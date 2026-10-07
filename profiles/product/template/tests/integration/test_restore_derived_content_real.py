# ruff: noqa: ANN001, ANN002, ANN003, ANN201, ANN202, ANN401, E501, S101, E402
"""A restore and what the assistant derived from the old bytes (ADR 0013, layer 5).

The replacement of a file's bytes withdraws every chunk derived from the old ones in the same
transaction, and the indexer's own guards (the file's share lock, and the object it read) keep a
write that was already in flight from attaching old content to the new bytes. These need real
row locks and two connections, so they need a real PostgreSQL; and they need the assistant's
table, so this module is generated only into a product with `ai` as well as `secure_files` and
`storage_governance`.

The shared helpers are `test_restore_replacement_real.py`'s.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from koras_ai import RetrievalScope  # noqa: E402
from koras_api.core import knowledge as knowledge_store  # noqa: E402
from koras_api.core.file_release_gate import read_releasable  # noqa: E402
from koras_worker.scanning import TransitionKind, commit_infected  # noqa: E402
from koras_worker.tasks import storage_restore  # noqa: E402
from restore_support import OLD, MemStore  # noqa: E402
from test_restore_replacement_real import (  # noqa: E402
    AS_PROVISIONING,
    AS_TENANT,
    NAME,
    _file,
    _request,
    _request_row,
    _row,
    _run,
    _settle,
    _stores,
    _tenant,
    engine,
    queue,
    session,
)

assert engine and queue and session  # re-exported fixtures

VECTOR = tuple([0.1] * 1536)


def _scope(tenant: str) -> RetrievalScope:
    return RetrievalScope(tenant_id=tenant, product_code="sample")


async def _plant_chunk(session: AsyncSession, tenant: str, file_id: str) -> None:
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    await session.execute(
        text(
            "insert into public.ai_knowledge_chunks (tenant_id, document_id, resource_type, "
            "resource_id, title, chunk_index, content, embedding) values (cast(:t as uuid), :d, "
            "'file', :r, 'x', 0, 'content of the old bytes', cast(:v as vector))"
        ),
        {"t": tenant, "d": f"file:{file_id}", "r": file_id, "v": knowledge_store._literal(VECTOR)},
    )
    await session.commit()


async def _chunks(engine, tenant: str, file_id: str) -> int:
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_TENANT, {"tenant_id": tenant})
        return (
            await s.execute(
                text(
                    "select count(*) from public.ai_knowledge_chunks "
                    "where tenant_id = cast(:t as uuid) and resource_id = :f"
                ),
                {"t": tenant, "f": file_id},
            )
        ).scalar_one()


async def _embed(texts):
    return [VECTOR for _ in texts]


@pytest.mark.parametrize("status", ["archived", "deleted", "purged"])
async def test_a_restore_over_a_lifecycle_state_replaces_and_withdraws_stale_chunks(
    engine, session, queue, status
) -> None:
    """The S2 trigger fires only for a file that was `ready` and `clean`. A purged or archived
    file's chunks would come back the moment the replacement is cleaned, so the restore removes
    them itself."""
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant, status=status, scan_status="clean")
    await _plant_chunk(session, tenant, file_id)
    await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)

    (done, _), _ = await _run(engine, source, target)

    assert done == 1
    row = await _row(engine, tenant, file_id)
    assert (row["status"], row["scan_status"]) == ("ready", "pending")
    assert row["storage_key"] != old_key and row["indexed_at"] is None
    assert await _chunks(engine, tenant, file_id) == 0


async def test_a_clean_files_chunks_are_withdrawn_with_its_replacement(
    engine, session, queue
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    await _plant_chunk(session, tenant, file_id)
    await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    assert await _chunks(engine, tenant, file_id) == 1

    (done, _), _ = await _run(engine, source, target)

    assert done == 1
    assert await _chunks(engine, tenant, file_id) == 0, "none of the old bytes' content survives"
    row = await _row(engine, tenant, file_id)
    assert row["indexed_at"] is None and row["index_note"] is None


async def test_a_replacement_that_cannot_be_read_by_the_indexer_before_its_verdict(
    engine, session, queue
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    source, target = _stores(old_key)
    await _request(session, tenant, file_id, old_key, overwrite=True)
    await _run(engine, source, target)
    reader = MemStore()
    reader.objects = target.objects
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    assert (
        await read_releasable(
            session, reader, tenant, file_id, actor_id="user-1", consumer="indexing"
        )
        is None
    )
    await session.rollback()
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    with pytest.raises(knowledge_store.FileNotReleasable):
        await knowledge_store.index_file_document(
            session,
            scope=_scope(tenant),
            document=knowledge_store.file_document(
                tenant_id=tenant, file_id=file_id, name=NAME, text_content="alpha"
            ),
            embed=_embed,
            read=knowledge_store.ReadIdentity(storage_key=old_key, etag=None),
        )


async def test_a_failed_switch_removes_the_new_object_and_leaves_the_row_whole(
    engine, session, queue, monkeypatch
) -> None:
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant)
    await _plant_chunk(session, tenant, file_id)
    request_id = await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    before = await _row(engine, tenant, file_id)
    monkeypatch.setattr(
        storage_restore, "_REPLACE_FILE", text("update public.files set no_such_column = 1")
    )

    (done, failed), restored = await _run(engine, source, target)

    assert (done, failed) == (0, 1) and restored == []
    assert dict(await _row(engine, tenant, file_id)) == dict(before), "the transaction rolled back"
    assert await _chunks(engine, tenant, file_id) == 1, "the chunks went with the transaction"
    assert target.objects == {old_key: OLD}, "no object is left at a key nothing points to"
    assert len(target.puts) == 1 and target.deletes == target.puts
    assert (await _request_row(engine, tenant, request_id))["status"] == "failed"


async def test_a_verdict_that_waits_for_the_restore_lands_on_the_replacement_as_quarantine(
    engine, session, queue
) -> None:
    """The other order, with a real wait: the restore holds the row lock, `commit_infected`
    blocks on it, and when the restore commits the file ends quarantined with no chunks. The
    safe direction: an infected verdict is never lost to a replacement."""
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant, attempted_minutes_ago=120)
    await _plant_chunk(session, tenant, file_id)
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
    assert await _chunks(engine, tenant, file_id) == 0


async def test_an_index_write_in_flight_cannot_leave_a_chunk_behind_a_replacement(
    engine, session, queue
) -> None:
    """The indexer holds the file's share lock while it writes (S2). A restore that arrives
    waits for it; when it commits, the chunks are gone and the file is pending."""
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant, indexed=False, attempted_minutes_ago=120)
    await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    etag = (await _row(engine, tenant, file_id))["scan_object_etag"]
    locked, release = asyncio.Event(), asyncio.Event()

    async def slow_embed(texts):
        return [VECTOR for _ in texts]

    async def index() -> int:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            await s.execute(AS_TENANT, {"tenant_id": tenant})
            original_execute = s.execute

            async def hooked(statement, *args, **kwargs):
                result = await original_execute(statement, *args, **kwargs)
                if "for share" in str(statement).lower():
                    locked.set()
                    await release.wait()
                return result

            s.execute = hooked  # type: ignore[method-assign]
            return await knowledge_store.index_file_document(
                s,
                scope=_scope(tenant),
                document=knowledge_store.file_document(
                    tenant_id=tenant, file_id=file_id, name=NAME, text_content="alpha beta gamma"
                ),
                embed=slow_embed,
                read=knowledge_store.ReadIdentity(storage_key=old_key, etag=etag),
            )

    indexing = asyncio.create_task(index())
    await asyncio.wait_for(locked.wait(), 10)
    restoring = asyncio.create_task(_run(engine, source, target))
    await asyncio.sleep(1.0)
    assert not restoring.done(), "the restore must wait for the share lock the indexer holds"
    release.set()
    assert await asyncio.wait_for(indexing, 10) >= 1
    (done, _), _ = await asyncio.wait_for(restoring, 10)

    assert done == 1
    assert await _chunks(engine, tenant, file_id) == 0, "no chunk of the old bytes survives"
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["indexed_at"]) == ("pending", None)


async def test_an_indexer_that_read_the_old_object_cannot_commit_after_a_restore_and_a_new_clean(
    engine, session, queue
) -> None:
    """With the real restore: A was read and is being embedded (no lock held), the restore
    replaces the object and the replacement is cleaned; A's chunks must not be attached to it."""
    tenant = await _tenant(session)
    file_id, old_key = await _file(session, tenant, indexed=False, attempted_minutes_ago=120)
    etag_a = (await _row(engine, tenant, file_id))["scan_object_etag"]
    await _request(session, tenant, file_id, old_key, overwrite=True)
    source, target = _stores(old_key)
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_embed(texts):
        started.set()
        await release.wait()
        return [VECTOR for _ in texts]

    async def index() -> int:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            await s.execute(AS_TENANT, {"tenant_id": tenant})
            return await knowledge_store.index_file_document(
                s,
                scope=_scope(tenant),
                document=knowledge_store.file_document(
                    tenant_id=tenant, file_id=file_id, name=NAME, text_content="alpha beta gamma"
                ),
                embed=slow_embed,
                read=knowledge_store.ReadIdentity(storage_key=old_key, etag=etag_a),
            )

    indexing = asyncio.create_task(index())
    await asyncio.wait_for(started.wait(), 10)
    (done, _), _ = await _run(engine, source, target)
    assert done == 1
    replaced = await _row(engine, tenant, file_id)
    assert replaced["storage_key"] != old_key and replaced["scan_status"] == "pending"
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_TENANT, {"tenant_id": tenant})
        await s.execute(
            text(
                "update public.files set scan_status = 'clean', "
                "scan_object_etag = 'etag-of-the-new-object' where id = cast(:f as uuid)"
            ),
            {"f": file_id},
        )
        await s.commit()
    release.set()

    with pytest.raises(knowledge_store.ObjectChanged):
        await asyncio.wait_for(indexing, 10)
    assert await _chunks(engine, tenant, file_id) == 0
    row = await _row(engine, tenant, file_id)
    assert row["indexed_at"] is None and row["index_note"] is None


#
# The invariant: an object that has become the live one is never deleted because the caller
# could not tell whether COMMIT succeeded. A = definitely not committed (may delete),
# B = definitely committed (never deletes), C = ambiguous (reads the database; deletes only on
# proof that nothing committed).
