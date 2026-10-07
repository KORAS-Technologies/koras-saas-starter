# ruff: noqa: ANN001, ANN201, ANN401, E501, S101
"""The scan transitions against a real PostgreSQL with row-level security on.

A fake session has no policies, no row locks and no second connection, so it
cannot show the three things S4 rests on: that the SQL is valid and the guard is
in the statement, that RLS and the tenant predicate leave another tenant's file
untouched, and that two workers racing on one file produce one verdict. Only a
real server and a role without `BYPASSRLS` can.

Skipped without a database, on the variable `playwright.config.ts` names. The
role in `E2E_DATABASE_URL` must be the restricted application role, not a
superuser; the test refuses to run as one.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get("E2E_DATABASE_URL", "")

if DATABASE_URL:
    os.environ["DATABASE_URL"] = DATABASE_URL
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="needs a real PostgreSQL; set E2E_DATABASE_URL (see playwright.config.ts)",
)

pytest.importorskip("koras_worker")
from koras_worker.scanning import (  # noqa: E402
    CleanEvidence,
    ObjectCheck,
    ObjectGate,
    ObjectIdentity,
    ScanFailure,
    ScanOutcome,
    ScanResult,
    TransitionKind,
    begin_attempt,
    commit_clean,
    commit_infected,
    record_failure,
)

AS_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")
AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)
NOW = datetime(2026, 10, 4, 12, 30, tzinfo=UTC)
DIGEST = "ab" * 32


def _evidence(
    tenant: str, file_id: str, etag: str = "etag-1", digest: str | None = None
) -> CleanEvidence:
    return CleanEvidence(
        tenant_id=tenant,
        file_id=file_id,
        storage_key=f"tenants/{tenant}/imports/{file_id}/a.csv",
        object_check=ObjectCheck(
            ObjectGate.READY, bytes_read=10, identity=ObjectIdentity(size=10, etag=etag)
        ),
        scan_result=ScanResult(ScanOutcome.CANDIDATE_CLEAN),
        structural_gate_passed=True,
        content_sha256=digest,
    )


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


async def _seed(session: AsyncSession, **file: object) -> tuple[str, str]:
    """A tenant and a ready, pending file, written as provisioning, unique per call."""
    tenant, file_id = str(uuid.uuid4()), str(uuid.uuid4())
    values: dict[str, object] = {
        "status": "ready",
        "scan_status": "pending",
        "checksum_sha256": None,
        "verified": None,
    }
    values.update(file)
    await session.execute(AS_PROVISIONING)
    await session.execute(
        text("insert into public.tenants (id, slug, name) values (cast(:t as uuid), :s, 'T')"),
        {"t": tenant, "s": f"scan-{tenant[:8]}"},
    )
    await session.commit()
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    await session.execute(
        text(
            "insert into public.files (id, tenant_id, storage_key, name, size_bytes, "
            "content_type, category, status, uploaded_by, scan_status, checksum_sha256, "
            "checksum_verified_at) values (cast(:f as uuid), cast(:t as uuid), :k, 'a.csv', 10, "
            "'text/csv', 'imports', :status, 'u', :scan_status, :checksum_sha256, :verified)"
        ),
        {"f": file_id, "t": tenant, "k": f"tenants/{tenant}/imports/{file_id}/a.csv", **values},
    )
    await session.commit()
    return tenant, file_id


async def _row(engine, tenant: str, file_id: str) -> dict[str, object]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as reader:
        await reader.execute(AS_TENANT, {"tenant_id": tenant})
        found = (
            (
                await reader.execute(
                    text("select * from public.files where id = cast(:f as uuid)"), {"f": file_id}
                )
            )
            .mappings()
            .one()
        )
        return dict(found)


async def _audit(engine, tenant: str, file_id: str) -> list[tuple[str, str, dict]]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as reader:
        await reader.execute(AS_TENANT, {"tenant_id": tenant})
        rows = (
            await reader.execute(
                text(
                    "select action, outcome, details from public.audit_events "
                    "where target_id = :f order by created_at, id"
                ),
                {"f": file_id},
            )
        ).all()
    return [
        (r.action, r.outcome, r.details if isinstance(r.details, dict) else json.loads(r.details))
        for r in rows
    ]


async def test_the_whole_lifecycle_through_the_real_statements(engine, session) -> None:
    tenant, file_id = await _seed(session)
    for _ in range(3):
        assert (
            await begin_attempt(session, tenant_id=tenant, file_id=file_id, now=NOW, max_attempts=3)
        ).kind is TransitionKind.APPLIED
        await record_failure(
            session, tenant_id=tenant, file_id=file_id, failure=ScanFailure.SCANNER_UNAVAILABLE
        )
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["status"], row["scan_attempts"]) == ("pending", "ready", 3)
    assert row["scan_failure"] == "scanner_unavailable" and row["scan_attempted_at"] == NOW

    done = await commit_clean(
        session, tenant_id=tenant, file_id=file_id, evidence=_evidence(tenant, file_id)
    )
    assert done.kind is TransitionKind.APPLIED
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["scan_object_etag"], row["scan_failure"]) == (
        "clean",
        "etag-1",
        None,
    )
    assert [a for a, _, _ in await _audit(engine, tenant, file_id)] == [
        "storage.object.scan_failed",
        "storage.object.scan_exhausted",
        "storage.object.scanned",
    ]


async def test_infected_quarantines_and_a_late_clean_cannot_undo_it(engine, session) -> None:
    tenant, file_id = await _seed(session)
    assert (await commit_infected(session, tenant_id=tenant, file_id=file_id)).kind is (
        TransitionKind.APPLIED
    )
    late = await commit_clean(
        session, tenant_id=tenant, file_id=file_id, evidence=_evidence(tenant, file_id)
    )
    assert late.kind is TransitionKind.NOT_ELIGIBLE
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["status"], row["scan_object_etag"]) == (
        "infected",
        "quarantined",
        None,
    )
    audit = await _audit(engine, tenant, file_id)
    assert [(a, o) for a, o, _ in audit] == [("storage.object.quarantined", "denied")]
    assert all("signature" not in json.dumps(d) for _, _, d in audit)


async def _clean_call(engine, tenant: str, file_id: str) -> TransitionKind:
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        return (
            await commit_clean(
                s, tenant_id=tenant, file_id=file_id, evidence=_evidence(tenant, file_id)
            )
        ).kind


async def _infected_call(engine, tenant: str, file_id: str) -> TransitionKind:
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        return (await commit_infected(s, tenant_id=tenant, file_id=file_id)).kind


def _quarantine_events(audit: list[tuple[str, str, dict]]) -> list[tuple[str, str, dict]]:
    return [a for a in audit if a[0] == "storage.object.quarantined"]


async def test_racing_verdicts_always_end_infected_with_one_quarantine(engine) -> None:
    """Two clean and two infected at once. Infected dominates, whatever the order."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as setup:
        tenant, file_id = await _seed(setup)

    kinds = await asyncio.gather(
        _clean_call(engine, tenant, file_id),
        _infected_call(engine, tenant, file_id),
        _clean_call(engine, tenant, file_id),
        _infected_call(engine, tenant, file_id),
    )
    # One infected always applies; a clean applies only if it took the lock first.
    assert kinds.count(TransitionKind.APPLIED) in {1, 2}
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["status"], row["scan_object_etag"]) == (
        "infected",
        "quarantined",
        None,
    )
    audit = await _audit(engine, tenant, file_id)
    assert len(_quarantine_events(audit)) == 1  # exactly one effective quarantine
    assert [a for a, _, _ in audit].count("storage.object.scanned") <= 1


async def test_clean_commits_first_and_a_later_infected_wins(engine, session) -> None:
    tenant, file_id = await _seed(session)
    assert await _clean_call(engine, tenant, file_id) is TransitionKind.APPLIED
    assert (await _row(engine, tenant, file_id))["scan_status"] == "clean"
    assert await _infected_call(engine, tenant, file_id) is TransitionKind.APPLIED
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["status"], row["scan_object_etag"]) == (
        "infected",
        "quarantined",
        None,
    )
    audit = await _audit(engine, tenant, file_id)
    assert [(a, o) for a, o, _ in audit] == [
        ("storage.object.scanned", "ok"),
        ("storage.object.quarantined", "denied"),
    ]
    assert audit[1][2] == {"scan_status": "infected", "overrode_clean": True}


async def test_infected_commits_first_and_a_later_clean_cannot_overwrite(engine, session) -> None:
    tenant, file_id = await _seed(session)
    assert await _infected_call(engine, tenant, file_id) is TransitionKind.APPLIED
    assert await _clean_call(engine, tenant, file_id) is TransitionKind.NOT_ELIGIBLE
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["status"], row["scan_object_etag"]) == (
        "infected",
        "quarantined",
        None,
    )
    assert [a for a, _, _ in await _audit(engine, tenant, file_id)] == [
        "storage.object.quarantined"
    ]


async def _blocked_sessions(engine) -> int:
    async with async_sessionmaker(engine, expire_on_commit=False)() as probe:
        return int(
            (
                await probe.execute(
                    text(
                        "select count(*) from pg_stat_activity where datname = current_database() "
                        "and cardinality(pg_blocking_pids(pid)) > 0 and query like '%public.files%'"
                    )
                )
            ).scalar_one()
        )


async def _wait_for_blocked(engine, count: int) -> None:
    for _ in range(200):
        if await _blocked_sessions(engine) >= count:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"{count} session(s) never queued on the row lock")


@pytest.mark.parametrize("clean_first", [True, False])
async def test_concurrent_clean_and_infected_end_infected_in_either_lock_order(
    engine, clean_first: bool
) -> None:
    """The lock queue is set up by hand: a holder keeps the row, the two verdicts queue behind
    it in a chosen order, and the holder lets go. The final state is the same both ways."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as setup:
        tenant, file_id = await _seed(setup)

    async with async_sessionmaker(engine, expire_on_commit=False)() as holder:
        await holder.execute(AS_TENANT, {"tenant_id": tenant})
        await holder.execute(
            text("select 1 from public.files where id = cast(:f as uuid) for update"),
            {"f": file_id},
        )
        first, second = (
            (_clean_call, _infected_call) if clean_first else (_infected_call, _clean_call)
        )
        t1 = asyncio.create_task(first(engine, tenant, file_id))
        await _wait_for_blocked(engine, 1)
        t2 = asyncio.create_task(second(engine, tenant, file_id))
        await _wait_for_blocked(engine, 2)
        await holder.rollback()  # release the row: the queue is served in order
    kinds = await asyncio.gather(t1, t2)

    clean_kind, infected_kind = (kinds[0], kinds[1]) if clean_first else (kinds[1], kinds[0])
    assert infected_kind is TransitionKind.APPLIED
    assert clean_kind is (TransitionKind.APPLIED if clean_first else TransitionKind.NOT_ELIGIBLE)
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["status"]) == ("infected", "quarantined")
    audit = await _audit(engine, tenant, file_id)
    assert len(_quarantine_events(audit)) == 1
    assert [a for a, _, _ in audit] == (
        ["storage.object.scanned", "storage.object.quarantined"]
        if clean_first
        else ["storage.object.quarantined"]
    )


async def test_racing_duplicate_infected_is_one_effective_quarantine(engine) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as setup:
        tenant, file_id = await _seed(setup, scan_status="clean")
    kinds = await asyncio.gather(*(_infected_call(engine, tenant, file_id) for _ in range(5)))
    assert kinds.count(TransitionKind.APPLIED) == 1
    assert kinds.count(TransitionKind.NOT_ELIGIBLE) == 4
    audit = await _audit(engine, tenant, file_id)
    assert len(audit) == 1 and audit[0][0] == "storage.object.quarantined"


async def test_a_clean_file_is_not_touched_by_any_other_operation(engine, session) -> None:
    """Only `commit_infected` acts on a clean row; attempts, failures and clean do not."""
    tenant, file_id = await _seed(session, scan_status="clean")
    before = await _row(engine, tenant, file_id)
    results = [
        await begin_attempt(session, tenant_id=tenant, file_id=file_id, now=NOW, max_attempts=3),
        await record_failure(
            session, tenant_id=tenant, file_id=file_id, failure=ScanFailure.SCAN_TIMEOUT
        ),
        await commit_clean(
            session, tenant_id=tenant, file_id=file_id, evidence=_evidence(tenant, file_id)
        ),
    ]
    assert {r.kind for r in results} == {TransitionKind.NOT_ELIGIBLE}
    assert await _row(engine, tenant, file_id) == before
    assert await _audit(engine, tenant, file_id) == []


async def test_a_duplicate_infected_after_quarantine_is_a_no_op(engine, session) -> None:
    tenant, file_id = await _seed(session, scan_status="clean")
    assert await _infected_call(engine, tenant, file_id) is TransitionKind.APPLIED
    before = await _row(engine, tenant, file_id)
    assert await _infected_call(engine, tenant, file_id) is TransitionKind.NOT_ELIGIBLE
    assert await _row(engine, tenant, file_id) == before
    assert len(await _audit(engine, tenant, file_id)) == 1


async def test_a_cross_tenant_late_infected_on_a_clean_file_is_refused(engine, session) -> None:
    tenant_a, _ = await _seed(session)
    tenant_b, file_b = await _seed(session, scan_status="clean")
    before = await _row(engine, tenant_b, file_b)
    late = await commit_infected(session, tenant_id=tenant_a, file_id=file_b)
    assert late.kind is TransitionKind.NOT_ELIGIBLE
    assert await _row(engine, tenant_b, file_b) == before
    assert await _audit(engine, tenant_b, file_b) == []
    assert await _audit(engine, tenant_a, file_b) == []


async def test_racing_attempts_each_count_and_exhaustion_is_written_once(engine) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as setup:
        tenant, file_id = await _seed(setup)

    async def one() -> int:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            result = await begin_attempt(
                s, tenant_id=tenant, file_id=file_id, now=NOW, max_attempts=3
            )
            assert result.attempts is not None
            return result.attempts

    counts = await asyncio.gather(*(one() for _ in range(6)))
    assert sorted(counts) == [1, 2, 3, 4, 5, 6]
    row = await _row(engine, tenant, file_id)
    assert (row["scan_attempts"], row["scan_status"]) == (6, "pending")
    audit = await _audit(engine, tenant, file_id)
    assert [a for a, _, _ in audit] == ["storage.object.scan_exhausted"]
    assert audit[0][2] == {"attempts": 3, "threshold": 3}


async def test_racing_equal_failures_write_one_event(engine) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as setup:
        tenant, file_id = await _seed(setup)

    async def fail() -> TransitionKind:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            return (
                await record_failure(
                    s, tenant_id=tenant, file_id=file_id, failure=ScanFailure.SCAN_TIMEOUT
                )
            ).kind

    kinds = await asyncio.gather(*(fail() for _ in range(4)))
    assert kinds.count(TransitionKind.APPLIED) == 1
    assert kinds.count(TransitionKind.UNCHANGED) == 3
    assert [a for a, _, _ in await _audit(engine, tenant, file_id)] == [
        "storage.object.scan_failed"
    ]


async def test_another_tenants_file_is_untouched_by_every_operation(engine, session) -> None:
    tenant_a, _ = await _seed(session)
    tenant_b, file_b = await _seed(session)
    before = await _row(engine, tenant_b, file_b)

    results = [
        await begin_attempt(session, tenant_id=tenant_a, file_id=file_b, now=NOW, max_attempts=3),
        await record_failure(
            session, tenant_id=tenant_a, file_id=file_b, failure=ScanFailure.SCAN_TIMEOUT
        ),
        await commit_infected(session, tenant_id=tenant_a, file_id=file_b),
        await commit_clean(
            session, tenant_id=tenant_a, file_id=file_b, evidence=_evidence(tenant_a, file_b)
        ),
    ]
    assert {r.kind for r in results} == {TransitionKind.NOT_ELIGIBLE}
    assert await _row(engine, tenant_b, file_b) == before
    assert await _audit(engine, tenant_b, file_b) == []
    assert await _audit(engine, tenant_a, file_b) == []


@pytest.mark.parametrize(
    "state",
    [
        {"scan_status": "skipped"},
        {"scan_status": "infected", "status": "quarantined"},
        {"status": "pending"},
        {"status": "archived"},
        {"scan_status": "clean", "status": "archived"},
        {"scan_status": "clean", "status": "quarantined"},
    ],
)
async def test_a_file_that_is_not_pending_and_ready_is_not_written(engine, session, state) -> None:
    tenant, file_id = await _seed(session, **state)
    before = await _row(engine, tenant, file_id)
    results = [
        await begin_attempt(session, tenant_id=tenant, file_id=file_id, now=NOW, max_attempts=3),
        await record_failure(
            session, tenant_id=tenant, file_id=file_id, failure=ScanFailure.SCAN_TIMEOUT
        ),
        await commit_infected(session, tenant_id=tenant, file_id=file_id),
        await commit_clean(
            session, tenant_id=tenant, file_id=file_id, evidence=_evidence(tenant, file_id)
        ),
    ]
    assert {r.kind for r in results} == {TransitionKind.NOT_ELIGIBLE}
    assert await _row(engine, tenant, file_id) == before


async def test_a_corroborated_digest_is_enforced_by_the_real_row(engine, session) -> None:
    tenant, file_id = await _seed(
        session, checksum_sha256=DIGEST, verified=datetime(2026, 10, 4, tzinfo=UTC)
    )
    wrong = await commit_clean(
        session,
        tenant_id=tenant,
        file_id=file_id,
        evidence=_evidence(tenant, file_id, digest="cd" * 32),
    )
    assert (wrong.kind, wrong.failure) == (TransitionKind.HELD, ScanFailure.INTEGRITY_MISMATCH)
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["scan_failure"], row["scan_object_etag"]) == (
        "pending",
        "integrity_mismatch",
        None,
    )
    right = await commit_clean(
        session,
        tenant_id=tenant,
        file_id=file_id,
        evidence=_evidence(tenant, file_id, digest=DIGEST),
    )
    assert right.kind is TransitionKind.APPLIED
    assert (await _row(engine, tenant, file_id))["scan_status"] == "clean"
    assert [a for a, _, _ in await _audit(engine, tenant, file_id)] == [
        "storage.object.scan_failed",
        "storage.object.scanned",
    ]


async def test_an_audit_failure_rolls_the_state_back_for_real(engine, session, monkeypatch) -> None:
    """A verdict and its event are one commit: break the event and the verdict is not there."""
    from koras_api.core import audit

    tenant, file_id = await _seed(session)

    async def broken(self) -> int:  # noqa: ANN001
        raise RuntimeError("audit down")

    monkeypatch.setattr(audit.SqlAuditSink, "flush", broken)
    with pytest.raises(RuntimeError):
        await commit_infected(session, tenant_id=tenant, file_id=file_id)
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["status"]) == ("pending", "ready")


async def test_an_audit_failure_on_the_override_leaves_the_file_clean_for_real(
    engine, session, monkeypatch
) -> None:
    """The quarantine and its SECURITY event are one commit; no best-effort audit."""
    from koras_api.core import audit

    tenant, file_id = await _seed(session, scan_status="clean")

    async def broken(self) -> int:  # noqa: ANN001
        raise RuntimeError("audit down")

    monkeypatch.setattr(audit.SqlAuditSink, "flush", broken)
    with pytest.raises(RuntimeError):
        await commit_infected(session, tenant_id=tenant, file_id=file_id)
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["status"]) == ("clean", "ready")
    monkeypatch.undo()
    assert await _infected_call(engine, tenant, file_id) is TransitionKind.APPLIED  # the retry
    assert (await _row(engine, tenant, file_id))["scan_status"] == "infected"


@pytest.mark.parametrize("state", ["pending", "clean"])
async def test_a_missing_audit_dependency_fails_closed_for_real(
    engine, session, monkeypatch, state
) -> None:
    """No audit module, no quarantine; the row is as it was and a retry succeeds."""
    from koras_worker.scanning import transition as transition_module
    from koras_worker.scanning.transition import TransitionUnavailable

    tenant, file_id = await _seed(session, scan_status=state)
    before = await _audit(engine, tenant, file_id)
    original = transition_module._audit_module
    monkeypatch.setattr(transition_module, "_audit_module", lambda: None)
    with pytest.raises(TransitionUnavailable):
        await commit_infected(session, tenant_id=tenant, file_id=file_id)
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["status"]) == (state, "ready")
    assert await _audit(engine, tenant, file_id) == before  # no quarantine event
    monkeypatch.setattr(transition_module, "_audit_module", original)
    assert await _infected_call(engine, tenant, file_id) is TransitionKind.APPLIED
    assert (await _row(engine, tenant, file_id))["scan_status"] == "infected"
    assert len(_quarantine_events(await _audit(engine, tenant, file_id))) == 1
