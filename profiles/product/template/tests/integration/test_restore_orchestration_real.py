# ruff: noqa: ANN001, ANN003, ANN201, ANN202, ANN401, E501, S101, E402
"""Restore and replacement, end to end, against everything real (ADR 0013, layer 5).

A real PostgreSQL with row-level security forced, a real S3-compatible store, a real clamd, the
real finalizer, the real `file.scan` job, the real release gate and the real restore worker, and
signed URLs fetched over HTTP from the store. What is proved is the part of the restore that no
fake can show: that the replacement is a different object on a final key, that a URL issued
before it still reads the old bytes and only them, that the replacement is refused to everyone
until a *fresh* scan has said clean about *its* bytes -- and that those bytes, if they are
infected, are quarantined whatever the file's earlier verdict was.

* a clean, released file is replaced from a backup: the old object is untouched, the row names a
  new final key with no verdict and no identity, the gate refuses until the scanner stamps it, and
  then the gate signs a URL that serves exactly the restored bytes;
* a backup that holds a signature is restored and then quarantined, never released on the strength
  of the clean verdict the file had before;
* a file quarantined for its content is restored only as a new file, which is scanned on its own
  and released on its own, while the quarantined row stays as it was;
* a backup that does not match its recorded digest writes nothing anywhere.

Needs a database (`E2E_DATABASE_URL`), a store (`STORAGE_*`) and a scanner (`E2E_CLAMD_HOST`). It is
generated only into a product with `secure_files` and `storage_governance`, where the
generator-integration workflow runs it against all three and fails on any skip.
"""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

DATABASE_URL = os.environ.get("E2E_DATABASE_URL", "")
if DATABASE_URL:
    os.environ["DATABASE_URL"] = DATABASE_URL
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

STORE_ENV = ("STORAGE_ENDPOINT", "STORAGE_BUCKET", "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL
    or not all(os.environ.get(n) for n in STORE_ENV)
    or not os.environ.get("E2E_CLAMD_HOST"),
    reason="needs a database (E2E_DATABASE_URL), a store (STORAGE_*) and a scanner (E2E_CLAMD_HOST)",
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
pytest.importorskip("koras_worker")
from eicar_support import materialize  # noqa: E402
from koras_api.core.upload_window import is_final_key  # noqa: E402
from koras_worker.tasks import restore_scan  # noqa: E402
from koras_worker.tasks import scan as scan_task  # noqa: E402
from koras_worker.tasks.storage_restore import restore_approved  # noqa: E402
from test_release_orchestration_real import _ask, _refused  # noqa: E402
from test_scan_orchestration_real import CSV, Chain, chain, queue  # noqa: E402
from test_scan_runtime_real import AS_PROVISIONING, AS_TENANT, engine  # noqa: E402

assert chain and engine and queue  # re-exported fixtures

NEWER = b"name,amount\nacme,11\nglobex,22\ninitech,33\n"
OLDER_DIGEST = hashlib.sha256(CSV).hexdigest()


def _fetch(url: str) -> bytes:
    answer = httpx.get(url, timeout=30)
    assert answer.status_code == 200, answer.text
    return answer.content


@pytest.fixture(autouse=True)
def _restore_uses_the_chains_queue(chain: Chain, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(restore_scan, "queue_for", lambda _url: chain.queue)


async def _released_file(chain: Chain, body: bytes = CSV, name: str = "a.csv") -> tuple[str, str]:
    """A file as a released one is: finalized, scanned clean, and its attempt long past."""
    file_id, _ = await chain.upload(body, "text/csv", name=name)
    await chain.finalize(file_id)
    assert (await chain.run_job(file_id))["status"] == "clean"
    async with async_sessionmaker(chain.engine, expire_on_commit=False)() as session:
        await session.execute(AS_TENANT, {"tenant_id": chain.tenant})
        await session.execute(
            text(
                "update public.files set scan_attempted_at = now() - interval '2 hours' "
                "where id = cast(:f as uuid)"
            ),
            {"f": file_id},
        )
        await session.commit()
    return file_id, (await chain.row(file_id))["storage_key"]


async def _approved(
    chain: Chain,
    file_id: str,
    source_key: str,
    backup_bytes: bytes,
    *,
    overwrite: bool,
    recorded_digest: str | None = None,
) -> str:
    """An approved request, with the backup copy in the bucket where the restore will read it."""
    # One backup per (file, destination), and a test may restore the same file twice.
    stamp = uuid.uuid4()
    backup_key = f"tenants/{chain.tenant}/backups/{file_id}/{stamp}"
    chain.store.put(backup_key, backup_bytes, "text/csv")
    digest = recorded_digest or hashlib.sha256(backup_bytes).hexdigest()
    async with async_sessionmaker(chain.engine, expire_on_commit=False)() as session:
        await session.execute(AS_PROVISIONING)
        backup_id = (
            await session.execute(
                text(
                    "insert into public.file_backups (tenant_id, file_id, source_key, backup_key, "
                    " destination, size_bytes, source_digest, backup_digest, status) values "
                    "(cast(:t as uuid), cast(:f as uuid), :s, :b, :dest, :size, :d, :d, 'verified') "
                    "returning id::text"
                ),
                {
                    "t": chain.tenant,
                    "f": file_id,
                    "s": source_key,
                    "b": backup_key,
                    "dest": f"backups-{stamp}",
                    "size": len(backup_bytes),
                    "d": digest,
                },
            )
        ).scalar_one()
        await session.commit()
        await session.execute(AS_TENANT, {"tenant_id": chain.tenant})
        request_id = (
            await session.execute(
                text(
                    "insert into public.restore_requests (tenant_id, file_id, backup_id, reason, "
                    " overwrite, requested_by) values (cast(:t as uuid), cast(:f as uuid), "
                    " cast(:b as uuid), 'the file was damaged', :o, 'user-1') returning id::text"
                ),
                {"t": chain.tenant, "f": file_id, "b": backup_id, "o": overwrite},
            )
        ).scalar_one()
        await session.execute(
            text(
                "update public.restore_requests set status = 'approved', approved_by = 'user-2', "
                "approved_at = now() where id = cast(:i as uuid)"
            ),
            {"i": request_id},
        )
        await session.commit()
    return request_id


async def _restore(chain: Chain) -> tuple[tuple[int, int], list[tuple[str, str, datetime]]]:
    restored: list[tuple[str, str, datetime]] = []
    async with async_sessionmaker(chain.engine, expire_on_commit=False)() as session:
        counts = await restore_approved(session, chain.store, chain.store, restored=restored)  # type: ignore[arg-type]
    return counts, restored


async def _scan_what_was_asked_for(chain: Chain, restored) -> dict[str, Any]:
    """The restore's own request for the scan, then the job it enqueued, run by the handler."""
    before = len(chain.queue.jobs)
    await restore_scan.request_scans_for_restored({}, restored)
    # The recording queue answers `simulated` (it hands nothing to a worker), which the restore
    # rightly reports as not enqueued; what is asserted is the job it was handed.
    assert len(chain.queue.jobs) == before + len(restored)
    return await scan_task.scan_file_task({}, chain.queue.jobs[-1])


async def _request_status(chain: Chain, request_id: str) -> dict[str, Any]:
    async with async_sessionmaker(chain.engine, expire_on_commit=False)() as session:
        await session.execute(AS_TENANT, {"tenant_id": chain.tenant})
        row = (
            (
                await session.execute(
                    text(
                        "select status, error, restored_file_id::text as restored "
                        "from public.restore_requests where id = cast(:i as uuid)"
                    ),
                    {"i": request_id},
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


# -- a replacement of a released file ----------------------------------------------------------


async def test_a_replacement_is_refused_until_its_own_scan_says_clean_and_then_serves_its_bytes(
    chain: Chain,
) -> None:
    file_id, old_key = await _released_file(chain)
    released = await _ask(chain, file_id)
    assert released.storage_key == old_key
    old_row = await chain.row(file_id)
    old_etag = old_row["scan_object_etag"]
    assert old_etag, "the released file carries the identity its verdict was bound to"
    old_url = chain.store.presign_download(old_key, "a.csv", 300)
    assert _fetch(old_url) == CSV

    request_id = await _approved(chain, file_id, old_key, NEWER, overwrite=True)
    (done, failed), restored = await _restore(chain)
    assert (done, failed) == (1, 0)
    assert (await _request_status(chain, request_id))["status"] == "completed"

    # The row names a NEW object, on the shape of a finalized upload, with nothing of the old verdict.
    row = await chain.row(file_id)
    new_key = row["storage_key"]
    assert new_key != old_key and is_final_key(new_key)
    assert new_key.startswith(f"tenants/{chain.tenant}/documents/{file_id}/final/")
    assert (row["status"], row["scan_status"]) == ("ready", "pending")
    assert row["scan_object_etag"] is None and row["scan_attempts"] == 0
    assert row["checksum_sha256"] == hashlib.sha256(NEWER).hexdigest()
    assert row["checksum_verified_at"] is not None
    backups = [k for k in chain.keys() if "/backups/" in k]
    assert len(backups) == 1
    assert sorted(chain.keys()) == sorted([old_key, new_key, *backups])

    # Nobody can read the replacement yet; a URL issued earlier still reads the old bytes only.
    refused = await _refused(chain, file_id)
    assert (refused.status_code, refused.detail["code"]) == (409, "file_scan_pending")
    assert _fetch(old_url) == CSV
    assert _fetch(chain.store.presign_download(old_key, "a.csv", 300)) == CSV, "never overwritten"

    # A fresh scan decision, about the replacement.
    result = await _scan_what_was_asked_for(chain, restored)
    assert result["status"] == "clean", result
    after = await chain.row(file_id)
    assert (after["scan_status"], after["status"]) == ("clean", "ready")
    assert after["storage_key"] == new_key, "the verdict is bound to the object it read"
    assert after["scan_object_etag"] and after["scan_object_etag"] != old_etag

    served = await _ask(chain, file_id)
    assert served.storage_key == new_key
    assert _fetch(chain.store.presign_download(new_key, "a.csv", 300)) == NEWER
    assert _fetch(old_url) == CSV, "a stale URL never exposes the replacement's bytes"


async def test_restored_bytes_that_are_infected_are_quarantined_whatever_the_file_was_before(
    chain: Chain,
) -> None:
    """The earlier verdict is about the old bytes. The backup holds a signature; the replacement
    is judged on what it is, and the gate never opens for it."""
    file_id, old_key = await _released_file(chain)
    bad = materialize()
    await _approved(chain, file_id, old_key, bad, overwrite=True)
    (done, _), restored = await _restore(chain)
    assert done == 1

    refused = await _refused(chain, file_id)
    assert (refused.status_code, refused.detail["code"]) == (409, "file_scan_pending")
    result = await _scan_what_was_asked_for(chain, restored)

    assert result["status"] == "infected", result
    row = await chain.row(file_id)
    assert (row["scan_status"], row["status"]) == ("infected", "quarantined")
    refused = await _refused(chain, file_id)
    assert (refused.status_code, refused.detail["code"]) == (403, "file_quarantined")
    assert "eicar" not in str(refused.detail).lower()
    assert (await chain.row(file_id))["storage_key"] != old_key
    assert _fetch(chain.store.presign_download(old_key, "a.csv", 60)) == CSV, "the old object is intact"


# -- a file quarantined for its content --------------------------------------------------------


async def test_a_quarantined_file_comes_back_only_as_a_new_file_that_is_scanned_on_its_own(
    chain: Chain,
) -> None:
    file_id, _ = await chain.upload(materialize(), "text/plain", name="a.txt")
    await chain.finalize(file_id)
    assert (await chain.run_job(file_id))["status"] == "infected"
    condemned = await chain.row(file_id)

    # Replacing it in place is refused, with nothing written.
    in_place = await _approved(chain, file_id, condemned["storage_key"], CSV, overwrite=True)
    keys_before = sorted(chain.keys())
    (done, failed), restored = await _restore(chain)
    assert (done, failed) == (0, 1) and restored == []
    status = await _request_status(chain, in_place)
    assert status["status"] == "failed" and "infected" in status["error"]
    assert sorted(chain.keys()) == keys_before, "nothing reached the bucket for a refusal"

    # As a new object it is a different file, on its own verdict.
    await _approved(chain, file_id, condemned["storage_key"], CSV, overwrite=False)
    (done, _), restored = await _restore(chain)
    assert done == 1
    ((_, new_id, _),) = restored
    assert new_id != file_id
    fresh = await chain.row(new_id)
    assert (fresh["status"], fresh["scan_status"]) == ("ready", "pending")
    assert is_final_key(fresh["storage_key"])
    assert str(fresh["storage_key"]).startswith(f"tenants/{chain.tenant}/documents/{new_id}/final/")
    refused = await _refused(chain, new_id)
    assert (refused.status_code, refused.detail["code"]) == (409, "file_scan_pending")

    # The new row was created just now, so the scanner's read gate is closed for a window: a job
    # that runs early reads nothing, counts nothing and decides nothing. (The restore asks for the
    # job after the window; the test lets the window pass by moving the row's creation back.)
    early = await _scan_what_was_asked_for(chain, restored)
    assert early["status"] == "deferred", early
    unchanged = await chain.row(new_id)
    assert (unchanged["scan_status"], unchanged["scan_attempts"]) == ("pending", 0)
    async with async_sessionmaker(chain.engine, expire_on_commit=False)() as session:
        await session.execute(AS_TENANT, {"tenant_id": chain.tenant})
        await session.execute(
            text(
                "update public.files set created_at = now() - interval '2 hours' "
                "where id = cast(:f as uuid)"
            ),
            {"f": new_id},
        )
        await session.commit()
    result = await scan_task.scan_file_task({}, chain.queue.jobs[-1])
    assert result["status"] == "clean", result
    assert str((await _ask(chain, new_id)).id) == new_id
    assert _fetch(chain.store.presign_download(fresh["storage_key"], "a.csv", 60)) == CSV
    # And the quarantined row is exactly as it was.
    assert dict(await chain.row(file_id)) == dict(condemned)
    refused = await _refused(chain, file_id)
    assert (refused.status_code, refused.detail["code"]) == (403, "file_quarantined")


# -- a backup that is not what was recorded ----------------------------------------------------


async def test_a_backup_that_does_not_match_its_recorded_digest_writes_nothing(
    chain: Chain,
) -> None:
    file_id, old_key = await _released_file(chain)
    request_id = await _approved(
        chain, file_id, old_key, NEWER, overwrite=True, recorded_digest=OLDER_DIGEST
    )
    keys_before = sorted(chain.keys())
    before = await chain.row(file_id)

    (done, failed), restored = await _restore(chain)

    assert (done, failed) == (0, 1) and restored == []
    assert sorted(chain.keys()) == keys_before
    assert dict(await chain.row(file_id)) == dict(before), "the released file is as it was"
    assert (await _request_status(chain, request_id))["status"] == "failed"
    assert str((await _ask(chain, file_id)).id) == file_id, "and still releases"


async def test_a_restore_that_loses_its_scan_request_leaves_the_file_withheld_and_the_sweep_finds_it(
    chain: Chain,
) -> None:
    """The file is `pending` on a final key, so the scan sweep selects it with no help from the
    restore: a lost request delays the verdict, and never releases anything."""
    from koras_worker.tasks import scan_sweep

    file_id, old_key = await _released_file(chain)
    await _approved(chain, file_id, old_key, NEWER, overwrite=True)
    (done, _), _restored = await _restore(chain)
    assert done == 1
    # No request was made at all. Withheld.
    refused = await _refused(chain, file_id)
    assert (refused.status_code, refused.detail["code"]) == (409, "file_scan_pending")

    selected: list[str] = []
    cursor = scan_sweep.FairCursor()
    async with async_sessionmaker(chain.engine, expire_on_commit=False)() as session:
        await session.execute(AS_PROVISIONING)
        while not cursor.exhausted:
            page = await scan_sweep.select_due(
                session,
                config=scan_sweep.ScanSweepSettings(),
                now=datetime.now(UTC),
                cursor=cursor,
            )
            selected += [due.file_id for due in page]
            if not page:
                break
    assert file_id in selected, "the sweep finds a restored file on its own: it is on a final key"
