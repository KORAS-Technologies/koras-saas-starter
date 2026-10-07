# ruff: noqa: ANN001, ANN002, ANN003, ANN201, ANN202, ANN401, E501, S101, E402
"""A restore that replaces a file's bytes, against a real PostgreSQL with RLS on (ADR 0013, layer 5).

A scripted session has no row locks, no second connection, no trigger and no policy, so it
cannot show what the replacement rests on: that it is a *new* object on a *final* key and the old
one is untouched, that the verdict and every piece of evidence about the old bytes is gone in the
same statement that points the row at the new ones, that a refusal writes nothing, that a
failure part-way leaves the old state whole, and that the scanner's own transitions racing the
restore cannot produce a `clean` replacement. The bucket is an in-memory fake: what is under
test is which key the row names and what the row says about it, not a provider (the real store
and the real scanner are `test_restore_orchestration_real.py`).

Needs a database, on the variable `playwright.config.ts` names. The role in `E2E_DATABASE_URL`
must be the restricted application role, not a superuser; the test refuses to run as one. It is
generated only into a product with `secure_files` and `storage_governance`, where the
generator-integration workflow runs it and fails on any skip.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get("E2E_DATABASE_URL", "")

if DATABASE_URL:
    os.environ["DATABASE_URL"] = DATABASE_URL
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="needs a real PostgreSQL; set E2E_DATABASE_URL (see playwright.config.ts)",
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
pytest.importorskip("koras_worker")
from koras_api.core.file_release import releasable  # noqa: E402
from koras_api.core.file_release_gate import read_releasable, row_releasable  # noqa: E402
from koras_api.core.upload_window import is_final_key  # noqa: E402
from koras_worker.scanning import TransitionKind, commit_infected  # noqa: E402
from koras_worker.scanning.objects import ObjectReference  # noqa: E402
from koras_worker.tasks import restore_scan, storage_restore  # noqa: E402
from koras_worker.tasks.storage_restore import restore_approved  # noqa: E402
from restore_support import (  # noqa: E402
    NAME,
    NEW,
    NEW_DIGEST,
    OLD,
    OLD_DIGEST,
    MemStore,
    Queue,
    final_key,
)

AS_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")
AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)

#: Every column of `public.files`, classed. A column added later has to be put in one of these
#: two sets, which is the moment somebody asks whether it is evidence about the bytes.
RESET_BY_REPLACEMENT = {
    "storage_key", "size_bytes", "checksum_sha256", "checksum_verified_at", "status",
    "backup_status", "backed_up_at", "archived_at",
    "scan_status", "scan_note", "scan_attempts", "scan_attempted_at", "scan_failure",
    "scan_object_etag", "indexed_at", "index_note",
}  # fmt: skip
NOT_ABOUT_THE_BYTES = {
    "id", "tenant_id", "name", "content_type", "uploaded_by", "created_at", "ready_at",
    "organization_id", "category", "classification", "retention_policy", "retain_until",
    "legal_hold", "entity_type", "entity_id",
    "workspace_id", "version",
}  # fmt: skip


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


@pytest.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as opened:
        yield opened


@pytest.fixture
def queue(monkeypatch) -> Queue:
    live = Queue()
    monkeypatch.setattr(restore_scan, "queue_for", lambda _url: live)
    return live


async def _tenant(session: AsyncSession) -> str:
    tenant = str(uuid.uuid4())
    await session.execute(AS_PROVISIONING)
    await session.execute(
        text("insert into public.tenants (id, slug, name) values (cast(:t as uuid), :s, 'T')"),
        {"t": tenant, "s": f"rr-{tenant[:8]}"},
    )
    await session.commit()
    return tenant


async def _file(
    session: AsyncSession,
    tenant: str,
    *,
    status: str = "ready",
    scan_status: str = "clean",
    attempted_minutes_ago: int | None = 120,
    created_days_ago: int = 400,
    indexed: bool = True,
) -> tuple[str, str]:
    """A file as a released one looks: a verdict, its evidence and its index, all about OLD."""
    file_id = str(uuid.uuid4())
    key = final_key(tenant, file_id)
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    await session.execute(
        text(
            "insert into public.files (id, tenant_id, storage_key, name, size_bytes, content_type, "
            " category, status, uploaded_by, created_at, scan_status, scan_note, scan_attempts, "
            " scan_attempted_at, scan_object_etag, checksum_sha256, checksum_verified_at, "
            " indexed_at, index_note, backup_status) values "
            "(cast(:f as uuid), cast(:t as uuid), :k, :n, :size, 'application/pdf', 'documents', "
            " :status, 'u', now() - make_interval(days => :age), :scan, 'scanned clean', 2, "
            " case when cast(:ago as int) is null then null "
            "      else now() - make_interval(mins => cast(:ago as int)) end, "
            " 'etag-of-the-old-object', :digest, now() - interval '1 day', "
            " case when :indexed then now() end, case when :indexed then '3 chunk(s)' end, "
            " 'verified')"
        ),
        {
            "f": file_id, "t": tenant, "k": key, "n": NAME, "size": len(OLD), "status": status,
            "age": created_days_ago, "scan": scan_status, "ago": attempted_minutes_ago,
            "digest": OLD_DIGEST, "indexed": indexed,
        },
    )  # fmt: skip
    await session.commit()
    return file_id, key


def _releasable(row, tenant: str) -> bool:
    """The one release rule, asked of a row as the tenant that owns it."""
    return row_releasable(SimpleNamespace(**{**row, "tenant_id": str(row["tenant_id"])}), tenant, "download")


async def _request(
    session: AsyncSession,
    tenant: str,
    file_id: str,
    key: str,
    *,
    overwrite: bool,
    backup_tenant: str | None = None,
    backup_file: str | None = None,
) -> str:
    """An approved restore of `NEW` for this file, from a backup the destination holds."""
    await session.execute(AS_PROVISIONING)
    backup_id = (
        await session.execute(
            text(
                "insert into public.file_backups (tenant_id, file_id, source_key, backup_key, "
                " destination, size_bytes, source_digest, backup_digest, status) values "
                "(cast(:t as uuid), cast(:f as uuid), :k, :k, 'backups', :size, :d, :d, 'verified') "
                "on conflict (file_id, destination) do update set backup_digest = excluded.backup_digest "
                "returning id::text"
            ),
            {
                "t": backup_tenant or tenant,
                "f": backup_file or file_id,
                "k": key,
                "size": len(NEW),
                "d": NEW_DIGEST,
            },
        )  # fmt: skip
    ).scalar_one()
    await session.commit()
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    request_id = (
        await session.execute(
            text(
                "insert into public.restore_requests (tenant_id, file_id, backup_id, reason, "
                " overwrite, requested_by) values (cast(:t as uuid), cast(:f as uuid), "
                " cast(:b as uuid), 'the file was damaged', :o, 'user-1') returning id::text"
            ),
            {"t": tenant, "f": file_id, "b": backup_id, "o": overwrite},
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


async def _run(engine, source: MemStore, target: MemStore):
    restored: list[tuple[str, str, datetime]] = []
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        counts = await restore_approved(s, source, target, restored=restored)
    return counts, restored


async def _row(engine, tenant: str, file_id: str):
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_TENANT, {"tenant_id": tenant})
        return (
            (
                await s.execute(
                    text("select * from public.files where id = cast(:f as uuid)"), {"f": file_id}
                )
            )
            .mappings()
            .one()
        )


async def _request_row(engine, tenant: str, request_id: str):
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_TENANT, {"tenant_id": tenant})
        return (
            (
                await s.execute(
                    text(
                        "select status, error, restored_file_id::text as restored from "
                        "public.restore_requests where id = cast(:i as uuid)"
                    ),
                    {"i": request_id},
                )
            )
            .mappings()
            .one()
        )


async def _audit(engine, tenant: str, action: str) -> list[dict]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_TENANT, {"tenant_id": tenant})
        rows = (
            await s.execute(
                text(
                    "select details::text from public.audit_events "
                    "where tenant_id = cast(:t as uuid) and action = :a"
                ),
                {"t": tenant, "a": action},
            )
        ).all()
    return [json.loads(r[0]) for r in rows]


async def _settle(engine, file_id: str) -> None:
    """Close a request a test ran by hand (`run_one` without the claim), so the next test's
    pass does not pick it up: the database is shared by every test in this module."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_PROVISIONING)
        await s.execute(
            text(
                "update public.restore_requests set status = 'completed', finished_at = now() "
                "where file_id = cast(:f as uuid) and status = 'approved'"
            ),
            {"f": file_id},
        )
        await s.commit()


def _stores(old_key: str) -> tuple[MemStore, MemStore]:
    source, target = MemStore(), MemStore()
    source.objects[old_key] = NEW  # the backup copy is keyed as the source was
    target.objects[old_key] = OLD  # what is live
    return source, target


# -- the replacement -----------------------------------------------------------


async def test_a_clean_file_is_replaced_by_a_new_object_and_starts_over(
    engine, session, queue
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    request_id = await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)

    (done, failed), restored = await _run(engine, source, target)

    assert (done, failed) == (1, 0)
    row = await _row(engine, tenant, file_id)
    assert row["storage_key"] != old_key, "the row must name a new object"
    assert row["storage_key"].startswith(f"tenants/{tenant}/documents/{file_id}/final/")
    assert is_final_key(row["storage_key"]), "the one shape the scanner reads and the rule releases"
    ObjectReference(tenant, file_id, row["storage_key"])  # the scanner will read it
    assert target.objects[row["storage_key"]] == NEW
    assert target.objects[old_key] == OLD, "the old object is neither overwritten nor deleted"
    assert target.puts == [row["storage_key"]] and target.deletes == []

    # Not the old verdict, and none of the evidence about the old bytes.
    assert (row["status"], row["scan_status"]) == ("ready", "pending")
    assert row["scan_note"] is None and row["scan_failure"] is None
    assert row["scan_attempts"] == 0 and row["scan_attempted_at"] is None
    assert row["scan_object_etag"] is None
    assert row["checksum_sha256"] == NEW_DIGEST and row["size_bytes"] == len(NEW)
    assert row["checksum_verified_at"] is not None, "this worker hashed, wrote and read them back"
    assert target.asked_digest[row["storage_key"]] == NEW_DIGEST, "the provider was asked to check"
    assert row["indexed_at"] is None and row["index_note"] is None
    assert (row["backup_status"], row["backed_up_at"], row["archived_at"]) == ("none", None, None)
    # What is not about the bytes is untouched.
    assert row["name"] == NAME and row["created_at"] < datetime.now(UTC) - timedelta(days=300)

    request = await _request_row(engine, tenant, request_id)
    assert request["status"] == "completed" and request["restored"] == file_id
    assert [r[1] for r in restored] == [file_id]


async def test_every_column_of_files_is_either_reset_or_declared_not_about_the_bytes(
    session,
) -> None:
    columns = {
        r[0]
        for r in (
            await session.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'files'"
                )
            )
        ).all()
    }
    assert columns == RESET_BY_REPLACEMENT | NOT_ABOUT_THE_BYTES, (
        "a column of `files` is not classed: decide whether it is evidence about the bytes, and if "
        f"it is, reset it in `_REPLACE_FILE`: {columns ^ (RESET_BY_REPLACEMENT | NOT_ABOUT_THE_BYTES)}"
    )
    sql = str(storage_restore._REPLACE_FILE)
    for column in RESET_BY_REPLACEMENT:
        assert f"{column} = " in sql, f"`{column}` is evidence about the bytes but is not reset"


async def test_an_old_signed_url_reads_the_old_object_and_never_the_replacement(
    engine, session, queue
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    source, target = _stores(old_key)
    url_issued_before = target.presign_download(old_key, NAME, 300)
    await _request(session, tenant, file_id, old_key, overwrite=True)

    await _run(engine, source, target)

    assert target.fetch(url_issued_before) == OLD
    assert target.fetch(url_issued_before) != NEW
    new_key = (await _row(engine, tenant, file_id))["storage_key"]
    assert new_key not in url_issued_before
    assert target.fetch(target.presign_download(new_key, NAME, 300)) == NEW


async def test_the_replacement_cannot_be_released_before_a_new_clean_verdict(
    engine, session, queue
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    source, target = _stores(old_key)
    before = await _row(engine, tenant, file_id)
    assert _releasable(before, tenant), "the old file was released: the replacement must not be"
    await _request(session, tenant, file_id, old_key, overwrite=True)
    await _run(engine, source, target)

    row = await _row(engine, tenant, file_id)
    assert not _releasable(row, tenant)
    assert row["scan_object_etag"] is None, "the old verdict's identity did not carry over"
    assert row["storage_key"] != before["storage_key"]
    # The row as it is now, with a verdict written by something other than the scanner, still
    # releases nothing: a clean needs the stamp the scanner's own transition writes with it.
    assert not releasable(
        status="ready",
        scan_status="clean",
        tenant_id=tenant,
        row_tenant_id=str(row["tenant_id"]),
        storage_key=row["storage_key"],
        scan_object_etag=None,
    )
    reader = MemStore()
    reader.objects = target.objects
    reads: list[str] = []
    original_get = reader.get
    reader.get = lambda key: reads.append(key) or original_get(key)  # type: ignore[method-assign]
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    assert (
        await read_releasable(
            session, reader, tenant, file_id, actor_id="user-1", consumer="indexing"
        )
        is None
    )
    assert reads == [], "no byte of the replacement may be read before it is clean"
    await session.rollback()


@pytest.mark.parametrize("status", ["archived", "deleted", "purged"])
async def test_a_restore_over_a_lifecycle_state_replaces_and_starts_over(
    engine, session, queue, status
) -> None:
    """Restore exists for these states: the replacement is `ready` and `pending` on a new final
    key, whatever the old row said."""
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant, status=status, scan_status="clean")
    await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)

    (done, _), _ = await _run(engine, source, target)

    assert done == 1
    row = await _row(engine, tenant, file_id)
    assert (row["status"], row["scan_status"]) == ("ready", "pending")
    assert row["storage_key"] != old_key and row["indexed_at"] is None
    assert is_final_key(row["storage_key"])


# -- what is refused, and that nothing is written for it -----------------------


@pytest.mark.parametrize(
    ("status", "scan", "ago", "code"),
    [
        ("quarantined", "infected", 120, "condemned"),
        ("ready", "infected", 120, "condemned"),
        ("ready", "pending", None, "scan_unresolved"),
        ("ready", "pending", 120, "scan_unresolved"),
        ("ready", "skipped", 120, "scan_unresolved"),
        ("purged", "pending", 24 * 60, "scan_unresolved"),
        ("deleted", "pending", None, "scan_unresolved"),
        ("archived", "pending", 24 * 60, "scan_unresolved"),
        ("ready", "clean", 1, "scan_recent"),
        ("purged", "clean", 1, "scan_recent"),
        ("pending", "clean", 120, "not_replaceable"),
    ],
)
async def test_a_refused_replacement_writes_nothing_and_says_why_in_a_closed_code(
    engine, session, queue, status, scan, ago, code
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(
        session, tenant, status=status, scan_status=scan, attempted_minutes_ago=ago
    )
    request_id = await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    before = await _row(engine, tenant, file_id)

    (done, failed), restored = await _run(engine, source, target)

    assert (done, failed) == (0, 1) and restored == []
    assert target.puts == [] and target.deletes == [], "nothing may reach the bucket for a refusal"
    assert target.objects == {old_key: OLD}
    assert dict(await _row(engine, tenant, file_id)) == dict(before), "the row is exactly as it was"
    request = await _request_row(engine, tenant, request_id)
    assert request["status"] == "failed" and request["restored"] is None
    assert request["error"] == storage_restore.REFUSALS[code]
    failed_events = await _audit(engine, tenant, "storage.restore.failed")
    assert failed_events[-1]["refusal"] == code
    assert set(failed_events[-1]) == {"overwrite", "verified", "refusal"}
    assert queue.jobs == [], "a refused restore asks for no scan"


async def test_an_infected_file_is_restored_only_as_a_new_object_that_is_scanned(
    engine, session, queue
) -> None:
    """The explicit path: the quarantined row is left exactly as it is, and the bytes come back
    as a different file that nothing may release until it has its own verdict."""
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant, status="quarantined", scan_status="infected")
    await _request(session, tenant, file_id, old_key, overwrite=False)
    source, target = _stores(old_key)
    before = await _row(engine, tenant, file_id)

    (done, _), restored = await _run(engine, source, target)

    assert done == 1
    assert dict(await _row(engine, tenant, file_id)) == dict(before), (
        "the condemned row is untouched"
    )
    assert target.objects[old_key] == OLD
    (_, new_id, created) = restored[0]
    assert new_id != file_id
    fresh = await _row(engine, tenant, new_id)
    assert (fresh["status"], fresh["scan_status"]) == ("ready", "pending")
    assert fresh["scan_attempts"] == 0 and fresh["scan_object_etag"] is None
    assert fresh["checksum_verified_at"] is not None and fresh["indexed_at"] is None
    assert fresh["storage_key"] != old_key and target.objects[fresh["storage_key"]] == NEW
    assert is_final_key(fresh["storage_key"]), "a new copy is on the same shape of key"
    assert not _releasable(fresh, tenant)


# -- asking for the scan -------------------------------------------------------


async def test_a_replacement_of_a_pre_watermark_file_still_gets_its_scan_requested(
    engine, session, queue
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant, created_days_ago=400)
    await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    _, restored = await _run(engine, source, target)

    await restore_scan.request_scans_for_restored({}, restored)

    assert len(queue.jobs) == 1
    job = queue.jobs[0]
    assert job["task"] == "file.scan" and job["tenant_id"] == tenant
    assert job["payload"] == {"file_id": file_id} and job["key"] == f"scan:{file_id}"
    assert job["delay"] <= 2.0, "an old row's read gate is long open; no deferral is owed"
    created = (await _row(engine, tenant, file_id))["created_at"]
    assert created < datetime.now(UTC) - timedelta(days=300), "it is older than any watermark"


async def test_a_new_copy_is_asked_for_after_its_read_gate_opens(engine, session, queue) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    await _request(session, tenant, file_id, old_key, overwrite=False)
    source, target = _stores(old_key)
    _, restored = await _run(engine, source, target)

    await restore_scan.request_scans_for_restored({}, restored)

    assert [j["payload"]["file_id"] for j in queue.jobs] == [restored[0][1]]
    assert queue.jobs[0]["delay"] >= restore_scan._window_seconds() - 60


async def test_a_lost_enqueue_leaves_the_file_pending_and_the_reconciliation_asks_again(
    engine, session, monkeypatch
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant, created_days_ago=400)
    request_id = await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    broken = Queue(fail=True)
    monkeypatch.setattr(restore_scan, "queue_for", lambda _url: broken)
    _, restored = await _run(engine, source, target)

    asked = await restore_scan.request_scans_for_restored({}, restored)

    assert [a.state for a in asked] == ["failed"]
    row = await _row(engine, tenant, file_id)
    assert (row["status"], row["scan_status"]) == ("ready", "pending"), "safe: still withheld"
    assert not _releasable(row, tenant)

    # The scan sweep cannot recover it (created before any watermark); the restore's own
    # reconciliation can, once it is owed: not before the grace has passed.
    live = Queue()
    monkeypatch.setattr(restore_scan, "queue_for", lambda _url: live)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await restore_scan.reconcile_restored_scans({}, s)
    assert _asked(live, tenant) == [], "not owed yet: the grace has not passed"
    await _age_request(engine, tenant, request_id, minutes=15)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await restore_scan.reconcile_restored_scans({}, s)
    assert _asked(live, tenant) == [file_id]


def _asked(queue: Queue, tenant: str) -> list[str]:
    """The files of this tenant a queue was asked to scan. The database is shared by the tests in
    this module, so a reconciliation pass also sees the others' restored files; never count."""
    return [j["payload"]["file_id"] for j in queue.jobs if j["tenant_id"] == tenant]


async def _age_request(engine, tenant: str, request_id: str, *, minutes: int) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_TENANT, {"tenant_id": tenant})
        await s.execute(
            text(
                "update public.restore_requests set finished_at = now() - make_interval(mins => :m) "
                "where id = cast(:i as uuid)"
            ),
            {"m": minutes, "i": request_id},
        )
        await s.commit()


async def test_the_reconciliation_leaves_alone_a_file_that_has_a_verdict_or_is_not_recent(
    engine, session, queue
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    request_id = await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    await _run(engine, source, target)
    await _age_request(engine, tenant, request_id, minutes=15)

    # A verdict arrives (the scanner's own write, simulated): nothing is owed any more.
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_TENANT, {"tenant_id": tenant})
        await s.execute(
            text("update public.files set scan_status = 'clean' where id = cast(:f as uuid)"),
            {"f": file_id},
        )
        await s.commit()
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await restore_scan.reconcile_restored_scans({}, s)
    assert _asked(queue, tenant) == []

    # And a restore older than the lookback is not chased for ever.
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_TENANT, {"tenant_id": tenant})
        await s.execute(
            text("update public.files set scan_status = 'pending' where id = cast(:f as uuid)"),
            {"f": file_id},
        )
        await s.commit()
    await _age_request(
        engine, tenant, request_id, minutes=(restore_scan.LOOKBACK_DAYS + 1) * 24 * 60
    )
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await restore_scan.reconcile_restored_scans({}, s)
    assert _asked(queue, tenant) == []


async def test_run_restores_asks_for_the_scan_only_after_the_rows_are_committed(
    engine, session, monkeypatch
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    seen: dict[str, object] = {}

    class Watching(Queue):
        async def enqueue(self, task, **kwargs):
            if kwargs.get("tenant_id") == tenant:
                seen["row"] = dict(await _row(engine, tenant, file_id))
            return await super().enqueue(task, **kwargs)

    watching = Watching()
    monkeypatch.setattr(restore_scan, "queue_for", lambda _url: watching)
    monkeypatch.setattr(storage_restore.settings, "database_url", DATABASE_URL, raising=False)
    monkeypatch.setattr(storage_restore.backup_settings, "storage_bucket", "b", raising=False)
    monkeypatch.setattr(storage_restore.backup_settings, "storage_access_key", "k", raising=False)
    monkeypatch.setattr(storage_restore, "destination_from", lambda _c: object())
    monkeypatch.setattr(storage_restore, "S3ObjectStore", lambda _d: source)
    monkeypatch.setattr(storage_restore, "_primary", lambda: target)
    monkeypatch.setattr(storage_restore, "_engine", lambda: create_async_engine(DATABASE_URL))

    result = await storage_restore.run_restores({})

    assert result["status"] == "ok" and result["completed"] >= 1
    assert _asked(watching, tenant) == [file_id]
    committed = seen["row"]
    assert committed["scan_status"] == "pending" and committed["storage_key"] != old_key, (
        "the job must find the replacement already committed"
    )


async def test_a_follow_up_that_cannot_run_never_fails_the_restore_that_completed(
    engine, session, queue, monkeypatch
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)

    async def explode(_ctx, _session):
        raise ConnectionError("redis is unreachable")

    monkeypatch.setattr(storage_restore, "reconcile_restored_scans", explode)
    monkeypatch.setattr(storage_restore.settings, "database_url", DATABASE_URL, raising=False)
    monkeypatch.setattr(storage_restore.backup_settings, "storage_bucket", "b", raising=False)
    monkeypatch.setattr(storage_restore.backup_settings, "storage_access_key", "k", raising=False)
    monkeypatch.setattr(storage_restore, "destination_from", lambda _c: object())
    monkeypatch.setattr(storage_restore, "S3ObjectStore", lambda _d: source)
    monkeypatch.setattr(storage_restore, "_primary", lambda: target)
    monkeypatch.setattr(storage_restore, "_engine", lambda: create_async_engine(DATABASE_URL))

    result = await storage_restore.run_restores({})

    assert result["status"] == "ok" and result["completed"] >= 1
    row = await _row(engine, tenant, file_id)
    assert (row["status"], row["scan_status"]) == ("ready", "pending"), "withheld, and still owed"
    assert row["storage_key"] != old_key


# -- failures ------------------------------------------------------------------


async def test_a_failed_upload_changes_nothing(engine, session, queue) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    request_id = await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    target.fail_put = True
    before = await _row(engine, tenant, file_id)

    (done, failed), restored = await _run(engine, source, target)

    assert (done, failed) == (0, 1) and restored == []
    assert dict(await _row(engine, tenant, file_id)) == dict(before)
    assert target.objects == {old_key: OLD}
    assert (await _request_row(engine, tenant, request_id))["status"] == "failed"
    assert queue.jobs == []


async def test_a_failed_switch_removes_the_new_object_and_leaves_the_row_whole(
    engine, session, queue, monkeypatch
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    request_id = await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    before = await _row(engine, tenant, file_id)
    monkeypatch.setattr(
        storage_restore, "_REPLACE_FILE", text("update public.files set no_such_column = 1")
    )

    (done, failed), restored = await _run(engine, source, target)

    assert (done, failed) == (0, 1) and restored == []
    assert dict(await _row(engine, tenant, file_id)) == dict(before), "the transaction rolled back"
    assert target.objects == {old_key: OLD}, "no object is left at a key nothing points to"
    assert len(target.puts) == 1 and target.deletes == target.puts
    assert (await _request_row(engine, tenant, request_id))["status"] == "failed"


async def test_a_row_that_moved_between_the_read_and_the_write_is_not_switched(
    engine, session, queue, monkeypatch
) -> None:
    """The statement repeats the facts the decision was made on. If the row is not as it was
    read, it updates nothing and the restore fails rather than pointing a changed row at an
    object chosen for another."""
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    real = storage_restore._REPLACE_FILE
    monkeypatch.setattr(
        storage_restore,
        "_REPLACE_FILE",
        text(str(real).replace("storage_key = :old_key", "storage_key = :old_key || 'moved'")),
    )

    (done, failed), _ = await _run(engine, source, target)

    assert (done, failed) == (0, 1)
    assert target.deletes == target.puts and target.objects == {old_key: OLD}
    assert (await _row(engine, tenant, file_id))["storage_key"] == old_key


async def test_restoring_twice_makes_two_distinct_objects_and_retains_both_old_ones(
    engine, session, queue
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    source, target = _stores(old_key)
    await _request(session, tenant, file_id, old_key, overwrite=True)
    await _run(engine, source, target)
    first_key = (await _row(engine, tenant, file_id))["storage_key"]

    # While the replacement awaits its verdict, a second replacement is refused.
    await _request(session, tenant, file_id, old_key, overwrite=True)
    (done, failed), _ = await _run(engine, source, target)
    assert (done, failed) == (0, 1)
    assert (await _row(engine, tenant, file_id))["storage_key"] == first_key

    # Once it has a verdict and its attempt is long past, a second replacement is a third key.
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_TENANT, {"tenant_id": tenant})
        await s.execute(
            text("update public.files set scan_status = 'clean', "
                 "scan_attempted_at = now() - interval '2 hours' where id = cast(:f as uuid)"),
            {"f": file_id},
        )  # fmt: skip
        await s.commit()
    await _request(session, tenant, file_id, old_key, overwrite=True)
    (done, _), _ = await _run(engine, source, target)
    assert done == 1
    second_key = (await _row(engine, tenant, file_id))["storage_key"]
    assert len({old_key, first_key, second_key}) == 3
    assert {old_key, first_key, second_key} <= set(target.objects), "nothing was deleted"


async def test_two_workers_cannot_run_one_request_twice(engine, session, queue) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)

    first, second = await asyncio.gather(_run(engine, source, target), _run(engine, source, target))

    assert first[0][0] + second[0][0] == 1, "exactly one worker claims the request"
    assert len(target.puts) == 1


async def test_an_object_that_does_not_read_back_is_removed_and_the_row_is_untouched(
    engine, session, queue
) -> None:
    """The provider answers with other bytes than were written. Nothing may point at it."""
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    request_id = await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    target.corrupt_reads = OLD
    before = await _row(engine, tenant, file_id)

    (done, failed), restored = await _run(engine, source, target)

    assert (done, failed) == (0, 1) and restored == []
    assert dict(await _row(engine, tenant, file_id)) == dict(before)
    assert target.objects == {old_key: OLD} and target.deletes == target.puts
    request = await _request_row(engine, tenant, request_id)
    assert request["status"] == "failed" and request["error"] == storage_restore.UNVERIFIED
    assert queue.jobs == []


async def test_a_new_copy_whose_object_does_not_read_back_creates_no_row(
    engine, session, queue
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    await _request(session, tenant, file_id, old_key, overwrite=False)
    source, target = _stores(old_key)
    target.corrupt_reads = OLD

    (done, failed), restored = await _run(engine, source, target)

    assert (done, failed) == (0, 1) and restored == []
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_TENANT, {"tenant_id": tenant})
        count = (
            await s.execute(
                text("select count(*) from public.files where tenant_id = cast(:t as uuid)"),
                {"t": tenant},
            )
        ).scalar_one()
    assert count == 1, "only the original row exists"
    assert target.objects == {old_key: OLD}


async def test_a_backup_that_is_not_the_recorded_digest_is_never_written(
    engine, session, queue
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    request_id = await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    source.objects[old_key] = b"a backup copy that was tampered with"

    (done, failed), _ = await _run(engine, source, target)

    assert (done, failed) == (0, 1) and target.puts == []
    assert "digest" in (await _request_row(engine, tenant, request_id))["error"]


# -- tenants -------------------------------------------------------------------


async def test_a_request_naming_another_tenants_file_cannot_replace_it(
    engine, session, queue
) -> None:
    owner = await _tenant(session)
    other = await _tenant(session)
    file_id, old_key = await _file(session, owner)
    # The other tenant's request names the owner's file, with a backup of its own.
    request_id = await _request(session, other, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    before = await _row(engine, owner, file_id)

    (done, failed), restored = await _run(engine, source, target)

    assert (done, failed) == (0, 1) and restored == []
    assert dict(await _row(engine, owner, file_id)) == dict(before)
    assert target.puts == [] and target.objects == {old_key: OLD}
    assert (await _request_row(engine, other, request_id))["status"] == "failed"


async def test_a_request_cannot_borrow_another_tenants_backup(engine, session, queue) -> None:
    owner = await _tenant(session)
    thief = await _tenant(session)
    owner_file, owner_key = await _file(session, owner)
    thief_file, thief_key = await _file(session, thief)
    # The thief's request is for the thief's own file, but its backup row is the owner's.
    request_id = await _request(
        session, thief, thief_file, owner_key, overwrite=True,
        backup_tenant=owner, backup_file=owner_file,
    )  # fmt: skip
    source, target = _stores(owner_key)
    target.objects[thief_key] = OLD
    before = await _row(engine, thief, thief_file)

    (done, failed), _ = await _run(engine, source, target)

    assert (done, failed) == (0, 0), "the request is never selected: the backup is not its own"
    assert dict(await _row(engine, thief, thief_file)) == dict(before)
    assert target.puts == []
    assert (await _request_row(engine, thief, request_id))["status"] == "approved"


# -- racing the scanner --------------------------------------------------------


async def test_readers_see_the_old_state_whole_or_the_new_state_whole_never_a_mixture(
    engine, session, queue
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    seen: set[tuple[bool, str, str]] = set()
    stop = asyncio.Event()

    async def read() -> None:
        while not stop.is_set():
            row = await _row(engine, tenant, file_id)
            seen.add((row["storage_key"] == old_key, row["status"], row["scan_status"]))
            await asyncio.sleep(0)

    reader = asyncio.create_task(read())
    await _run(engine, source, target)
    await asyncio.sleep(0.2)
    stop.set()
    await reader

    assert seen <= {(True, "ready", "clean"), (False, "ready", "pending")}, seen
    assert (False, "ready", "pending") in seen


async def test_a_verdict_that_wins_the_lock_first_makes_the_restore_refuse(
    engine, session, queue
) -> None:
    """The scanner's `commit_infected` (unedited) and the restore take the same row lock. When
    the verdict is first, the restore reads a condemned file and refuses; nothing is written."""
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant, attempted_minutes_ago=120)
    await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        result = await commit_infected(s, tenant_id=tenant, file_id=file_id)
    assert result.kind is TransitionKind.APPLIED

    (done, failed), _ = await _run(engine, source, target)

    assert (done, failed) == (0, 1) and target.puts == []
    row = await _row(engine, tenant, file_id)
    assert (row["status"], row["scan_status"], row["storage_key"]) == (
        "quarantined",
        "infected",
        old_key,
    )


async def test_a_verdict_that_waits_for_the_restore_lands_on_the_replacement_as_quarantine(
    engine, session, queue
) -> None:
    """The other order, with a real wait: the restore holds the row lock, `commit_infected`
    blocks on it, and when the restore commits the file ends quarantined with no chunks. The
    safe direction: an infected verdict is never lost to a replacement."""
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant, attempted_minutes_ago=120)
    await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    row = (await session.execute(AS_PROVISIONING)) and (
        await session.execute(
            text(
                "select r.id::text as id, r.tenant_id::text as tenant_id, r.file_id::text as file_id, "
                " r.overwrite, b.backup_key, b.backup_digest, b.size_bytes "
                "from public.restore_requests r join public.file_backups b on b.id = r.backup_id "
                "where r.file_id = cast(:f as uuid)"
            ),
            {"f": file_id},
        )
    ).first()
    await session.rollback()

    holder = async_sessionmaker(engine, expire_on_commit=False)()
    try:
        await holder.execute(AS_PROVISIONING)
        ran = await storage_restore.run_one(holder, source, target, row)
        assert ran.outcome == "completed", ran  # uncommitted: the lock on the row is held

        async def verdict():
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                return await commit_infected(s, tenant_id=tenant, file_id=file_id)

        verdicting = asyncio.create_task(verdict())
        await asyncio.sleep(1.0)
        assert not verdicting.done(), "the verdict must wait for the lock the restore holds"
        await holder.commit()
    finally:
        await holder.close()
    assert (await asyncio.wait_for(verdicting, 10)).kind is TransitionKind.APPLIED
    await _settle(engine, file_id)

    final = await _row(engine, tenant, file_id)
    assert (final["status"], final["scan_status"]) == ("quarantined", "infected")


# -- the outcome of a COMMIT that raised ---------------------------------------


#
# The invariant: an object that has become the live one is never deleted because the caller
# could not tell whether COMMIT succeeded. A = definitely not committed (may delete),
# B = definitely committed (never deletes), C = ambiguous (reads the database; deletes only on
# proof that nothing committed).


async def _run_with_failing_commit(engine, source, target, *, lands: bool, monkeypatch):
    """Run the sweep with the request's final COMMIT raising `ConnectionError`.

    `lands=True`: the server made the transaction durable and the reply was lost.
    `lands=False`: the server never committed it.
    """
    restored: list[tuple[str, str, datetime]] = []
    state = {"armed": False, "fired": False}
    real_record = storage_restore._record

    async def record(session, *args, **kwargs):
        await real_record(session, *args, **kwargs)
        state["armed"] = True

    monkeypatch.setattr(storage_restore, "_record", record)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        real_commit = s.commit

        async def commit():
            if state["armed"] and not state["fired"]:
                state["fired"] = True
                if lands:
                    await real_commit()
                else:
                    await s.rollback()
                raise ConnectionError("the connection was reset during COMMIT")
            await real_commit()

        s.commit = commit  # type: ignore[method-assign]
        counts = await restore_approved(s, source, target, restored=restored)
    assert state["fired"], "the commit under test was never reached"
    return counts, restored


@pytest.mark.parametrize("overwrite", [True, False])
async def test_commit_ambiguous_but_landed_keeps_the_live_object(
    engine, session, queue, monkeypatch, overwrite
) -> None:
    """C, committed: the reply was lost, the row names the replacement. It must survive."""
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    request_id = await _request(session, tenant, file_id, old_key, overwrite=overwrite)
    source, target = _stores(old_key)

    (done, failed), restored = await _run_with_failing_commit(
        engine, source, target, lands=True, monkeypatch=monkeypatch
    )

    assert target.deletes == [], "an object the database names must never be deleted"
    request = await _request_row(engine, tenant, request_id)
    assert request["status"] == "completed" and (done, failed) == (1, 0)
    live = request["restored"]
    assert [r[1] for r in restored] == [live], "and it is asked for a scan"
    new_key = (await _row(engine, tenant, live))["storage_key"]
    assert new_key in target.objects and target.objects[new_key] == NEW
    if overwrite:
        assert new_key != old_key and target.objects[old_key] == OLD


async def test_commit_ambiguous_and_not_landed_removes_the_orphan_after_proof(
    engine, session, queue, monkeypatch
) -> None:
    """C, not committed: proven by the request still `restoring` and no row naming the key."""
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    request_id = await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    before = await _row(engine, tenant, file_id)

    (done, failed), restored = await _run_with_failing_commit(
        engine, source, target, lands=False, monkeypatch=monkeypatch
    )

    assert (done, failed) == (0, 1) and restored == []
    assert dict(await _row(engine, tenant, file_id)) == dict(before)
    assert target.objects == {old_key: OLD} and len(target.deletes) == 1
    assert (await _request_row(engine, tenant, request_id))["status"] == "failed"


@pytest.mark.parametrize("lands", [True, False])
async def test_commit_ambiguous_and_unprovable_never_deletes(
    engine, session, queue, monkeypatch, lands
) -> None:
    """C, unknown: the database cannot be read afterwards. Nothing is deleted either way."""
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    # The verification reads fail, as a database that is still down would make them.
    monkeypatch.setattr(storage_restore, "_REQUEST_STATE", text("select * from no_such_table"))

    (done, failed), restored = await _run_with_failing_commit(
        engine, source, target, lands=lands, monkeypatch=monkeypatch
    )

    assert target.deletes == [], "unknown is not proof: the replacement may be live"
    assert restored == [] and (done, failed) == (0, 1)
    row = await _row(engine, tenant, file_id)
    if lands:
        assert row["storage_key"] in target.objects and row["storage_key"] != old_key
    else:
        assert row["storage_key"] == old_key
        assert len([k for k in target.objects if k != old_key]) == 1, "the orphan is left"


async def test_a_failure_after_the_commit_never_deletes_the_live_object(
    engine, session, queue, monkeypatch
) -> None:
    """B: the commit returned. A queue that is down, or raises something unexpected, changes
    nothing about the object, and the file stays pending for the reconciliation."""
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)

    (done, failed), restored = await _run(engine, source, target)
    assert (done, failed) == (1, 0)

    def explode(_url):
        raise RuntimeError("redis exploded")

    monkeypatch.setattr(restore_scan, "queue_for", explode)
    asked = await restore_scan.request_scans_for_restored({}, restored)

    assert [a.state for a in asked] == ["failed"]
    row = await _row(engine, tenant, file_id)
    assert row["storage_key"] in target.objects and row["storage_key"] != old_key
    assert row["scan_status"] == "pending" and row["status"] == "ready"
    assert target.deletes == []


def test_an_object_is_deleted_only_where_nothing_was_committed() -> None:
    """In text: `restore_approved` deletes once, and only in the branch that has proof."""
    import inspect

    body = inspect.getsource(restore_approved)
    assert body.count("_discard(") == 1 and ".delete(" not in body
    before = body[: body.index("_discard(")]
    assert 'settled == "committed"' in before and 'settled == "unknown"' in before
    assert before.rindex("else:") > before.rindex('settled == "unknown"')


# -- the reconciliation is idempotent and generation-proof ---------------------


async def test_two_completed_restores_of_one_file_ask_for_one_scan(engine, session, queue) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    source, target = _stores(old_key)
    first_request = await _request(session, tenant, file_id, old_key, overwrite=True)
    await _run(engine, source, target)
    # The second replacement needs a clean file again.
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_TENANT, {"tenant_id": tenant})
        await s.execute(
            text(
                "update public.files set scan_status = 'clean', "
                "scan_attempted_at = now() - interval '3 hours' where id = cast(:f as uuid)"
            ),
            {"f": file_id},
        )
        await s.commit()
    second_request = await _request(session, tenant, file_id, old_key, overwrite=True)
    await _run(engine, source, target)
    await _age_request(engine, tenant, first_request, minutes=30)
    await _age_request(engine, tenant, second_request, minutes=15)

    for _ in range(2):  # a duplicate pass is the same ask
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            await restore_scan.reconcile_restored_scans({}, s)

    asked = _asked(queue, tenant)
    assert asked == [file_id, file_id], "one request per pass, though two restores completed"
    mine = [j for j in queue.jobs if j["tenant_id"] == tenant]
    assert {j["key"] for j in mine} == {f"scan:{file_id}"}, "one job identity"
    assert all(j["payload"] == {"file_id": file_id} for j in mine), "no object is named"
    # And what the scanner will read is whatever the row names now: the second generation.
    assert (await _row(engine, tenant, file_id))["storage_key"] != old_key


async def test_a_commit_still_in_flight_is_unknown_until_it_ends(
    engine, session, queue, monkeypatch
) -> None:
    """The residual window: the COMMIT raised client-side but the old backend is still finishing
    it. "Not seen committed" is then not proof. The request row lock the transaction holds makes
    the check wait; while it is held the answer is `unknown` (the object is kept), and once the
    transaction has ended without committing it is `not_committed`."""
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    request_id = await _request(session, tenant, file_id, old_key, overwrite=True)
    async with async_sessionmaker(engine, expire_on_commit=False)() as claim:
        await claim.execute(AS_PROVISIONING)
        await claim.execute(
            text(
                "update public.restore_requests set status = 'restoring' where id = cast(:i as uuid)"
            ),
            {"i": request_id},
        )
        await claim.commit()
    monkeypatch.setattr(
        storage_restore, "_LOCK_WAIT", text("select set_config('lock_timeout', '300ms', true)")
    )
    row = type("R", (), {"id": request_id, "tenant_id": tenant})()

    async with async_sessionmaker(engine, expire_on_commit=False)() as in_flight:
        await in_flight.execute(AS_PROVISIONING)
        await in_flight.execute(
            text("select 1 from public.restore_requests where id = cast(:i as uuid) for update"),
            {"i": request_id},
        )
        async with async_sessionmaker(engine, expire_on_commit=False)() as checker:
            held = await storage_restore.commit_outcome(checker, row, "tenants/x/new-key")
        await in_flight.rollback()
    async with async_sessionmaker(engine, expire_on_commit=False)() as checker:
        free = await storage_restore.commit_outcome(checker, row, "tenants/x/new-key")

    assert held == "unknown", "a transaction that may still commit is not proof of anything"
    assert free == "not_committed"
