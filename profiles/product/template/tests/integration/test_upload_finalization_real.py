# ruff: noqa: ANN001, ANN201, ANN202, ANN401, E501, S101, E402
"""Immutable upload finalization against a real PostgreSQL with row-level security on (ADR 0013).

The unit suite proves the shapes. This proves what only a server can: the compare-and-set swap
under forced RLS as the restricted role, that two finalizations racing on one row leave exactly one
owner and one referenced object, what is left behind when the copy lands and the transaction does
not, that a held file is recorded as a closed word with one audit event, and that the sweep selects
only what it should. The bucket is an in-memory model of the one thing that matters to the argument
-- a client can write a key it was granted and nothing else; the real provider's behaviour is
`test_upload_finalization_provider.py`.

Needs a database, and the role must be the restricted application role. It is generated only into a
product with `secure_files`, where a skip is a failure: the generator-integration workflow runs it
against the round-trip database and fails on any skip.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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
from koras_api.core.upload_window import (
    FINALIZE_DELAY_SECONDS,
    final_key_for,
    incoming_key,
    is_incoming_key,
)
from koras_worker.tasks import finalize as finalize_task
from koras_worker.uploads.finalize import FinalizeKind, UploadFinalizer
from upload_store_support import ClientCannotWrite, MemBucket

AS_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")
AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)
ISSUED = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
#: After the ticket's own life (15 min) and *before* the finalization horizon (19 min).
BETWEEN = ISSUED + timedelta(minutes=17)
AFTER = ISSUED + timedelta(seconds=FINALIZE_DELAY_SECONDS + 60)
A = b"name,amount\nacme,10\nglobex,20\n"
B = b"name,amount\nevil,99\nzzzzzz,00\n"
assert len(A) == len(B)



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


def sessions(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(
    session: AsyncSession,
    bucket: MemBucket,
    body: bytes = A,
    *,
    legacy: bool = False,
    tenant: str | None = None,
    **file: object,
) -> tuple[str, str, str]:
    """A tenant and a ready, pending file whose ticket was signed for an incoming key.

    The object is in the bucket and the ticket's key is granted to the client. `legacy=True`
    seeds a key written before this change (no incoming segment). The row carries the content
    claim the upload was authorized for : the SHA-256 of `body`, unless a test passes
    `checksum_sha256=` (including `None`, a ticket from before the claim was required).
    """
    tenant = tenant or str(uuid.uuid4())
    file_id = str(uuid.uuid4())
    key = (
        f"tenants/{tenant}/documents/{file_id}/a.csv"
        if legacy
        else incoming_key(tenant, "documents", file_id, str(uuid.uuid4()), "a.csv")
    )
    bucket.objects[key] = body
    bucket.grant(key)
    values: dict[str, object] = {
        "created_at": ISSUED,
        "status": "ready",
        "scan_status": "pending",
        "backup_status": "none",
        "checksum_sha256": hashlib.sha256(body).hexdigest(),
    }
    values.update(file)
    await session.execute(AS_PROVISIONING)
    await session.execute(
        text(
            "insert into public.tenants (id, slug, name) values (cast(:t as uuid), :s, 'T') "
            "on conflict (id) do nothing"
        ),
        {"t": tenant, "s": f"fin-{tenant[:8]}"},
    )
    await session.commit()
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    await session.execute(
        text(
            "insert into public.files (id, tenant_id, storage_key, name, size_bytes, "
            "content_type, category, status, uploaded_by, scan_status, backup_status, "
            "checksum_sha256, created_at) values (cast(:f as uuid), cast(:t as uuid), :k, "
            "'a.csv', :size, 'text/csv', 'documents', :status, 'u', :scan_status, :backup_status, "
            ":checksum_sha256, :created_at)"
        ),
        {"f": file_id, "t": tenant, "k": key, "size": len(body), **values},
    )
    await session.commit()
    return tenant, file_id, key


async def _row(engine, tenant: str, file_id: str) -> dict[str, Any]:
    async with sessions(engine)() as reader:
        await reader.execute(AS_TENANT, {"tenant_id": tenant})
        return dict(
            (
                await reader.execute(
                    text("select * from public.files where id = cast(:f as uuid)"), {"f": file_id}
                )
            )
            .mappings()
            .one()
        )


async def _finalize(engine, tenant, file_id, bucket, *, at=AFTER, wrap=None):
    async with sessions(engine)() as opened:
        target = wrap(opened) if wrap else opened
        return await UploadFinalizer(bucket).finalize(
            target, tenant_id=tenant, file_id=file_id, now=at
        )


async def _run(engine, tenant, file_id, bucket, *, at=AFTER, max_attempts=8):
    """One finalize job's worth of work: what `file.finalize` does, minus the queue."""
    async with sessions(engine)() as opened:
        return await finalize_task.finalize_one(
            opened,
            UploadFinalizer(bucket),
            tenant_id=tenant,
            file_id=file_id,
            now=at,
            max_attempts=max_attempts,
        )


async def _events(engine, tenant, file_id, action):
    async with sessions(engine)() as reader:
        await reader.execute(AS_TENANT, {"tenant_id": tenant})
        return (
            (
                await reader.execute(
                    text(
                        "select outcome, details::text as d from public.audit_events "
                        "where target_id = :f and action = :a"
                    ),
                    {"f": file_id, "a": action},
                )
            )
            .mappings()
            .all()
        )


def _final_keys(bucket: MemBucket) -> list[str]:
    return sorted(k for k in bucket.objects if "/final/" in k)


async def test_a_write_landing_during_the_copy_cannot_change_the_object_after_it(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, A)
    bucket.after_copy = lambda: bucket.client_put(incoming, B)  # lands right after the copy
    outcome = await _finalize(engine, tenant, file_id, bucket)
    assert outcome.kind is FinalizeKind.FINALIZED
    assert bucket.objects[outcome.key] == A  # fixed at the copy
    # The late write recreated nothing the row references; it only wrote the incoming key,
    # which the finalizer then removed or which holds B unseen. Either way the row is final.
    assert (await _row(engine, tenant, file_id))["storage_key"] == outcome.key


async def test_finalizing_twice_is_a_no_op_the_second_time(engine, session) -> None:
    bucket = MemBucket()
    tenant, file_id, _ = await _seed(session, bucket)
    first = await _finalize(engine, tenant, file_id, bucket)
    copies = [c for c in bucket.calls if c[0] == "copy"]
    second = await _finalize(engine, tenant, file_id, bucket)
    assert (first.kind, second.kind) == (FinalizeKind.FINALIZED, FinalizeKind.ALREADY_FINAL)
    assert second.key == first.key
    assert [c for c in bucket.calls if c[0] == "copy"] == copies
    assert _final_keys(bucket) == [first.key]


class _FailingSession:
    """Delegates to a real session, failing one named thing."""

    def __init__(
        self, real: AsyncSession, *, on_swap: bool = False, on_commit: str | None = None
    ) -> None:
        self._real = real
        self._on_swap = on_swap
        self._on_commit = on_commit  # "before" (nothing lands) or "after" (it lands, then raises)

    async def execute(self, statement, params=None):
        if self._on_swap and "set storage_key" in str(statement):
            raise RuntimeError("the database refused the swap")
        return await self._real.execute(statement, params)

    async def commit(self):
        if self._on_commit == "before":
            raise RuntimeError("the connection dropped before the commit")
        await self._real.commit()
        if self._on_commit == "after":
            raise RuntimeError("the connection dropped after the commit")

    async def rollback(self):
        await self._real.rollback()


async def test_the_copy_lands_and_the_swap_fails_so_the_row_stays_incoming_and_the_copy_is_removed(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket)
    with pytest.raises(RuntimeError, match="refused the swap"):
        await _finalize(
            engine, tenant, file_id, bucket, wrap=lambda s: _FailingSession(s, on_swap=True)
        )
    row = await _row(engine, tenant, file_id)
    assert row["storage_key"] == incoming and incoming in bucket.objects
    assert _final_keys(bucket) == [], "the attempt removed the object only it had written"
    # The next attempt starts again with a new generation and succeeds.
    again = await _finalize(engine, tenant, file_id, bucket)
    assert again.kind is FinalizeKind.FINALIZED and _final_keys(bucket) == [again.key]


async def test_a_commit_that_raises_after_landing_never_deletes_the_object_the_row_now_names(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, _ = await _seed(session, bucket)
    with pytest.raises(RuntimeError, match="after the commit"):
        await _finalize(
            engine, tenant, file_id, bucket, wrap=lambda s: _FailingSession(s, on_commit="after")
        )
    row = await _row(engine, tenant, file_id)
    assert not is_incoming_key(row["storage_key"])
    assert row["storage_key"] in bucket.objects, (
        "the referenced object must survive an ambiguous commit"
    )


async def test_a_commit_that_raises_before_landing_removes_the_unreferenced_object(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket)
    with pytest.raises(RuntimeError, match="before the commit"):
        await _finalize(
            engine, tenant, file_id, bucket, wrap=lambda s: _FailingSession(s, on_commit="before")
        )
    assert (await _row(engine, tenant, file_id))["storage_key"] == incoming
    assert _final_keys(bucket) == []


class _Gated(_FailingSession):
    """Holds each finalizer after it has read the row until both have, so they truly overlap."""

    barrier: asyncio.Barrier

    async def rollback(self):
        await self._real.rollback()
        if not getattr(self, "_passed", False):
            self._passed = True
            await asyncio.wait_for(self.barrier.wait(), timeout=10)


async def test_two_finalizations_racing_leave_one_owner_and_one_referenced_object(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, _ = await _seed(session, bucket)
    barrier = asyncio.Barrier(2)

    def gate(s):
        wrapped = _Gated(s)
        wrapped.barrier = barrier
        return wrapped

    results = await asyncio.gather(
        _finalize(engine, tenant, file_id, bucket, wrap=gate),
        _finalize(engine, tenant, file_id, bucket, wrap=gate),
    )
    kinds = sorted(r.kind.value for r in results)
    assert kinds == ["finalized", "not_eligible"], kinds
    row = await _row(engine, tenant, file_id)
    # Exactly one final object remains, it is the one the row names, and the loser removed its own.
    assert _final_keys(bucket) == [row["storage_key"]]
    assert len([c for c in bucket.calls if c[0] == "copy"]) == 2


class _Parked(_FailingSession):
    """Holds one finalizer after it has read the row, until the test lets it go."""

    def __init__(self, real, parked: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__(real)
        self._parked, self._release, self._once = parked, release, False

    async def rollback(self):
        await self._real.rollback()
        if not self._once:
            self._once = True
            self._parked.set()
            await asyncio.wait_for(self._release.wait(), timeout=10)


async def test_a_loser_that_finds_its_source_deleted_by_the_winner_reports_nothing_wrong(
    engine, session
) -> None:
    """The real store timing that the barrier race hid: the winner commits and deletes the incoming
    object before the loser looks for it. The file is healthy; recording `object_unreachable` on it
    would be a false failure on a finalized row."""
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket)
    parked, release = asyncio.Event(), asyncio.Event()
    loser = asyncio.create_task(
        _finalize(engine, tenant, file_id, bucket, wrap=lambda s: _Parked(s, parked, release))
    )
    await asyncio.wait_for(parked.wait(), timeout=10)
    winner = await _finalize(
        engine, tenant, file_id, bucket
    )  # finishes, commits, deletes the incoming object
    assert winner.kind is FinalizeKind.FINALIZED and incoming not in bucket.objects
    release.set()
    result = await loser
    assert result.kind is FinalizeKind.ALREADY_FINAL and result.key == winner.key
    row = await _row(engine, tenant, file_id)
    assert row["scan_failure"] is None and row["storage_key"] == winner.key
    assert _final_keys(bucket) == [winner.key]


async def test_a_file_that_is_no_longer_ready_is_not_finalized_and_nothing_is_copied(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, _ = await _seed(session, bucket)
    # The row leaves `ready` before the attempt reads it, so it is not eligible at all.
    async with sessions(engine)() as other:
        await other.execute(AS_TENANT, {"tenant_id": tenant})
        await other.execute(
            text("update public.files set status = 'quarantined' where id = cast(:f as uuid)"),
            {"f": file_id},
        )
        await other.commit()
    outcome = await _finalize(engine, tenant, file_id, bucket)
    assert outcome.kind is FinalizeKind.NOT_ELIGIBLE
    assert _final_keys(bucket) == [] and not [c for c in bucket.calls if c[0] == "copy"]


async def test_a_promoted_object_is_corroborated_by_this_process_not_the_provider(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket)
    outcome = await _finalize(engine, tenant, file_id, bucket)
    assert outcome.kind is FinalizeKind.FINALIZED
    assert (await _row(engine, tenant, file_id))["checksum_verified_at"] is not None
    # The digest came from reading the bytes (twice: incoming, then the final copy), and the
    # provider's own stored checksum was never consulted.
    assert [c for c in bucket.calls if c[0] == "sha256"] == [
        ("sha256", incoming),
        ("sha256", outcome.key),
    ]
    assert not [c for c in bucket.calls if c[0] == "checksum"]


async def test_a_pending_legacy_row_is_not_touched_by_finalization(engine, session) -> None:
    """The historical files are of this kind: pending, old keys. Finalization changes nothing."""
    bucket = MemBucket()
    tenant, file_id, key = await _seed(
        session, bucket, legacy=True, created_at=ISSUED - timedelta(days=30)
    )
    before = await _row(engine, tenant, file_id)
    outcome = await _finalize(engine, tenant, file_id, bucket)
    assert outcome.kind is FinalizeKind.ALREADY_FINAL
    assert await _row(engine, tenant, file_id) == before and bucket.calls == []


async def test_a_row_naming_another_tenants_incoming_key_is_held_before_any_store_call(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, _ = await _seed(session, bucket)
    foreign = incoming_key(str(uuid.uuid4()), "documents", file_id, str(uuid.uuid4()), "a.csv")
    bucket.objects[foreign] = A
    async with sessions(engine)() as other:
        await other.execute(AS_TENANT, {"tenant_id": tenant})
        await other.execute(
            text("update public.files set storage_key = :k where id = cast(:f as uuid)"),
            {"k": foreign, "f": file_id},
        )
        await other.commit()
    outcome = await _finalize(engine, tenant, file_id, bucket)
    assert outcome.kind is FinalizeKind.HELD
    assert bucket.calls == [] and foreign in bucket.objects


async def test_finalization_writes_one_audit_event_with_no_key_or_name(engine, session) -> None:
    """the swap and its audit row commit together; the row names ids and a boolean only."""
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket)
    result = await _finalize(engine, tenant, file_id, bucket)
    assert result.kind is FinalizeKind.FINALIZED
    async with sessions(engine)() as reader:
        await reader.execute(AS_TENANT, {"tenant_id": tenant})
        rows = (
            (
                await reader.execute(
                    text(
                        "select action, outcome, details::text as d from public.audit_events "
                        "where target_id = :f and action = 'storage.upload.finalized'"
                    ),
                    {"f": file_id},
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1 and rows[0]["outcome"] == "ok"
    final = (await _row(engine, tenant, file_id))["storage_key"]
    assert (
        incoming not in rows[0]["d"] and final not in rows[0]["d"] and "a.csv" not in rows[0]["d"]
    )
    # A second, duplicate finalization writes nothing more.
    again = await _finalize(engine, tenant, file_id, bucket)
    assert again.kind is FinalizeKind.ALREADY_FINAL


# --- the job: counted, finalized, recorded --------------------------------------------------


async def test_before_the_horizon_nothing_is_read_counted_or_written(engine, session) -> None:
    bucket = MemBucket()
    tenant, file_id, key = await _seed(session, bucket)
    run = await _run(engine, tenant, file_id, bucket, at=BETWEEN)
    assert run["status"] == "deferred"
    assert run["opens_at"] == (ISSUED + timedelta(seconds=FINALIZE_DELAY_SECONDS)).isoformat()
    assert bucket.calls == []
    row = await _row(engine, tenant, file_id)
    assert (row["storage_key"], row["scan_attempts"], row["scan_status"]) == (key, 0, "pending")


async def test_a_finalized_file_is_on_a_final_key_counted_once_and_still_not_clean(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket)
    run = await _run(engine, tenant, file_id, bucket)
    assert run["status"] == "finalized" and run["attempts"] == 1

    row = await _row(engine, tenant, file_id)
    final = row["storage_key"]
    assert final != incoming and not is_incoming_key(final)
    assert f"/{file_id}/final/" in final
    # Finalization decides nothing about the content: the file is exactly as releasable as it
    # was, which is not at all. A verdict is a later step's, and only ever about this key.
    assert (row["status"], row["scan_status"]) == ("ready", "pending")
    assert row["checksum_verified_at"] is not None and row["scan_failure"] is None
    # The incoming object was removed; nothing a ticket could write is referenced or left.
    assert incoming not in bucket.objects and _final_keys(bucket) == [final]
    assert bucket.objects[final] == A
    # Nothing was opened for reading except to hash it: no URL was ever signed.
    assert {op for op, _ in bucket.calls} <= {"head", "provenance", "sha256", "copy", "delete"}


async def test_repeated_writes_before_finalization_touch_the_incoming_key_only(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, A)
    bucket.client_put(incoming, B)  # the same ticket, reused before expiry
    bucket.client_put(incoming, A)
    bucket.client_put(incoming, B)
    bucket.client_put(incoming, A)
    run = await _run(engine, tenant, file_id, bucket)
    assert run["status"] == "finalized"
    final = (await _row(engine, tenant, file_id))["storage_key"]
    # Only bytes that hash to the claim bound at issuance are promoted.
    assert bucket.objects[final] == A


async def test_a_last_write_that_is_not_the_claimed_content_is_never_promoted(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, A)
    bucket.client_put(incoming, B)  # same length, different bytes: only the digest tells
    run = await _run(engine, tenant, file_id, bucket)
    assert run["status"] == "held" and run["failure"] == "integrity_mismatch"
    row = await _row(engine, tenant, file_id)
    assert (row["storage_key"], row["scan_status"], row["status"]) == (incoming, "pending", "ready")
    assert row["scan_failure"] == "integrity_mismatch" and row["checksum_verified_at"] is None
    assert _final_keys(bucket) == []
    (event,) = await _events(engine, tenant, file_id, "storage.upload.held")
    assert event["outcome"] == "failed" and "integrity_mismatch" in event["d"]


async def test_a_write_after_finalization_cannot_alter_the_final_object(engine, session) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, A)
    await _run(engine, tenant, file_id, bucket)
    final = (await _row(engine, tenant, file_id))["storage_key"]
    # An in-flight request landing after finalization: the ticket still names the incoming key.
    bucket.client_put(incoming, B)
    assert bucket.objects[final] == A
    # And the ticket was never signed for the final key.
    with pytest.raises(ClientCannotWrite):
        bucket.client_put(final, B)
    assert bucket.objects[final] == A


async def test_a_provider_copy_that_carries_another_objects_metadata_is_never_promoted(
    engine, session
) -> None:
    """The measured provider behaviour: an unsigned copy-source header turns the PUT into a copy.
    The copy has the right bytes, and no provenance of this ticket, so it is held."""
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, A)
    bucket.objects["tenants/other/documents/f/final/g/a.csv"] = A
    bucket.client_copy(incoming, "tenants/other/documents/f/final/g/a.csv")
    run = await _run(engine, tenant, file_id, bucket)
    assert run["status"] == "held" and run["failure"] == "integrity_mismatch"
    assert _final_keys(bucket) == ["tenants/other/documents/f/final/g/a.csv"]


async def test_a_forged_non_empty_provenance_is_not_the_expected_upload_identity(
    engine, session
) -> None:
    """Provenance must EQUAL the ticket's upload id; any other non-empty value is refused."""
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, A)
    bucket.meta[incoming] = str(uuid.uuid4())  # right bytes, someone else's identity
    run = await _run(engine, tenant, file_id, bucket)
    assert run["status"] == "held" and run["failure"] == "integrity_mismatch"
    assert _final_keys(bucket) == []
    assert not [c for c in bucket.calls if c[0] == "copy"], "nothing was copied before the check"


async def test_a_file_with_no_claim_is_held_and_given_none(engine, session) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, checksum_sha256=None)
    run = await _run(engine, tenant, file_id, bucket)
    assert run["status"] == "held" and run["failure"] == "integrity_mismatch"
    row = await _row(engine, tenant, file_id)
    assert row["checksum_sha256"] is None and row["storage_key"] == incoming
    assert bucket.calls == [], "no store call was made for a row with no claim"


async def test_a_missing_incoming_object_holds_the_file_unreachable(engine, session) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket)
    del bucket.objects[incoming]
    run = await _run(engine, tenant, file_id, bucket)
    assert run["status"] == "held" and run["failure"] == "object_unreachable"
    row = await _row(engine, tenant, file_id)
    assert row["scan_status"] == "pending" and row["storage_key"] == incoming


async def test_an_object_of_the_wrong_size_is_held_changed_and_not_copied(engine, session) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket)
    bucket.objects[incoming] = A + b"extra"
    run = await _run(engine, tenant, file_id, bucket)
    assert run["status"] == "held" and run["failure"] == "object_changed"
    assert not [c for c in bucket.calls if c[0] == "copy"]


async def test_a_refused_copy_is_held_and_nothing_is_left(engine, session) -> None:
    bucket = MemBucket(fail_copy=RuntimeError("CopyRefused"))
    tenant, file_id, incoming = await _seed(session, bucket)
    run = await _run(engine, tenant, file_id, bucket)
    assert run["status"] == "held" and run["failure"] == "object_unreachable"
    assert (await _row(engine, tenant, file_id))["storage_key"] == incoming
    assert _final_keys(bucket) == []


async def test_a_failed_incoming_delete_after_the_swap_leaves_a_correct_row_and_an_orphan(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket)
    bucket.fail_delete.add(incoming)
    run = await _run(engine, tenant, file_id, bucket)
    assert run["status"] == "finalized"
    row = await _row(engine, tenant, file_id)
    assert not is_incoming_key(row["storage_key"])
    assert incoming in bucket.objects, (
        "cleanup debt: an unreferenced object, never a referenced one"
    )


async def test_with_no_object_store_the_file_is_held_and_stays_on_its_incoming_key(
    engine, session, monkeypatch
) -> None:
    """Fail closed: a worker that cannot reach a store finalizes nothing and releases nothing."""
    for name in ("STORAGE_ENDPOINT", "STORAGE_BUCKET", "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY"):
        monkeypatch.setenv(name, "")
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket)
    async with sessions(engine)() as opened:
        run = await finalize_task.finalize_one(
            opened,
            UploadFinalizer(finalize_task._LazyFinalizeStore()),
            tenant_id=tenant,
            file_id=file_id,
            now=AFTER,
            max_attempts=8,
        )
    assert run["status"] == "held" and run["failure"] == "object_unreachable"
    row = await _row(engine, tenant, file_id)
    assert (row["storage_key"], row["scan_status"]) == (incoming, "pending")


# --- holds are recorded once, retried within bounds, and cleared when the file is final ------


async def test_the_same_refusal_twice_is_one_audit_event_and_two_attempts(engine, session) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket)
    del bucket.objects[incoming]
    first = await _run(engine, tenant, file_id, bucket)
    second = await _run(engine, tenant, file_id, bucket)
    assert (first["attempts"], second["attempts"]) == (1, 2)
    assert len(await _events(engine, tenant, file_id, "storage.upload.held")) == 1


async def test_a_changed_reason_is_a_second_event(engine, session) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, A)
    saved = bucket.objects.pop(incoming)
    await _run(engine, tenant, file_id, bucket)  # object_unreachable
    bucket.objects[incoming] = saved + b"x"  # now the wrong size
    await _run(engine, tenant, file_id, bucket)  # object_changed
    assert len(await _events(engine, tenant, file_id, "storage.upload.held")) == 2
    assert (await _row(engine, tenant, file_id))["scan_failure"] == "object_changed"


async def test_a_file_that_recovers_is_finalized_and_its_old_hold_is_cleared(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, A)
    saved = bucket.objects.pop(incoming)
    held = await _run(engine, tenant, file_id, bucket)
    assert held["status"] == "held"
    bucket.objects[incoming] = saved
    done = await _run(engine, tenant, file_id, bucket)
    assert done["status"] == "finalized" and done["attempts"] == 2
    row = await _row(engine, tenant, file_id)
    assert row["scan_failure"] is None and not is_incoming_key(row["storage_key"])


async def test_a_file_past_its_attempts_waits_for_a_person(engine, session) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket)
    del bucket.objects[incoming]
    for _ in range(2):
        await _run(engine, tenant, file_id, bucket, max_attempts=2)
    bucket.objects[incoming] = A  # the object is back, but the file has had its attempts
    run = await _run(engine, tenant, file_id, bucket, max_attempts=2)
    assert run["status"] == "exhausted"
    assert (await _row(engine, tenant, file_id))["storage_key"] == incoming


# --- the sweep, against the real selection ---------------------------------------------------


async def _due(engine, *, at=AFTER, retry_after=900, max_attempts=8) -> set[str]:
    async with sessions(engine)() as reader:
        await reader.execute(AS_PROVISIONING)
        rows = (
            await reader.execute(
                finalize_task._DUE,
                {
                    "due_before": at - timedelta(seconds=FINALIZE_DELAY_SECONDS),
                    "retry_before": at - timedelta(seconds=retry_after),
                    "max_attempts": max_attempts,
                    "batch": 1000,
                },
            )
        ).all()
        await reader.rollback()
    return {str(row.id) for row in rows}


async def test_the_sweep_selects_a_due_incoming_file_and_nothing_it_should_not(
    engine, session
) -> None:
    bucket = MemBucket()
    _, due, _ = await _seed(session, bucket)
    _, early, _ = await _seed(session, bucket, created_at=AFTER - timedelta(minutes=5))
    _, final, _ = await _seed(session, bucket, legacy=True)
    _, infected, _ = await _seed(session, bucket, scan_status="infected", status="quarantined")
    _, not_ready, _ = await _seed(session, bucket, status="pending")
    selected = await _due(engine)
    assert due in selected
    assert not {early, final, infected, not_ready} & selected


async def test_the_sweep_never_reselects_a_digest_that_was_not_the_claim(engine, session) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, A)
    bucket.client_put(incoming, B)
    await _run(engine, tenant, file_id, bucket)
    assert file_id not in await _due(engine, at=AFTER + timedelta(days=30))


async def test_the_sweep_retries_another_reason_only_after_its_back_off_and_within_bounds(
    engine, session
) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket)
    del bucket.objects[incoming]
    await _run(engine, tenant, file_id, bucket, at=AFTER)
    assert file_id not in await _due(engine, at=AFTER + timedelta(seconds=60))
    assert file_id in await _due(engine, at=AFTER + timedelta(seconds=901))
    assert file_id not in await _due(engine, at=AFTER + timedelta(days=1), max_attempts=1)


async def test_a_sweep_run_finalizes_what_no_job_did_and_releases_nothing(
    engine, session, monkeypatch
) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, created_at=datetime.now(UTC) - timedelta(days=1))
    monkeypatch.setattr(finalize_task, "_LazyFinalizeStore", lambda: bucket)
    monkeypatch.setattr(finalize_task.settings, "database_url", DATABASE_URL)
    result = await finalize_task.sweep_finalize({})
    assert result["status"] == "ran" and result["outcomes"].get("finalized", 0) >= 1
    row = await _row(engine, tenant, file_id)
    assert not is_incoming_key(row["storage_key"]) and row["storage_key"] in bucket.objects
    assert (row["status"], row["scan_status"]) == ("ready", "pending")


async def test_another_tenant_cannot_finalize_a_file(engine, session) -> None:
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket)
    other = str(uuid.uuid4())
    await session.execute(AS_PROVISIONING)
    await session.execute(
        text("insert into public.tenants (id, slug, name) values (cast(:t as uuid), :s, 'T')"),
        {"t": other, "s": f"fin-{other[:8]}"},
    )
    await session.commit()
    run = await _run(engine, other, file_id, bucket)
    outcome = await _finalize(engine, other, file_id, bucket)
    assert run["status"] == "not_eligible" and outcome.kind is FinalizeKind.NOT_ELIGIBLE
    assert bucket.calls == []
    assert (await _row(engine, tenant, file_id))["storage_key"] == incoming


async def test_a_legacy_shaped_key_is_never_copied_by_the_job(engine, session) -> None:
    """A key written before the capability is not rewritten, and not touched."""
    bucket = MemBucket()
    tenant, file_id, key = await _seed(session, bucket, legacy=True)
    before = await _row(engine, tenant, file_id)
    run = await _run(engine, tenant, file_id, bucket, at=ISSUED + timedelta(days=30))
    assert run["status"] == "already_final"
    after = await _row(engine, tenant, file_id)
    assert after["storage_key"] == key
    assert not [c for c in bucket.calls if c[0] in {"copy", "delete"}]
    assert after["scan_failure"] is None and after["scan_status"] == before["scan_status"]


async def test_backup_never_selects_an_incoming_key_and_the_swap_resets_backup_state(
    engine, session
) -> None:
    backup = pytest.importorskip("koras_worker.tasks.storage_backup")
    due_query = backup._due_query(True)
    bucket = MemBucket()
    tenant, file_id, incoming = await _seed(session, bucket, backup_status="copied")

    async def due() -> set[str]:
        async with sessions(engine)() as reader:
            await reader.execute(AS_PROVISIONING)
            rows = (await reader.execute(due_query, {"limit": 100000})).all()
            await reader.rollback()
        return {r.storage_key for r in rows}

    # `copied` is not due; make the row due so the selection could pick it up.
    async with sessions(engine)() as other:
        await other.execute(AS_TENANT, {"tenant_id": tenant})
        await other.execute(
            text("update public.files set backup_status = 'none' where id = cast(:f as uuid)"),
            {"f": file_id},
        )
        await other.commit()
    assert incoming not in await due(), "a still-writable object is never backed up"

    async with sessions(engine)() as other:
        await other.execute(AS_TENANT, {"tenant_id": tenant})
        await other.execute(
            text(
                "update public.files set backup_status = 'copied', backed_up_at = now() where id = cast(:f as uuid)"
            ),
            {"f": file_id},
        )
        await other.commit()
    outcome = await _finalize(engine, tenant, file_id, bucket)
    row = await _row(engine, tenant, file_id)
    assert (row["backup_status"], row["backed_up_at"]) == ("none", None)
    assert outcome.key in await due(), "the final object is what the next pass backs up"
    assert final_key_for(incoming, outcome.key.split("/")[-2]) == outcome.key
