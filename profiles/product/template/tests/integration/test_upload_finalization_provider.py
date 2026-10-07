# ruff: noqa: ANN001, ANN201, ANN202, ANN401, E501, S101, E402, S310, S324
"""Immutable upload finalization against a real S3-compatible object store (ADR 0013).

A signed PUT begun inside its window can finish after it, can replace bytes a verifier has already
read, and can be reused until expiry, and the provider offers no version, checksum or conditional
write to bind a verdict to bytes. This suite shows what the finalization does about each of those,
with a real store: real signed URLs, real HTTP PUTs (one held in flight past the ticket's expiry),
the real `S3ObjectStore` copy, the real finalizer and its job, and a real PostgreSQL for the row.

Disposable objects only. Every key is under `tenants/<a fresh random tenant>/`, a tenant no row
has, so no listing, reconciliation or sweep can see it; every object is deleted at the end and the
prefix is listed to prove it is empty. Prints no credential.

Needs a store and a database; generated only into a product with `secure_files`, where the
generator-integration workflow runs it against MinIO and the round-trip database and fails on any
skip. Locally, set E2E_DATABASE_URL and STORAGE_ENDPOINT, STORAGE_BUCKET, STORAGE_ACCESS_KEY and
STORAGE_SECRET_KEY, then run pytest on tests/integration/test_upload_*_provider.py.
"""

from __future__ import annotations

import hashlib
import http.client
import os
import ssl
import sys
import threading
import time
import urllib.parse
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get("E2E_DATABASE_URL", "")
STORE_ENV = ("STORAGE_ENDPOINT", "STORAGE_BUCKET", "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY")
if DATABASE_URL:
    os.environ["DATABASE_URL"] = DATABASE_URL
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not all(os.environ.get(n) for n in STORE_ENV),
    reason="needs an object store (STORAGE_*) and a database (E2E_DATABASE_URL)",
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
pytest.importorskip("koras_worker")
from koras_api.core.upload_window import FINALIZE_DELAY_SECONDS, incoming_key, is_incoming_key
from koras_storage import Destination, Provider, S3ObjectStore, upload_guard_headers
from koras_worker.tasks import finalize as finalize_task
from koras_worker.uploads.finalize import FinalizeKind, UploadFinalizer

AS_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")
AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)
CT = "text/csv"
LONG_AGO = datetime.now(UTC) - timedelta(hours=2)  # the file's ticket was issued long ago
NOW = datetime.now(UTC)


def _destination() -> Destination:
    return Destination(
        provider=Provider.SUPABASE,
        endpoint=os.environ["STORAGE_ENDPOINT"],
        bucket=os.environ["STORAGE_BUCKET"],
        region=os.environ.get("STORAGE_REGION", "us-east-1"),
        access_key=os.environ["STORAGE_ACCESS_KEY"],
        secret_key=os.environ["STORAGE_SECRET_KEY"],
    )


class Run:
    """One disposable tenant prefix, and everything the experiments need to touch it."""

    def __init__(self) -> None:
        self.tenant = str(uuid.uuid4())
        self.destination = _destination()
        self.store = S3ObjectStore(self.destination)
        self.client = self.store._client  # noqa: SLF001 - provider answers the Protocol hides
        self.bucket = self.destination.bucket
        self.prefix = f"tenants/{self.tenant}/"
        #: What each ticket's holder must send, exactly: the headers the URL signed .
        self.headers: dict[str, dict[str, str]] = {}

    # -- the client's side: real signed URLs and real HTTP -----------------------------------

    def ticket(
        self,
        file_id: str,
        size: int,
        expires_in: int = 600,
        *,
        claim: bytes | None = None,
        guarded: bool = True,
    ) -> tuple[str, str]:
        """A real signed URL, signed as the API signs it unless a test says otherwise.

        `claim`: sign `x-amz-checksum-sha256` for these bytes (the API always does; most tests
        here leave it off so that a provider that did not enforce it is what is being modelled).
        `guarded=False` signs no copy-source guard and no provenance (a ticket from before
        the capability, or a provider that ignored them).
        """
        upload_id = str(uuid.uuid4())
        key = incoming_key(self.tenant, "documents", file_id, upload_id, "a.csv")
        digest = hashlib.sha256(claim).hexdigest() if claim is not None else None
        url = self.store.presign_upload(
            key, CT, size, expires_in, digest, provenance=upload_id if guarded else None
        )
        headers = {"Content-Type": CT}
        if digest is not None:
            import base64

            headers["x-amz-checksum-sha256"] = base64.b64encode(bytes.fromhex(digest)).decode()
        if guarded:
            headers.update(upload_guard_headers(upload_id))
        self.headers[url] = headers
        return key, url

    @staticmethod
    def _connect(url: str, *, timeout: int) -> http.client.HTTPConnection:
        """A plain connection for an http endpoint (a local store), TLS for https."""
        parts = urllib.parse.urlsplit(url)
        if parts.scheme == "http":
            return http.client.HTTPConnection(parts.netloc, timeout=timeout)
        return http.client.HTTPSConnection(
            parts.netloc, timeout=timeout, context=ssl.create_default_context()
        )

    @staticmethod
    def _split(url: str) -> tuple[str, str]:
        parts = urllib.parse.urlsplit(url)
        return parts.netloc, parts.path + "?" + parts.query

    def put(
        self,
        url: str,
        body: bytes,
        *,
        path_key: str | None = None,
        extra: dict[str, str] | None = None,
        only: dict[str, str] | None = None,
    ) -> int:
        """A PUT with the ticket's headers (`only` replaces them; `extra` adds to them)."""
        headers = {**(only if only is not None else self.headers.get(url, {"Content-Type": CT}))}
        headers.update(extra or {})
        host, path = self._split(url)
        if path_key is not None:  # a client re-aiming the same signature at another key
            split = urllib.parse.urlsplit(url)
            prefix = split.path[: split.path.index("/tenants/")]
            path = f"{prefix}/{urllib.parse.quote(path_key, safe='/')}?{split.query}"
        conn = self._connect(url, timeout=300)
        conn.request("PUT", path, body=body, headers={**headers, "Content-Length": str(len(body))})
        status = conn.getresponse().status
        conn.close()
        return status

    def slow_put(
        self, url: str, body: bytes, every: float, started: threading.Event, out: dict
    ) -> None:
        """Headers now, the body one byte at a time: in flight for len(body) * every seconds."""
        host, path = self._split(url)
        conn = self._connect(url, timeout=600)
        conn.putrequest("PUT", path)
        for name, value in self.headers.get(url, {"Content-Type": CT}).items():
            conn.putheader(name, value)
        conn.putheader("Content-Length", str(len(body)))
        conn.endheaders()
        started.set()
        for byte in body:
            conn.send(bytes([byte]))
            time.sleep(every)
        out["status"] = conn.getresponse().status
        out["done_at"] = time.time()
        conn.close()

    # -- the provider's answers ----------------------------------------------------------------

    def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    def etag(self, key: str) -> str:
        return self.client.head_object(Bucket=self.bucket, Key=key)["ETag"].strip('"')

    def keys(self) -> list[str]:
        out, token = [], None
        while True:
            args = {"Bucket": self.bucket, "Prefix": self.prefix}
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


@pytest.fixture
def run():
    experiment = Run()
    try:
        yield experiment
    finally:
        experiment.clean_up()
        remaining = experiment.keys()
        assert remaining == [], f"the experiment left {len(remaining)} object(s) in the store"


@pytest.fixture
async def engine():
    created = create_async_engine(DATABASE_URL)
    async with async_sessionmaker(created, expire_on_commit=False)() as probe:
        who = (
            await probe.execute(
                text("select rolsuper or rolbypassrls from pg_roles where rolname = current_user")
            )
        ).scalar_one()
        assert not who, "run this as the restricted application role, never a superuser"
    try:
        yield created
    finally:
        await created.dispose()


async def _seed(
    engine,
    run: Run,
    file_id: str,
    key: str,
    size: int,
    created_at=LONG_AGO,
    claim: bytes | None = None,
) -> None:
    """The file's row, with the content claim the upload was authorized for .

    The claim defaults to `A`, the bytes an honest upload sends; `claim=None` here means that
    default, and a test wanting no claim at all passes the empty marker below.
    """
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await session.execute(AS_PROVISIONING)
        await session.execute(
            text(
                "insert into public.tenants (id, slug, name) values (cast(:t as uuid), :s, 'T') "
                "on conflict (id) do nothing"
            ),
            {"t": run.tenant, "s": f"prov-{run.tenant[:8]}"},
        )
        await session.commit()
        await session.execute(AS_TENANT, {"tenant_id": run.tenant})
        await session.execute(
            text(
                "insert into public.files (id, tenant_id, storage_key, name, size_bytes, "
                "content_type, category, status, uploaded_by, scan_status, created_at, "
                "checksum_sha256) values "
                "(cast(:f as uuid), cast(:t as uuid), :k, 'a.csv', :size, :ct, 'documents', "
                "'ready', 'u', 'pending', :created_at, :claim)"
            ),
            {
                "claim": hashlib.sha256(A if claim is None else claim).hexdigest(),
                "f": file_id,
                "t": run.tenant,
                "k": key,
                "size": size,
                "ct": CT,
                "created_at": created_at,
            },
        )
        await session.commit()


async def _row(engine, run: Run, file_id: str) -> dict:
    async with async_sessionmaker(engine, expire_on_commit=False)() as reader:
        await reader.execute(AS_TENANT, {"tenant_id": run.tenant})
        return dict(
            (
                await reader.execute(
                    text("select * from public.files where id = cast(:f as uuid)"), {"f": file_id}
                )
            )
            .mappings()
            .one()
        )


async def _finalize(engine, run: Run, file_id: str):
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        return await UploadFinalizer(run.store).finalize(  # type: ignore[arg-type]
            session, tenant_id=run.tenant, file_id=file_id, now=NOW
        )


async def _job(engine, run: Run, file_id: str):
    """One `file.finalize` job's worth of work against the real store."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        return await finalize_task.finalize_one(
            session,
            UploadFinalizer(run.store),  # type: ignore[arg-type]
            tenant_id=run.tenant,
            file_id=file_id,
            now=NOW,
            max_attempts=8,
        )


A = b"name,amount\nacme,10\nglobex,20\n"
B = b"name,amount\nevil,99\nzzzzzz,00\n"
assert len(A) == len(B)
MD5 = lambda b: hashlib.md5(b).hexdigest()  # noqa: E731


# --- 1, 3, 4: a client writes the incoming key only, and finalization makes a distinct object ----


async def test_a_client_put_and_a_reused_ticket_change_the_incoming_key_and_finalization_copies_the_last(
    engine, run
) -> None:
    file_id = str(uuid.uuid4())
    key, url = run.ticket(file_id, len(A))
    assert run.put(url, A) == 200 and run.get(key) == A
    assert run.put(url, B) == 200 and run.get(key) == B  # reuse before expiry: incoming only
    assert run.put(url, A) == 200 and run.get(key) == A
    assert run.put(url, B) == 200
    assert run.put(url, A) == 200  # the last write is the claimed content 
    assert run.keys() == [key], "every write so far has been to the one key the ticket names"

    await _seed(engine, run, file_id, key, len(A))
    incoming_etag = run.etag(key)
    outcome = await _finalize(engine, run, file_id)
    assert outcome.kind is FinalizeKind.FINALIZED
    final = outcome.key
    assert final != key and not is_incoming_key(final)
    assert f"/{file_id}/final/" in final
    # A distinct object: its own key, holding the bytes the incoming key held when it was copied.
    assert run.get(final) == A
    assert run.keys() == [final], "the incoming object was removed once the row named the final one"
    # Recorded for the evidence: on this provider a single-part copy of identical bytes carries
    # the same MD5 ETag, so the *key*, not the ETag, is what makes the final object distinct.
    print(f"EVIDENCE etag_incoming={incoming_etag} etag_final={run.etag(final)}")
    assert (await _row(engine, run, file_id))["storage_key"] == final


# --- 5: a client cannot write the final key ----------------------------------------------------


async def test_a_client_cannot_put_to_the_final_key_with_the_ticket_it_holds_or_with_none(
    engine, run
) -> None:
    file_id = str(uuid.uuid4())
    key, url = run.ticket(file_id, len(A))
    assert run.put(url, A) == 200
    await _seed(engine, run, file_id, key, len(A))
    final = (await _finalize(engine, run, file_id)).key
    before = (run.get(final), run.etag(final))

    # The same signature aimed at the final key: the signature covers the key, so it is refused.
    reaimed = run.put(url, B, path_key=final)
    print(f"EVIDENCE reaimed_signature_status={reaimed}")
    assert reaimed == 403
    # No signature at all.
    split = urllib.parse.urlsplit(url)
    prefix = split.path[: split.path.index("/tenants/")]
    bare = f"{split.scheme}://{split.netloc}{prefix}/{urllib.parse.quote(final, safe='/')}"
    unsigned = run.put(bare, B)
    print(f"EVIDENCE unsigned_put_status={unsigned}")
    assert unsigned in {400, 401, 403}
    assert (run.get(final), run.etag(final)) == before


# --- 2, 6, 7, 8: a request in flight past expiry --------------------------------------------


async def test_a_put_in_flight_past_the_ticket_expiry_cannot_alter_the_final_object(
    engine, run
) -> None:
    file_id = str(uuid.uuid4())
    key, url = run.ticket(file_id, len(B), expires_in=10)
    # The honest upload, inside the window.
    assert run.put(url, A) == 200

    # A second request on the same ticket, begun inside the window, held open one byte at a
    # time: the provider accepts it because it began before expiry.
    started, outcome = threading.Event(), {}
    thread = threading.Thread(target=run.slow_put, args=(url, B, 2.0, started, outcome))
    thread.start()
    assert started.wait(5)
    begun = time.time()

    await _seed(engine, run, file_id, key, len(A))
    # Wait until the ticket is dead and the request is plainly still in flight, then finalize.
    time.sleep(max(0.0, 16 - (time.time() - begun)))
    assert thread.is_alive(), "the held request must still be in flight after the ticket expired"
    final_run = await _job(engine, run, file_id)
    assert final_run["status"] == "finalized"
    row = await _row(engine, run, file_id)
    final = row["storage_key"]
    assert not is_incoming_key(final)
    etag_at_finalization, bytes_at_finalization = run.etag(final), run.get(final)
    assert bytes_at_finalization == A and etag_at_finalization == MD5(A)

    thread.join(timeout=120)
    assert outcome.get("status") == 200, "the late request is accepted by the provider, as measured"
    landed_after = outcome["done_at"] - begun
    print(f"EVIDENCE late_put_landed_{landed_after:.1f}s_after_start etag={etag_at_finalization}")

    # It landed on the incoming key. The object that was finalized did not move.
    assert run.get(key) == B, "the incoming key took the late write"
    assert run.get(final) == A and run.etag(final) == etag_at_finalization
    assert (await _row(engine, run, file_id))["storage_key"] == final


async def test_a_reused_ticket_after_finalization_still_cannot_reach_the_final_object(
    engine, run
) -> None:
    file_id = str(uuid.uuid4())
    key, url = run.ticket(file_id, len(A), expires_in=600)
    assert run.put(url, A) == 200
    await _seed(engine, run, file_id, key, len(A))
    assert (await _job(engine, run, file_id))["status"] == "finalized"
    row = await _row(engine, run, file_id)
    final, etag = row["storage_key"], run.etag(row["storage_key"])
    assert run.put(url, B) == 200, "the ticket is still valid and writes the incoming key"
    assert run.get(key) == B
    assert run.get(final) == A and run.etag(final) == etag


# --- 9, 12: retries and concurrent attempts, against the real store ----------------------------


async def test_a_finalization_retry_is_idempotent_and_leaves_one_object(engine, run) -> None:
    file_id = str(uuid.uuid4())
    key, url = run.ticket(file_id, len(A))
    assert run.put(url, A) == 200
    await _seed(engine, run, file_id, key, len(A))
    first = await _finalize(engine, run, file_id)
    second = await _finalize(engine, run, file_id)
    assert (first.kind, second.kind) == (FinalizeKind.FINALIZED, FinalizeKind.ALREADY_FINAL)
    assert run.keys() == [first.key] and second.key == first.key


async def test_two_concurrent_finalizations_against_the_real_store_leave_exactly_one_object(
    engine, run
) -> None:
    import asyncio

    file_id = str(uuid.uuid4())
    key, url = run.ticket(file_id, len(A))
    assert run.put(url, A) == 200
    await _seed(engine, run, file_id, key, len(A))
    results = await asyncio.gather(_finalize(engine, run, file_id), _finalize(engine, run, file_id))
    assert sorted(r.kind.value for r in results) in (
        ["already_final", "finalized"],
        ["finalized", "not_eligible"],
    )
    row = await _row(engine, run, file_id)
    assert run.keys() == [row["storage_key"]], (
        "one referenced object, and the loser removed its own"
    )


# --- the horizon is not what protects it -------------------------------------------------------


async def test_a_run_before_the_horizon_touches_nothing_in_the_store(engine, run) -> None:
    file_id = str(uuid.uuid4())
    key, url = run.ticket(file_id, len(A))
    assert run.put(url, A) == 200
    await _seed(
        engine,
        run,
        file_id,
        key,
        len(A),
        created_at=NOW - timedelta(seconds=FINALIZE_DELAY_SECONDS - 30),
    )
    outcome = await _finalize(engine, run, file_id)
    assert outcome.kind is FinalizeKind.POSTPONED
    assert run.keys() == [key] and run.get(key) == A
