"""The commit path, against a real PostgreSQL with row-level security on.

**This file exists because two defects reached a shipped feature and neither
was visible to anything else in this repository.** Both are in
`docs/features/data-import/phase-2-review.md`.

*The first* was that the commit could never succeed. `begin_commit` was defined
and exported and called by nothing, so `record_commit` asked the machine for
`commit_requested -> committed`, an edge it does not have. The writer ran, the
rows rolled back, and the failure that was then recorded was refused by the same
gap and escaped uncaught. Every commit of every product wrote nothing.

*The second* was in the fix for the first. The claim commits its own
transaction, and the worker declares its tenant with `set_config(..., true)` --
transaction-local. Committing ended the transaction those settings belonged to,
so the very next statement ran with no tenant, row-level security matched
nothing, and the run the worker had just claimed read back as absent.

**The second one is why this file is not a unit test.** It does not raise, it
does not fail a type check, and against an in-memory double it does not happen
at all: a fake session has no transaction and no policies, so the context it
does not have cannot be lost. The only thing that reproduces it is a real
PostgreSQL, a role without `BYPASSRLS`, and policies that are on.

Skipped without a database, because a suite that fails on a laptop with no
Postgres is a suite people stop running -- the same argument
`playwright.config.ts` makes for the round trip, and the same variable.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
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

# The worker builds its `Settings()` at import, so these have to be present
# before `koras_worker.tasks.imports` is reached -- the same arrangement every
# other worker test here makes. `DATABASE_URL` is the one that matters: it is
# what the task opens its own engine on, so it must be the database this test
# seeded rather than whatever a developer has exported.
if DATABASE_URL:
    os.environ["DATABASE_URL"] = DATABASE_URL
os.environ.setdefault("ENVIRONMENT", "dev")
# Never connected to on this path: the commit is the job, not the enqueue.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="needs a real PostgreSQL; set E2E_DATABASE_URL (see playwright.config.ts)",
)

#: The organisation `e2e/support/seed.sql` creates. Reused rather than inserted
#: here: the seed is the fixture, and a test that wrote its own tenant would be
#: asserting against data no policy had ever been applied to.
TENANT = "00000000-0000-4e2e-8000-000000000001"
SUBJECT = "e2e-owner"

CSV = b"Email,Name\nann@example.test,Ann\nbo@example.test,Bo\n"

#: Exactly what `koras_worker.tasks.imports` declares, and it has to be: the
#: property under test is what happens to these settings when a transaction
#: ends, so a test that set them any other way would be testing its own SQL.
AS_TENANT = text(
    "select set_config('app.provisioning', '', true), "
    "set_config('app.tenant_id', :tenant_id, true)"
)


def _target(writer: Any) -> Any:  # noqa: ANN401 - the engine's own Writer alias
    """A committable target, declared here and registered nowhere.

    The generated product declares no import targets and must not: a target
    names a table the product owns, and the starter owns no domain. So the test
    brings its own, which is also the only way to control what the writer does.
    """
    from koras_import import FieldKind, FieldSpec, ImportTarget, Operation

    return ImportTarget(
        key="test.commit_probe",
        label_key="import.target.test.commit_probe",
        permission="imports.manage",
        fields=(
            FieldSpec(
                "email",
                "import.field.test.email",
                kind=FieldKind.EMAIL,
                required=True,
            ),
            FieldSpec("name", "import.field.test.name", required=True),
        ),
        match_keys=("email",),
        operations=(Operation.SKIP_DUPLICATE,),
        writer=writer,
    )


class _Bucket:
    """The object store, and the only thing here that is not real.

    The bytes it answers are a real CSV and the parser does real work on them.
    What is stubbed is the network call to fetch them, which is not the property
    under test and would make this suite need credentials.
    """

    async def get(self, key: str) -> bytes:
        del key
        return CSV


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    made = create_async_engine(DATABASE_URL)
    yield made
    await made.dispose()


async def _seed(engine: AsyncEngine, *, status: str) -> tuple[str, str]:
    """A file and a run, committed, in the state the worker expects to find."""
    run_id, file_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await session.execute(AS_TENANT, {"tenant_id": TENANT})
        await session.execute(
            text(
                "insert into public.files (id, tenant_id, category, name, storage_key,"
                " size_bytes, content_type, status, scan_status, uploaded_by)"
                " values (cast(:id as uuid), cast(:t as uuid), 'imports', 'probe.csv',"
                " :key, :size, 'text/csv', 'ready', 'clean', :by)"
            ),
            {
                "id": file_id,
                "t": TENANT,
                "key": f"imports/{file_id}.csv",
                "size": len(CSV),
                "by": SUBJECT,
            },
        )
        await session.execute(
            text(
                "insert into public.import_runs (id, tenant_id, target, status, format,"
                " source_file_id, delimiter, encoding, columns, mapping, operation,"
                " rows_total, rows_valid, errors_total, requested_by, committed_by)"
                " values (cast(:id as uuid), cast(:t as uuid), 'test.commit_probe',"
                " :status, 'csv', cast(:f as uuid), ',', 'utf-8-sig', :cols,"
                " cast(:map as jsonb), 'skip_duplicate', 2, 2, 0, :by, :by)"
            ),
            {
                "id": run_id,
                "t": TENANT,
                "f": file_id,
                "status": status,
                "cols": ["Email", "Name"],
                "map": '{"Email":"email","Name":"name"}',
                "by": SUBJECT,
            },
        )
        await session.commit()
    return run_id, file_id


async def _run_row(engine: AsyncEngine, run_id: str) -> Any:  # noqa: ANN401 - a Row
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await session.execute(AS_TENANT, {"tenant_id": TENANT})
        return (
            await session.execute(
                text(
                    "select status, error from public.import_runs"
                    " where id = cast(:id as uuid)"
                ),
                {"id": run_id},
            )
        ).first()


async def _commit(
    monkeypatch: pytest.MonkeyPatch,
    engine: AsyncEngine,
    run_id: str,
    writer: Any,  # noqa: ANN401 - the engine's own Writer alias
) -> dict[str, Any]:
    """Drive the product's own worker task, not a copy of it."""
    import koras_api.imports.targets as product_targets
    import koras_worker.tasks.imports as task
    from koras_import import build_registry
    from koras_queue import JobEnvelope

    monkeypatch.setattr(task, "_object_store", lambda: _Bucket())
    monkeypatch.setattr(
        task, "_registry", lambda: build_registry([_target(writer)])
    )
    # The product's own list stays empty throughout, which is the invariant this
    # test must not quietly break.
    assert product_targets.TARGETS == []

    return await task.commit_run(
        {},
        JobEnvelope(
            task="import.commit",
            tenant_id=TENANT,
            payload={"run_id": run_id},
            actor_id=SUBJECT,
        ),
    )


async def test_the_tenant_survives_the_claim_and_the_commit_completes(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression, and it fails the moment the tenant is not re-declared.

    The claim moves the run to `committing` and **commits**. Everything after
    that point runs in a new transaction, and `app.tenant_id` does not carry:
    without re-declaring it the worker's own re-read of the run it just claimed
    returns nothing, the task logs that the run vanished and answers
    `{"status": "skipped"}`, and the assertion below fails on that.

    It is not an exception and nothing about it is loud, which is the reason
    this test is here rather than a comment.
    """
    seen: dict[str, int] = {}

    async def writer(session: AsyncSession, request: Any) -> Any:  # noqa: ANN401
        from koras_import import Written

        # A real statement on the caller's session, so the writer is inside the
        # transaction whose isolation is being asserted. It reads rather than
        # writes: what a row lands in is the product's business, and every
        # generated product's business is different.
        visible = (
            await session.execute(
                text("select count(*) from public.import_runs")
            )
        ).scalar_one()
        seen["runs_visible_to_the_writer"] = visible
        return Written(skipped=len(request.rows))

    run_id, _ = await _seed(engine, status="commit_requested")

    answer = await _commit(monkeypatch, engine, run_id, writer)

    assert answer["status"] == "ok", (
        f"the commit did not complete: {answer}. A 'skipped' answer with reason "
        "'no run' is the tenant context being lost by the claim's commit."
    )
    row = await _run_row(engine, run_id)
    assert row.status == "committed"
    assert row.error is None

    # The writer ran inside a transaction that could see this organisation's
    # rows. Zero would mean it ran with no tenant and every policy matched
    # nothing -- a commit that "succeeded" over an empty view of the database.
    assert seen["runs_visible_to_the_writer"] >= 1


async def test_a_writer_that_raises_records_the_failure_rather_than_stranding(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the same defect, and it needs its own edge.

    A failed commit is recorded in a second transaction opened after the first
    has rolled back. That transaction moves the run to `failed` -- and until
    2026-09-22 `commit_requested` had no edge to `failed`, so the recording
    raised, escaped past the notification, and left the run in a state nothing
    in the codebase could move it out of again.

    Asserted on the row rather than on the task's answer, because the symptom
    was a run stuck in the database while the log said something had happened.
    """

    async def writer(session: AsyncSession, request: Any) -> Any:  # noqa: ANN401
        del session, request
        raise RuntimeError("the writer fell over")

    run_id, _ = await _seed(engine, status="commit_requested")

    answer = await _commit(monkeypatch, engine, run_id, writer)

    assert answer["status"] == "failed"
    row = await _run_row(engine, run_id)
    assert row.status == "failed", (
        f"the run is {row.status!r}; a run left in 'commit_requested' is the "
        "failure path being refused by the state machine"
    )
    assert row.error


async def test_a_committed_run_is_not_committed_a_second_time(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay safety, on the state machine rather than on the queue's lock.

    The deterministic job id stops two workers running at once; it says nothing
    about a job delivered again later. What makes a second commit impossible is
    that `committed` is terminal, and this asserts the worker honours it rather
    than that the edge table says so.
    """
    calls: list[int] = []

    async def writer(session: AsyncSession, request: Any) -> Any:  # noqa: ANN401
        from koras_import import Written

        del session
        calls.append(len(request.rows))
        return Written(skipped=len(request.rows))

    run_id, _ = await _seed(engine, status="commit_requested")

    first = await _commit(monkeypatch, engine, run_id, writer)
    assert first["status"] == "ok"
    assert len(calls) == 1

    second = await _commit(monkeypatch, engine, run_id, writer)

    assert second["status"] == "skipped"
    assert len(calls) == 1, "the writer ran a second time on an already committed run"
    row = await _run_row(engine, run_id)
    assert row.status == "committed"


async def test_a_failure_before_the_claim_is_recorded_rather_than_stranding(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The edge the other failure test does not reach.

    A commit can fail *before* anything is claimed: the target lost its writer,
    the product no longer declares it, or the queue was unconfigured and the
    route recorded the failure itself. The run is still `commit_requested` at
    that point, and until 2026-09-22 the machine had no edge from there to
    `failed` -- so recording it raised, escaped past the notification, and left
    the run somewhere nothing could move it out of.

    **This case exists because removing that edge left the other three tests
    green.** Their writer fails *after* the claim, by which time the run is
    `committing`, and `committing -> failed` has always existed. A mutation that
    reintroduced the whole defect was invisible to them. IMP2-02 in
    `docs/features/data-import/phase-2-review.md`.
    """
    run_id, _ = await _seed(engine, status="commit_requested")

    # A target with no writer: legitimate, and the second gate the worker keeps
    # for one that lost its writer between the request and the job.
    answer = await _commit(monkeypatch, engine, run_id, None)

    assert answer["status"] == "failed"
    row = await _run_row(engine, run_id)
    assert row.status == "failed", (
        f"the run is {row.status!r}. A run left in 'commit_requested' cannot be "
        "moved by any route or sweep in this product -- it is stranded for good"
    )
    assert row.error
