# ruff: noqa: ANN001, ANN003, ANN201, ANN202, ANN401, E501, S101, E402
"""Upload, finalization, hand-off, scan and verdict, against everything real (ADR 0013).

A real PostgreSQL with row-level security forced, a real S3-compatible store, a real clamd, the
real finalizer, the real hand-off, the real `file.scan` job and the real transitions. Nothing here
is a stand-in except the queue, which records what was enqueued and hands the job to the handler
the way the worker would.

What is proved is the order and what each step leaves behind:

* a finalized file is put on the queue as one `file.scan` job for its own tenant, and the job takes
  it to `clean` only when the scanner found nothing *and* the digest, identity and structural
  gates all passed -- a clean verdict binds the final key and the object's identity;
* EICAR is `infected`, quarantined, with one security event and no signature name anywhere;
* the ClamAV `OK` for a deflated, streamed ZIP64 entry is only a candidate: whatever the engine
  answers, that file is never `clean` (ADR 0013; `docs/CLAMD_SERVICE.md`);
* a scanner that cannot be reached holds the file `pending`, and the sweep brings back a file
  whose hand-off was lost;
* bytes that are not the claim are held `integrity_mismatch`, never scanned into `clean`.

Needs a database (`E2E_DATABASE_URL`), a store (`STORAGE_*`) and a scanner (`E2E_CLAMD_HOST`,
`E2E_CLAMD_PORT`). It is generated only into a product with `secure_files`, where the
generator-integration workflow runs it against all three and fails on any skip.
"""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

DATABASE_URL = os.environ.get("E2E_DATABASE_URL", "")
STORE_ENV = ("STORAGE_ENDPOINT", "STORAGE_BUCKET", "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY")
CLAMD_HOST = os.environ.get("E2E_CLAMD_HOST", "")
CLAMD_PORT = os.environ.get("E2E_CLAMD_PORT", "3310")
if DATABASE_URL:
    os.environ["DATABASE_URL"] = DATABASE_URL
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not all(os.environ.get(n) for n in STORE_ENV) or not CLAMD_HOST,
    reason="needs a database (E2E_DATABASE_URL), a store (STORAGE_*) and a scanner (E2E_CLAMD_HOST)",
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
pytest.importorskip("koras_worker")
from eicar_support import materialize  # noqa: E402
from koras_queue import JobEnvelope, RecordingJobQueue  # noqa: E402
from koras_storage import UPLOAD_PROVENANCE_META, Destination, Provider, S3ObjectStore  # noqa: E402
from koras_worker.tasks import finalize as finalize_task  # noqa: E402
from koras_worker.tasks import scan as scan_task  # noqa: E402
from koras_worker.tasks import scan_sweep  # noqa: E402
from koras_worker.uploads.finalize import FinalizeKind, UploadFinalizer  # noqa: E402
from test_scan_runtime_real import AS_PROVISIONING, AS_TENANT, _audit, _row, engine  # noqa: E402
from zip_support import real_docx, streamed_zip  # noqa: E402

assert engine  # re-exported fixture

CSV = b"name,amount\nacme,10\nglobex,20\n"
LONG_AGO = datetime.now(UTC) - timedelta(hours=2)  # the ticket was issued long ago
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _destination() -> Destination:
    return Destination(
        provider=Provider.SUPABASE,
        endpoint=os.environ["STORAGE_ENDPOINT"],
        bucket=os.environ["STORAGE_BUCKET"],
        region=os.environ.get("STORAGE_REGION", "us-east-1"),
        access_key=os.environ["STORAGE_ACCESS_KEY"],
        secret_key=os.environ["STORAGE_SECRET_KEY"],
    )


class _Queue(RecordingJobQueue):
    async def aclose(self) -> None:
        return None


class Chain:
    """One disposable tenant, its objects, and the steps of the chain."""

    def __init__(self, engine, queue: _Queue) -> None:
        self.engine = engine
        self.queue = queue
        self.tenant = str(uuid.uuid4())
        self.store = S3ObjectStore(_destination())
        self.client = self.store._client  # noqa: SLF001
        self.bucket = _destination().bucket

    def keys(self) -> list[str]:
        out: list[str] = []
        token = None
        while True:
            args: dict[str, Any] = {"Bucket": self.bucket, "Prefix": f"tenants/{self.tenant}/"}
            if token:
                args["ContinuationToken"] = token
            page = self.client.list_objects_v2(**args)
            out += [o["Key"] for o in page.get("Contents", [])]
            token = page.get("NextContinuationToken")
            if not token:
                return out

    def clean_up(self) -> None:
        for key in self.keys():
            self.store.delete(key)

    async def upload(
        self,
        body: bytes,
        content_type: str = "text/csv",
        *,
        claim: bytes | None = None,
        name: str = "a.csv",
    ) -> tuple[str, str]:
        """The state an honest upload leaves: a ready, pending row on an incoming key, and the
        object under it carrying the ticket's own upload id. `claim` is what the client said."""
        from koras_api.core.upload_window import incoming_key

        file_id, upload_id = str(uuid.uuid4()), str(uuid.uuid4())
        key = incoming_key(self.tenant, "documents", file_id, upload_id, name)
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            Metadata={UPLOAD_PROVENANCE_META: upload_id},
        )
        async with async_sessionmaker(self.engine, expire_on_commit=False)() as session:
            await session.execute(AS_PROVISIONING)
            await session.execute(
                text(
                    "insert into public.tenants (id, slug, name) values (cast(:t as uuid), :s, 'T') "
                    "on conflict (id) do nothing"
                ),
                {"t": self.tenant, "s": f"orch-{self.tenant[:8]}"},
            )
            await session.commit()
            await session.execute(AS_TENANT, {"tenant_id": self.tenant})
            await session.execute(
                text(
                    "insert into public.files (id, tenant_id, storage_key, name, size_bytes, "
                    "content_type, category, status, uploaded_by, scan_status, created_at, "
                    "checksum_sha256) values (cast(:f as uuid), cast(:t as uuid), :k, :n, :size, "
                    ":ct, 'documents', 'ready', 'u', 'pending', :created_at, :claim)"
                ),
                {
                    "f": file_id,
                    "t": self.tenant,
                    "k": key,
                    "n": name,
                    "size": len(body),
                    "ct": content_type,
                    "created_at": LONG_AGO,
                    "claim": hashlib.sha256(body if claim is None else claim).hexdigest(),
                },
            )
            await session.commit()
        return file_id, key

    async def finalize(self, file_id: str, *, hand_off: bool = True) -> dict[str, Any]:
        """One `file.finalize` job's worth of work, with the real hand-off (or none)."""
        on_final = None
        if hand_off:

            async def on_final(tenant_id: str, fid: str) -> object:
                return await scan_task.hand_off_to_scanner({}, tenant_id, fid)

        async with async_sessionmaker(self.engine, expire_on_commit=False)() as session:
            return await finalize_task.finalize_one(
                session,
                UploadFinalizer(self.store),  # type: ignore[arg-type]
                tenant_id=self.tenant,
                file_id=file_id,
                now=datetime.now(UTC),
                max_attempts=8,
                on_final=on_final,
            )

    def jobs_for(self, file_id: str) -> list[JobEnvelope]:
        return [j for j in self.queue.jobs if j.payload.get("file_id") == file_id]

    async def run_job(self, file_id: str) -> dict[str, Any]:
        (job,) = self.jobs_for(file_id)
        return await scan_task.scan_file_task({}, job)

    async def row(self, file_id: str) -> dict[str, Any]:
        return await _row(self.engine, self.tenant, file_id)

    async def actions(self, file_id: str) -> list[str]:
        return [a for a, _, _ in await _audit(self.engine, self.tenant, file_id)]


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> _Queue:
    recorded = _Queue()
    monkeypatch.setattr(scan_task, "queue_for", lambda url: recorded)
    monkeypatch.setenv("FILE_SCAN_BACKEND", "clamd")
    monkeypatch.setenv("FILE_SCAN_CLAMD_HOST", CLAMD_HOST)
    monkeypatch.setenv("FILE_SCAN_CLAMD_PORT", CLAMD_PORT)
    return recorded


@pytest.fixture
def chain(engine, queue: _Queue):
    built = Chain(engine, queue)
    try:
        yield built
    finally:
        built.clean_up()
        assert built.keys() == [], "the experiment left objects in the store"


# ---------------------------------------------------------------------------- the clean path


async def test_an_upload_is_finalized_handed_off_scanned_and_released_clean(chain: Chain) -> None:
    file_id, incoming = await chain.upload(CSV)

    done = await chain.finalize(file_id)
    assert done["status"] == FinalizeKind.FINALIZED.value
    after_finalize = await chain.row(file_id)
    assert after_finalize["scan_status"] == "pending", "finalization decides nothing about content"
    assert after_finalize["storage_key"] != incoming and "/final/" in after_finalize["storage_key"]
    assert after_finalize["checksum_verified_at"] is not None

    (job,) = chain.jobs_for(file_id)
    assert job.task == "file.scan" and job.tenant_id == chain.tenant
    assert dict(job.payload) == {"file_id": file_id}
    assert job.idempotency_key == f"scan:{file_id}"

    result = await chain.run_job(file_id)
    assert result["status"] == "clean", result
    row = await chain.row(file_id)
    assert (row["scan_status"], row["status"]) == ("clean", "ready")
    assert row["scan_failure"] is None and row["scan_object_etag"]
    assert row["storage_key"] == after_finalize["storage_key"], "the verdict binds the final key"
    assert row["scan_attempts"] >= 2, "the finalizer's attempt and the scanner's are both counted"
    actions = await chain.actions(file_id)
    assert "storage.upload.finalized" in actions and actions.count("storage.object.scanned") == 1


async def test_a_genuine_office_document_is_released_after_the_structural_gate(chain: Chain) -> None:
    body = real_docx()
    file_id, _ = await chain.upload(body, DOCX_TYPE, name="a.docx")
    await chain.finalize(file_id)
    assert (await chain.run_job(file_id))["status"] == "clean"


# ------------------------------------------------------------------------ the infected path


async def test_eicar_is_infected_quarantined_and_leaves_no_signature_name(chain: Chain) -> None:
    file_id, _ = await chain.upload(materialize(), "text/plain", name="a.txt")
    await chain.finalize(file_id)
    result = await chain.run_job(file_id)
    assert result["status"] == "infected", result
    row = await chain.row(file_id)
    assert (row["scan_status"], row["status"]) == ("infected", "quarantined")
    assert row["scan_object_etag"] is None
    actions = await chain.actions(file_id)
    assert actions.count("storage.object.quarantined") == 1
    assert "storage.object.scanned" not in actions
    stored = " ".join(str(v) for v in row.values()).lower()
    assert "eicar" not in stored, "a signature name never reaches the database"
    audit = str(await _audit(chain.engine, chain.tenant, file_id)).lower()
    assert "eicar" not in audit


# ------------------------------------------ a candidate is not a release (the ZIP64 gap)


async def test_a_streamed_deflated_zip64_entry_is_never_released_clean_whatever_the_engine_says(
    chain: Chain,
) -> None:
    body = streamed_zip(force_zip64=True, payload=materialize())
    file_id, _ = await chain.upload(body, "application/zip", name="a.zip")
    await chain.finalize(file_id)
    result = await chain.run_job(file_id)
    row = await chain.row(file_id)
    assert row["scan_status"] != "clean", result
    if result["status"] == "held":
        # The engine answered OK (the documented gap) and the structural gate held it.
        assert row["scan_status"] == "pending"
        assert row["scan_failure"] == "inspection_incomplete"
    else:
        # The day the engine inspects this form it says FOUND: infected, never clean.
        assert result["status"] == "infected"


async def test_an_engine_ok_for_a_streamed_zip64_entry_is_held_by_the_structural_gate(
    chain: Chain,
) -> None:
    """The engine answers OK (a candidate) for this form; the product's own gate holds it."""
    body = streamed_zip(force_zip64=True)
    file_id, _ = await chain.upload(body, "application/zip", name="a.zip")
    await chain.finalize(file_id)
    result = await chain.run_job(file_id)
    assert result["status"] == "held" and result["failure"] == "inspection_incomplete", result
    row = await chain.row(file_id)
    assert (row["scan_status"], row["scan_failure"]) == ("pending", "inspection_incomplete")
    assert "storage.object.scanned" not in await chain.actions(file_id)


async def test_the_same_content_in_an_ordinary_archive_is_found_by_the_engine(chain: Chain) -> None:
    body = streamed_zip(force_zip64=False, payload=materialize())
    file_id, _ = await chain.upload(body, "application/zip", name="a.zip")
    await chain.finalize(file_id)
    assert (await chain.run_job(file_id))["status"] == "infected"


# ---------------------------------------------------------------------------- holds


async def test_a_scanner_that_cannot_be_reached_holds_the_file_pending(
    chain: Chain, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_id, _ = await chain.upload(CSV)
    await chain.finalize(file_id)
    monkeypatch.setenv("FILE_SCAN_CLAMD_HOST", "127.0.0.1")
    monkeypatch.setenv("FILE_SCAN_CLAMD_PORT", "9")  # the discard port: nothing listens
    monkeypatch.setenv("FILE_SCAN_CONNECT_TIMEOUT_SECONDS", "1")
    result = await chain.run_job(file_id)
    assert result["status"] == "held" and result["failure"] == "scanner_unavailable"
    row = await chain.row(file_id)
    assert (row["scan_status"], row["scan_failure"]) == ("pending", "scanner_unavailable")
    assert "storage.object.scanned" not in await chain.actions(file_id)


async def test_bytes_that_are_not_the_claim_are_never_scanned_into_clean(chain: Chain) -> None:
    file_id, _ = await chain.upload(CSV)
    await chain.finalize(file_id)
    row = await chain.row(file_id)
    # The final object is replaced after finalization (a provider fault, a bug, an insider).
    other = b"name,amount\nevil,99\nzzzzzz,00\n"
    assert len(other) == len(CSV)
    chain.client.put_object(Bucket=chain.bucket, Key=row["storage_key"], Body=other)
    result = await chain.run_job(file_id)
    assert result["status"] == "held" and result["failure"] in {
        "integrity_mismatch",
        "object_changed",
    }, result
    assert (await chain.row(file_id))["scan_status"] == "pending"


async def test_a_file_still_on_its_incoming_key_is_never_read_by_the_scanner(
    chain: Chain, queue: _Queue
) -> None:
    file_id, incoming = await chain.upload(CSV)
    # A job that arrives early (a stale one, a forged one): nothing is read, counted or written.
    job = JobEnvelope(
        task="file.scan",
        tenant_id=chain.tenant,
        payload={"file_id": file_id},
        idempotency_key=f"scan:{file_id}",
    )
    result = await scan_task.scan_file_task({}, job)
    assert result == {"status": "not_eligible"}
    row = await chain.row(file_id)
    assert row["storage_key"] == incoming and row["scan_attempts"] == 0
    assert (row["scan_status"], row["scan_failure"]) == ("pending", None)


async def test_another_tenants_job_finds_nothing(chain: Chain) -> None:
    file_id, _ = await chain.upload(CSV)
    await chain.finalize(file_id)
    job = JobEnvelope(
        task="file.scan",
        tenant_id=str(uuid.uuid4()),
        payload={"file_id": file_id},
        idempotency_key=f"scan:{file_id}",
    )
    assert (await scan_task.scan_file_task({}, job))["status"] == "not_eligible"
    assert (await chain.row(file_id))["scan_status"] == "pending"


# ------------------------------------------------------------- a lost hand-off is recovered


async def test_a_lost_hand_off_leaves_the_file_pending_and_the_sweep_scans_it(
    chain: Chain, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_id, _ = await chain.upload(CSV)

    def down(url: str) -> Any:
        raise ConnectionError("the queue is down")

    monkeypatch.setattr(scan_task, "queue_for", down)
    done = await chain.finalize(file_id)
    assert done["status"] == "finalized", "a lost hand-off never fails a finalized file"
    assert chain.jobs_for(file_id) == []
    row = await chain.row(file_id)
    assert (row["scan_status"], row["status"]) == ("pending", "ready")

    # Later: the sweep. Far enough on that the finalizer's own attempt has backed off.
    class Live(_Queue):
        async def enqueue(self, task, **kwargs):
            result = await super().enqueue(task, **kwargs)
            from koras_queue import Enqueued

            return Enqueued(task=result.task, job_id=result.job_id)

    swept = Live()
    config = scan_sweep.ScanSweepSettings(
        file_scan_backend="clamd",
        file_scan_sweep_not_before=LONG_AGO - timedelta(days=1),
        file_scan_sweep_batch_size=500,
        file_scan_sweep_max_batches=20,
    )

    async def forget(job_id: str) -> None:
        return None

    async with async_sessionmaker(chain.engine, expire_on_commit=False)() as session:
        report = await scan_sweep.sweep(
            session, swept, forget, config=config, now=datetime.now(UTC) + timedelta(hours=3)
        )
    assert report.state == "ran" and report.enqueued >= 1
    queued = [j for j in swept.jobs if j.payload.get("file_id") == file_id]
    assert len(queued) == 1 and queued[0].tenant_id == chain.tenant
    result = await scan_task.scan_file_task({}, queued[0])
    assert result["status"] == "clean", result


async def test_a_file_on_an_incoming_key_is_not_selected_by_the_scan_sweep(chain: Chain) -> None:
    file_id, _ = await chain.upload(CSV)
    config = scan_sweep.ScanSweepSettings(
        file_scan_backend="clamd",
        file_scan_sweep_not_before=LONG_AGO - timedelta(days=1),
    )
    cursor = scan_sweep.FairCursor()
    found: set[str] = set()
    for _ in range(20):
        if cursor.exhausted:
            break
        async with async_sessionmaker(chain.engine, expire_on_commit=False)() as session:
            page = await scan_sweep.select_due(
                session, config=config, now=datetime.now(UTC) + timedelta(hours=3), cursor=cursor
            )
        if not page:
            break
        found |= {d.file_id for d in page}
    assert file_id not in found
