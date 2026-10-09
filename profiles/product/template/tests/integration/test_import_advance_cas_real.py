"""GR-383: a run moves only from the state its caller saw, against a real PostgreSQL.

`_advance` used to check the edge against a frozen in-memory snapshot and then
issue `update public.import_runs ... where id = :id`, so the database never
agreed to the edge the caller had checked. Four races followed:

1. a run cancelled while `validating` was overwritten by the worker's verdict,
   and a cancelled run could then be confirmed and written;
2. two confirmations both passed, the loser overwrote `committed_by` and wrote
   an `import.run.committed` audit row for a confirmation that lost;
3. a late second confirmation regressed `committed` to `commit_requested`;
4. a cancellation raced the worker's claim (`begin_commit`), and a cancelled
   run ended up committed with its rows written.

The fix is a compare-and-set: `where id = ... and status = <the snapshot's
status>`. Every case here makes the snapshot stale on purpose -- a second
session moves the run first -- and then asserts the late writer is refused and
that nothing of it persisted. Counts and statuses are read on a third
connection after the fact.

Skipped without a database, for the reason `test_import_commit_atomic.py`
gives; CI runs it in the same step.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

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

from test_import_commit_atomic import (  # noqa: E402
    AS_TENANT,
    SUBJECT,
    TENANT,
    _csv,
    _install,
    _job,
    _seed,
    _state,
    _target,
    _writing,
)

OTHER_SUBJECT = "e2e-second-confirmer"


@pytest.fixture(autouse=True)
async def _fresh_application_pool() -> AsyncIterator[None]:
    """The API's own engine pools connections bound to the event loop that opened them.

    Each test has a loop of its own, and one test here goes through the route's
    `tenant_session`. A connection left pooled on that loop makes the next module that
    uses the API's engine from another loop (the source-state suite, whose `TestClient`
    runs its own) fail with "attached to a different loop", so the pool is emptied on
    both sides of every test.
    """
    from koras_api.core.engine import engine as application_engine

    await application_engine.dispose()
    try:
        yield
    finally:
        await application_engine.dispose()


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    made = create_async_engine(DATABASE_URL)
    yield made
    await made.dispose()


def _maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _open(engine: AsyncEngine) -> AsyncSession:
    session = _maker(engine)()
    await session.execute(AS_TENANT, {"tenant_id": TENANT})
    return session


async def _snapshot(engine: AsyncEngine, run_id: str) -> Any:  # noqa: ANN401
    """The run as a caller read it: the frozen `Run` every store function takes."""
    from koras_api.core import imports as store

    session = await _open(engine)
    try:
        run = await store.get(session, run_id)
    finally:
        await session.close()
    assert run is not None
    return run


async def _row(engine: AsyncEngine, run_id: str) -> Any:  # noqa: ANN401
    async with _maker(engine)() as session:
        await session.execute(AS_TENANT, {"tenant_id": TENANT})
        return (
            await session.execute(
                text(
                    "select status, committed_by, error from public.import_runs"
                    " where id = cast(:id as uuid)"
                ),
                {"id": run_id},
            )
        ).one()


async def _move(engine: AsyncEngine, run_id: str, status: str) -> None:
    """Another actor moves the run, committed, behind the first caller's back."""
    async with _maker(engine)() as session:
        await session.execute(AS_TENANT, {"tenant_id": TENANT})
        await session.execute(
            text("update public.import_runs set status = :s where id = cast(:id as uuid)"),
            {"s": status, "id": run_id},
        )
        await session.commit()


async def _audit_rows(engine: AsyncEngine, run_id: str) -> list[str]:
    async with _maker(engine)() as session:
        await session.execute(AS_TENANT, {"tenant_id": TENANT})
        rows = await session.execute(
            text(
                "select actor_id from public.audit_events"
                " where target_id = :id and action = 'import.run.committed'"
            ),
            {"id": run_id},
        )
        return [row.actor_id for row in rows]


async def _kept_error_rows(engine: AsyncEngine, run_id: str) -> int:
    async with _maker(engine)() as session:
        await session.execute(AS_TENANT, {"tenant_id": TENANT})
        return int(
            (
                await session.execute(
                    text(
                        "select count(*) from public.import_row_errors"
                        " where run_id = cast(:id as uuid)"
                    ),
                    {"id": run_id},
                )
            ).scalar_one()
        )


# 1 -- cancel during validating, then the worker's verdict --------------------


async def test_a_verdict_that_arrives_after_a_cancellation_is_refused_and_keeps_nothing(
    engine: AsyncEngine,
) -> None:
    from koras_api.core import imports as store
    from koras_import import RowError, TransitionRefused, Validation

    run_id = await _seed(engine, _csv(), status="validating")
    stale = await _snapshot(engine, run_id)  # what the worker is holding

    canceller = await _open(engine)
    await store.cancel(canceller, await _snapshot(engine, run_id))
    await canceller.commit()
    await canceller.close()

    worker = await _open(engine)
    problem = RowError(row=2, column="Email", field="email", code="import.error.email", value="v")
    with pytest.raises(TransitionRefused):
        await store.record_validation(
            worker,
            stale,
            tenant_id=TENANT,
            result=Validation(rows=1, valid=0, errors=(problem,), truncated=False),
        )
    await worker.rollback()
    await worker.close()

    assert (await _row(engine, run_id)).status == "cancelled"
    assert await _kept_error_rows(engine, run_id) == 0, "the refused verdict kept rows"


async def test_the_worker_skips_a_validation_whose_run_was_cancelled_underneath_it(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from koras_api.core import imports as store

    raw = _csv()
    task = _install(monkeypatch, raw, _target(_writing()))
    run_id = await _seed(engine, raw, status="validating")

    real = store.predict_outcome

    async def cancelled_meanwhile(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        await _move(engine, run_id, "cancelled")
        return await real(*args, **kwargs)

    monkeypatch.setattr(store, "predict_outcome", cancelled_meanwhile)

    answer = await task.validate_run({}, _job(run_id))

    assert answer["status"] == "skipped", answer
    assert (await _row(engine, run_id)).status == "cancelled"
    assert await _kept_error_rows(engine, run_id) == 0


# 2 -- two confirmations at once ----------------------------------------------


async def test_two_sessions_confirming_the_same_run_one_wins_and_the_other_is_refused(
    engine: AsyncEngine,
) -> None:
    from koras_api.core import imports as store
    from koras_import import TransitionRefused

    run_id = await _seed(engine, _csv(), status="validated")
    first_snapshot = await _snapshot(engine, run_id)
    second_snapshot = await _snapshot(engine, run_id)  # both saw `validated`

    winner = await _open(engine)
    loser = await _open(engine)
    await store.request_commit(winner, first_snapshot, by="winner")
    # The loser's UPDATE waits on the winner's row lock, then re-reads the row.
    pending = asyncio.ensure_future(store.request_commit(loser, second_snapshot, by="loser"))
    await asyncio.sleep(0.3)
    assert not pending.done(), "the loser should be waiting on the winner's row lock"
    await winner.commit()
    with pytest.raises(TransitionRefused):
        await pending
    await loser.rollback()
    await winner.close()
    await loser.close()

    row = await _row(engine, run_id)
    assert (row.status, row.committed_by) == ("commit_requested", "winner")


async def test_two_confirmations_of_one_run_leave_one_audit_row_and_one_committer(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route, twice at once: the loser must not audit a confirmation it lost."""
    from fastapi import HTTPException
    from koras_api.core import imports as store
    from koras_api.core.database import tenant_session
    from koras_api.routers import imports as route
    from koras_auth import JWTClaims
    from koras_import import build_registry
    from koras_platform import OrganizationRole
    from koras_tenant import TenantContext

    target = _target(_writing())
    monkeypatch.setattr(route, "registry", build_registry([target]))
    run_id = await _seed(engine, _csv(), status="validated")

    # Both requests read the run before either writes, which is the window.
    barrier = asyncio.Barrier(2)
    seen: set[int] = set()
    real_get = store.get

    async def meet_after_first_read(session: AsyncSession, rid: str) -> Any:  # noqa: ANN401
        run = await real_get(session, rid)
        marker = id(asyncio.current_task())
        if marker not in seen:
            seen.add(marker)
            await asyncio.wait_for(barrier.wait(), timeout=10)
        return run

    monkeypatch.setattr(store, "get", meet_after_first_read)

    enqueued: list[str] = []

    class _Jobs:
        async def enqueue(self, *_: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            key = kwargs["idempotency_key"]
            duplicate = key in enqueued
            enqueued.append(key)
            return SimpleNamespace(simulated=False, duplicate=duplicate, job_id="job-1")

    async def confirm(subject: str) -> str:
        claims = JWTClaims(sub=subject, roles=frozenset({OrganizationRole.OWNER}))
        tenant = TenantContext(
            id=TENANT, slug="e2e", name="E2E", organization_id="e2e-org", user_id=subject
        )
        async with tenant_session(TENANT, user_id=subject) as session:
            try:
                await route.commit(run_id, claims, tenant, session, _Jobs())  # type: ignore[arg-type]
            except HTTPException as refused:
                return f"{refused.status_code}"
        return "202"

    answers = await asyncio.gather(confirm("confirmer-a"), confirm("confirmer-b"))

    assert sorted(answers) == ["202", "409"], answers
    row = await _row(engine, run_id)
    audited = await _audit_rows(engine, run_id)
    assert len(audited) == 1, f"{len(audited)} confirmations audited for one run"
    assert row.committed_by == audited[0]
    assert row.status == "commit_requested"
    assert len(enqueued) == 1, "the loser must not reach the queue"


# 3 -- a late second confirmation of a committed run --------------------------


async def test_confirming_a_run_that_has_already_committed_is_refused_and_changes_nothing(
    engine: AsyncEngine,
) -> None:
    from koras_api.core import imports as store
    from koras_import import TransitionRefused

    run_id = await _seed(engine, _csv(), status="validated")
    stale = await _snapshot(engine, run_id)  # `validated`, as the late confirmer saw it
    await _move(engine, run_id, "committed")

    session = await _open(engine)
    with pytest.raises(TransitionRefused):
        await store.request_commit(session, stale, by=OTHER_SUBJECT)
    await session.rollback()
    await session.close()

    row = await _row(engine, run_id)
    assert row.status == "committed"
    assert row.committed_by == SUBJECT, "the late confirmer overwrote the real one"


# 4 -- a cancellation against the worker's claim ------------------------------


async def test_a_claim_that_loses_to_a_cancellation_is_refused(engine: AsyncEngine) -> None:
    from koras_api.core import imports as store
    from koras_import import TransitionRefused

    run_id = await _seed(engine, _csv(), status="commit_requested")
    stale = await _snapshot(engine, run_id)
    await _move(engine, run_id, "cancelled")

    session = await _open(engine)
    with pytest.raises(TransitionRefused):
        await store.begin_commit(session, stale)
    await session.rollback()
    await session.close()

    assert (await _row(engine, run_id)).status == "cancelled"


async def test_a_cancellation_that_loses_to_the_claim_is_refused(engine: AsyncEngine) -> None:
    from koras_api.core import imports as store
    from koras_import import TransitionRefused

    run_id = await _seed(engine, _csv(), status="commit_requested")
    stale = await _snapshot(engine, run_id)
    await _move(engine, run_id, "committing")

    session = await _open(engine)
    with pytest.raises(TransitionRefused):
        await store.cancel(session, stale)
    await session.rollback()
    await session.close()

    assert (await _row(engine, run_id)).status == "committing"


async def test_a_commit_whose_claim_lost_to_a_cancellation_writes_nothing(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from koras_api.core import imports as store

    raw = _csv()
    task = _install(monkeypatch, raw, _target(_writing()))
    run_id = await _seed(engine, raw, status="commit_requested")

    real = store.begin_commit

    async def cancelled_first(session: AsyncSession, run: Any) -> None:  # noqa: ANN401
        await _move(engine, run_id, "cancelled")
        await real(session, run)

    monkeypatch.setattr(store, "begin_commit", cancelled_first)

    answer = await task.commit_run({}, _job(run_id))

    assert answer["status"] == "skipped", answer
    assert answer["reason"] == "not claimable"
    run, written = await _state(engine, run_id)
    assert written == 0, f"{written} rows were written for a cancelled run"
    assert run.status == "cancelled"


async def test_a_commit_that_finds_its_run_taken_from_it_rolls_back_every_row(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`record_commit` shares the writer's transaction; a miss must undo the rows."""
    raw = _csv(20)

    taken = False

    def writer_that_loses_the_run() -> Any:  # noqa: ANN401
        inner = _writing()

        async def writer(session: AsyncSession, request: Any) -> Any:  # noqa: ANN401
            nonlocal taken
            written = await inner(session, request)
            if not taken:
                taken = True
                # Another actor ends the run (the queue's timeout abandoning it,
                # say) after the claim has committed and before the result is
                # recorded.
                await _move(engine, request.run_id, "failed")
            return written

        return writer

    task = _install(monkeypatch, raw, _target(writer_that_loses_the_run()))
    run_id = await _seed(engine, raw, status="commit_requested")

    answer = await task.commit_run({}, _job(run_id))

    assert answer["status"] == "skipped", answer
    run, written = await _state(engine, run_id)
    assert written == 0, f"{written} rows survived a result that could not be recorded"
    assert run.status == "failed"


async def test_a_verdict_on_a_stale_mapped_snapshot_ends_failed_not_stranded(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The validate route enqueues before it commits `mapped -> validating`."""
    from koras_api.core import imports as store
    from koras_import import TransitionRefused

    raw = _csv()
    task = _install(monkeypatch, raw, _target(_writing()))
    run_id = await _seed(engine, raw, status="mapped")

    real = store.predict_outcome

    async def route_commits_meanwhile(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        await _move(engine, run_id, "validating")
        return await real(*args, **kwargs)

    monkeypatch.setattr(store, "predict_outcome", route_commits_meanwhile)

    with pytest.raises(TransitionRefused):
        await task.validate_run({}, _job(run_id))

    row = await _row(engine, run_id)
    assert row.status == "failed", "the run was left in validating with no job"
    assert await _kept_error_rows(engine, run_id) == 0
