# ruff: noqa: ANN001, ANN002, ANN003, ANN201, ANN202, ANN204, ANN401, E501, S101, S608, E402
"""The scan sweep against a real PostgreSQL (and, for the queue identity, a real Redis).

What only a server can show: that the selection SQL is valid under forced RLS as
the restricted role; what is and is not due (the window, the watermark, the
ceiling, the back-off and its cap); that exhaustion does not remove a file from
the sweep; that pagination is complete and ordered; that the sweep's only
cross-tenant read returns identifiers and that tenant context sees only its own;
that an interrupted run really persists `scan_interrupted` through the real
constraint; and that the queue's retained result would have silently blocked a
re-enqueue without the sweep's cleanup.

Skipped without a database (`E2E_DATABASE_URL`). The role must be the restricted
application role. The object source and the scanner are the deterministic fakes;
the database, the transitions, the audit sink and the sweep are the real ones.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

DATABASE_URL = os.environ.get("E2E_DATABASE_URL", "")
REDIS_URL = os.environ.get("E2E_REDIS_URL", "redis://localhost:6379/5")

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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
pytest.importorskip("koras_worker")
from koras_queue import ArqJobQueue, RecordingJobQueue, job_id_for  # noqa: E402
from koras_worker.scanning import ObjectReader, ScanDisposition, scan_file  # noqa: E402
from koras_worker.tasks.scan_sweep import (  # noqa: E402
    BACKOFF_CAP_SECONDS,
    DueFile,
    FairCursor,
    ScanSweepSettings,
    select_due,
    sweep,
)
from object_support import FakeObjectSource, identity  # noqa: E402
from scanner_support import FakeScanner  # noqa: E402
from test_scan_runtime_real import (  # noqa: E402
    AS_PROVISIONING,
    AS_TENANT,
    CSV,
    _audit,
    _row,
    _seed,
    engine,
    sessions,
)

assert engine  # re-exported fixture

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
WATERMARK = NOW - timedelta(days=1)
MIN = timedelta(minutes=1)


def config(**overrides) -> ScanSweepSettings:
    values = {
        "file_scan_sweep_not_before": WATERMARK,
        "file_scan_backend": "clamd",
    }
    values.update(overrides)
    return ScanSweepSettings(**values)


async def due_files(engine, now=NOW, **overrides) -> list[DueFile]:
    """Everything the sweep would select over as many pages as it takes, in the order served."""
    overrides.setdefault("file_scan_sweep_batch_size", 500)
    overrides.setdefault("file_scan_sweep_max_batches", 20)
    found: list[DueFile] = []
    cursor = FairCursor()
    cfg = config(**overrides)
    for _ in range(cfg.file_scan_sweep_max_batches):
        if cursor.exhausted:
            break
        async with sessions(engine)() as session:
            page = await select_due(session, config=cfg, now=now, cursor=cursor)
        if not page:
            break
        found += page
    return found


async def due_ids(engine, now=NOW, **overrides) -> set[str]:
    return {d.file_id for d in await due_files(engine, now, **overrides)}


async def seed(session, *, age: timedelta, tenant=None, **file) -> tuple[str, str]:
    return await _seed(session, created_at=NOW - age, tenant=tenant, **file)


async def mark(engine, tenant: str, file_id: str, **columns) -> None:
    """Set scan columns the way `begin_attempt` would have left them, as the tenant."""
    assignments = ", ".join(f"{name} = :{name}" for name in columns)
    async with sessions(engine)() as session:
        await session.execute(AS_TENANT, {"tenant_id": tenant})
        await session.execute(
            text(f"update public.files set {assignments} where id = cast(:f as uuid)"),
            {"f": file_id, **columns},
        )
        await session.commit()


# ================================================================= what is due


async def test_a_never_attempted_file_is_due_only_after_the_window_plus_one_sweep_interval(
    engine,
) -> None:
    async with sessions(engine)() as session:
        t, young = await seed(session, age=20 * MIN)
        _, old = await seed(session, age=22 * MIN)
        _, edge = await seed(session, age=21 * MIN)
    found = await due_ids(engine)
    assert old in found and edge in found
    assert young not in found, "inside the 16 minute window plus the 5 minute grace"


async def test_the_watermark_excludes_every_file_created_before_it(engine) -> None:
    async with sessions(engine)() as session:
        _, before = await _seed(session, created_at=WATERMARK - MIN)
        _, after = await _seed(session, created_at=WATERMARK + MIN)
    found = await due_ids(engine)
    assert before not in found and after in found


async def test_the_sweep_cannot_select_a_file_that_is_not_ready_and_pending(engine) -> None:
    async with sessions(engine)() as session:
        _, uploading = await seed(session, age=2 * 60 * MIN, status="pending")
        _, clean = await seed(session, age=2 * 60 * MIN, scan_status="clean")
        _, infected = await seed(session, age=2 * 60 * MIN, scan_status="infected")
        _, skipped = await seed(session, age=2 * 60 * MIN, scan_status="skipped")
    found = await due_ids(engine)
    assert not ({uploading, clean, infected, skipped} & found)


async def test_a_file_over_the_ceiling_is_never_selected_and_is_again_when_it_is_raised(
    engine,
) -> None:
    async with sessions(engine)() as session:
        _, big = await seed(session, age=60 * MIN, body=b"x" * 10)
    assert big in await due_ids(engine, file_scan_max_bytes=10)
    assert big not in await due_ids(engine, file_scan_max_bytes=9)


async def test_the_backoff_doubles_from_twelve_minutes_and_caps_at_one_hour(engine) -> None:
    expectations = {1: 12, 2: 24, 3: 48, 4: 60, 9: 60, 5000: 60}
    seeded: dict[int, tuple[str, str]] = {}
    async with sessions(engine)() as session:
        for attempts in expectations:
            seeded[attempts] = await seed(session, age=10 * 60 * MIN)
    for attempts, (tenant, file_id) in seeded.items():
        await mark(
            engine, tenant, file_id, scan_attempts=attempts, scan_attempted_at=NOW - 30 * MIN
        )
    # 30 minutes after the last attempt: only the 12 and 24 minute files are owed.
    found = await due_ids(engine)
    assert {a for a, (_, f) in seeded.items() if f in found} == {1, 2}
    # 50 minutes: the 48 minute file joins; the capped ones are not yet due.
    for tenant, file_id in seeded.values():
        await mark(engine, tenant, file_id, scan_attempted_at=NOW - 50 * MIN)
    found = await due_ids(engine)
    assert {a for a, (_, f) in seeded.items() if f in found} == {1, 2, 3}
    # 61 minutes: everything is due, and an hour is as long as anyone ever waits.
    for tenant, file_id in seeded.values():
        await mark(
            engine,
            tenant,
            file_id,
            scan_attempted_at=NOW - timedelta(seconds=BACKOFF_CAP_SECONDS + 60),
        )
    found = await due_ids(engine)
    assert {f for _, f in seeded.values()} <= found


async def test_a_file_that_reached_the_threshold_is_still_reconciled(engine) -> None:
    async with sessions(engine)() as session:
        tenant, file_id = await seed(session, age=10 * 60 * MIN)
    await mark(
        engine,
        tenant,
        file_id,
        scan_attempts=12,
        scan_failure="scanner_unavailable",
        scan_attempted_at=NOW - 2 * 60 * MIN,
    )
    assert file_id in await due_ids(engine)
    await mark(engine, tenant, file_id, scan_attempts=32767, scan_attempted_at=NOW - 2 * 60 * MIN)
    assert file_id in await due_ids(engine), "the saturated counter does not abandon the file"


async def test_an_interrupted_file_is_selected_like_any_other_pending_file(engine) -> None:
    async with sessions(engine)() as session:
        tenant, file_id = await seed(session, age=10 * 60 * MIN)
    await mark(
        engine,
        tenant,
        file_id,
        scan_attempts=1,
        scan_failure="scan_interrupted",
        scan_attempted_at=NOW - 13 * MIN,
    )
    assert file_id in await due_ids(engine)


# ===================================================== pagination and tenant safety


async def test_pagination_is_complete_oldest_first_within_a_tenant_and_without_repeats(
    engine,
) -> None:
    async with sessions(engine)() as session:
        tenant, first = await seed(session, age=60 * MIN)
        ids = {first}
        for n in range(2, 8):
            ids.add((await seed(session, age=(60 + n) * MIN, tenant=tenant))[1])
    cursor, seen = FairCursor(), []
    while not cursor.exhausted:
        async with sessions(engine)() as session:
            page = await select_due(
                session,
                config=config(file_scan_sweep_batch_size=3, file_scan_sweep_max_batches=20),
                now=NOW,
                cursor=cursor,
            )
        assert len(page) <= 3
        if not page:
            break
        seen += page
    mine_ = [d for d in seen if d.tenant_id == tenant]
    assert {d.file_id for d in mine_} == ids and len({d.file_id for d in seen}) == len(seen)
    keys = [(d.due_at, d.file_id) for d in mine_]
    assert keys == sorted(keys), "a tenant's files come oldest due first"


async def test_the_selection_pairs_each_file_with_its_own_tenant_only(engine) -> None:
    async with sessions(engine)() as session:
        ta, fa = await seed(session, age=60 * MIN)
        tb, fb = await seed(session, age=60 * MIN)
    pairs = {(d.tenant_id, d.file_id) for d in await due_files(engine)}
    assert (ta, fa) in pairs and (tb, fb) in pairs
    assert (ta, fb) not in pairs and (tb, fa) not in pairs


async def test_without_the_provisioning_context_a_session_sees_only_its_own_tenant(engine) -> None:
    """The sweep's read needs `app.provisioning`; the tenant's own context cannot widen it."""
    async with sessions(engine)() as session:
        ta, fa = await seed(session, age=60 * MIN)
        tb, fb = await seed(session, age=60 * MIN)
    async with sessions(engine)() as session:
        await session.execute(AS_TENANT, {"tenant_id": ta})
        visible = {
            r[0]
            for r in (
                await session.execute(
                    text("select id::text from public.files where scan_status = 'pending'")
                )
            ).all()
        }
    assert fa in visible and fb not in visible
    async with sessions(engine)() as session:
        assert (
            await session.execute(text("select count(*) from public.files"))
        ).scalar_one() == 0, "no tenant and no provisioning context: nothing at all"
        await session.rollback()
        assert await session.execute(AS_PROVISIONING)


async def test_a_job_naming_another_tenants_file_finds_nothing_even_when_enqueued(engine) -> None:
    async with sessions(engine)() as session:
        ta, fa = await seed(session, age=60 * MIN)
        tb, _ = await seed(session, age=60 * MIN)
    async with sessions(engine)() as opened:
        result = await scan_file(
            opened,
            tenant_id=tb,
            file_id=fa,
            reader=ObjectReader(
                FakeObjectSource(stats=[identity(len(CSV))], body=CSV),
                chunk_bytes=64,
                clock=lambda: NOW,
            ),
            scanner=FakeScanner.candidate_clean(),
            max_attempts=12,
            now=NOW,
        )
    assert result.disposition is ScanDisposition.NOT_ELIGIBLE
    assert (await _row(engine, ta, fa))["scan_status"] == "pending"


# ===================================================== the whole loop, deterministic


async def run_scan(engine, tenant, file_id, scanner, *, at):
    async with sessions(engine)() as opened:
        return await scan_file(
            opened,
            tenant_id=tenant,
            file_id=file_id,
            reader=ObjectReader(
                FakeObjectSource(stats=[identity(len(CSV))], body=CSV),
                chunk_bytes=64,
                clock=lambda: at,
            ),
            scanner=scanner,
            max_attempts=3,
            now=at,
        )


async def sweep_once(engine, now, queue=None):
    queue = queue if queue is not None else RecordingJobQueue()

    async def forget(job_id: str) -> None:
        return None

    async with sessions(engine)() as session:
        report = await sweep(
            session,
            queue,
            forget,
            # Wide enough that rows left by other tests on a shared database cannot crowd this out.
            config=config(file_scan_sweep_batch_size=500, file_scan_sweep_max_batches=20),
            now=now,
        )
    return report, queue


def mine(queue, file_id):
    return [j for j in queue.jobs if j.payload.get("file_id") == file_id]


async def test_a_missed_upload_enqueue_is_recovered_and_the_file_ends_clean(engine) -> None:
    async with sessions(engine)() as session:
        tenant, file_id = await _seed(session, created_at=NOW - 30 * MIN)
    _, queue = await sweep_once(engine, NOW)
    (job,) = mine(queue, file_id)
    assert job.tenant_id == tenant and dict(job.payload) == {"file_id": file_id}
    result = await run_scan(engine, tenant, file_id, FakeScanner.candidate_clean(), at=NOW)
    assert result.disposition is ScanDisposition.CLEAN
    stored = await _row(engine, tenant, file_id)
    assert stored["scan_status"] == "clean" and stored["scan_attempts"] == 1
    _, again = await sweep_once(engine, NOW + 5 * MIN)
    assert mine(again, file_id) == [], "a released file is never selected again"


async def test_an_outage_leaves_the_file_pending_and_it_is_retried_after_the_backoff(
    engine,
) -> None:
    async with sessions(engine)() as session:
        tenant, file_id = await _seed(session, created_at=NOW - 30 * MIN)
    await run_scan(engine, tenant, file_id, FakeScanner.unavailable(), at=NOW)
    stored = await _row(engine, tenant, file_id)
    assert (stored["scan_status"], stored["scan_failure"]) == ("pending", "scanner_unavailable")

    _, early = await sweep_once(engine, NOW + 11 * MIN)
    assert mine(early, file_id) == [], "12 minutes after the first attempt, not before"
    _, due = await sweep_once(engine, NOW + 13 * MIN)
    assert len(mine(due, file_id)) == 1

    await run_scan(engine, tenant, file_id, FakeScanner.unavailable(), at=NOW + 13 * MIN)
    _, soon = await sweep_once(engine, NOW + 13 * MIN + 23 * MIN)
    assert mine(soon, file_id) == [], "the second wait is 24 minutes"
    _, later = await sweep_once(engine, NOW + 13 * MIN + 25 * MIN)
    assert len(mine(later, file_id)) == 1

    result = await run_scan(
        engine, tenant, file_id, FakeScanner.candidate_clean(), at=NOW + 40 * MIN
    )
    assert result.disposition is ScanDisposition.CLEAN


async def test_exhaustion_is_written_once_and_the_file_stays_reconcilable_and_releasable(
    engine,
) -> None:
    async with sessions(engine)() as session:
        tenant, file_id = await _seed(session, created_at=NOW - 30 * MIN)
    at = NOW
    for _ in range(5):  # the threshold in `run_scan` is 3
        await run_scan(engine, tenant, file_id, FakeScanner.unavailable(), at=at)
        at += 61 * MIN
    actions = [a for a, _, _ in await _audit(engine, tenant, file_id)]
    assert actions.count("storage.object.scan_exhausted") == 1
    assert actions.count("storage.object.scan_failed") == 1
    assert (await _row(engine, tenant, file_id))["scan_attempts"] == 5
    _, queue = await sweep_once(engine, at)
    assert len(mine(queue, file_id)) == 1, "beyond the threshold, still reconcilable"
    result = await run_scan(engine, tenant, file_id, FakeScanner.candidate_clean(), at=at)
    assert result.disposition is ScanDisposition.CLEAN


async def test_an_infected_file_is_never_selected_and_cannot_become_clean(engine) -> None:
    async with sessions(engine)() as session:
        tenant, file_id = await _seed(session, created_at=NOW - 30 * MIN)
    result = await run_scan(engine, tenant, file_id, FakeScanner.infected(), at=NOW)
    assert result.disposition is ScanDisposition.INFECTED
    _, queue = await sweep_once(engine, NOW + 2 * 60 * MIN)
    assert mine(queue, file_id) == []
    again = await run_scan(
        engine, tenant, file_id, FakeScanner.candidate_clean(), at=NOW + 2 * 60 * MIN
    )
    assert again.disposition is ScanDisposition.NOT_ELIGIBLE
    assert (await _row(engine, tenant, file_id))["scan_status"] == "infected"
    async with sessions(engine)() as session:  # even a direct attempt at the column is refused
        await session.execute(AS_TENANT, {"tenant_id": tenant})
        released = await session.execute(
            text(
                "update public.files set scan_status = 'clean' "
                "where id = cast(:f as uuid) and scan_status = 'pending'"
            ),
            {"f": file_id},
        )
        await session.commit()
    assert released.rowcount == 0


class Blocking:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def scan(self, source):
        self.started.set()
        await asyncio.Event().wait()

    async def ping(self) -> bool:
        return True


async def test_an_interrupted_run_persists_scan_interrupted_and_can_later_succeed(engine) -> None:
    async with sessions(engine)() as session:
        tenant, file_id = await _seed(session, created_at=NOW - 30 * MIN)
    scanner = Blocking()
    task = asyncio.ensure_future(run_scan(engine, tenant, file_id, scanner, at=NOW))
    await asyncio.wait_for(scanner.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    stored = await _row(engine, tenant, file_id)
    assert (stored["status"], stored["scan_status"]) == ("ready", "pending")
    assert (stored["scan_failure"], stored["scan_attempts"]) == ("scan_interrupted", 1)
    assert "storage.object.scan_failed" in [a for a, _, _ in await _audit(engine, tenant, file_id)]

    _, queue = await sweep_once(engine, NOW + 13 * MIN)
    assert len(mine(queue, file_id)) == 1
    result = await run_scan(
        engine, tenant, file_id, FakeScanner.candidate_clean(), at=NOW + 13 * MIN
    )
    assert result.disposition is ScanDisposition.CLEAN
    cleared = await _row(engine, tenant, file_id)
    assert cleared["scan_failure"] is None and cleared["scan_attempts"] == 2


async def test_the_thirteenth_failure_value_is_accepted_and_an_unknown_one_is_not(engine) -> None:
    async with sessions(engine)() as session:
        tenant, file_id = await _seed(session, created_at=NOW - 30 * MIN)
    await mark(engine, tenant, file_id, scan_failure="scan_interrupted")
    with pytest.raises(Exception, match="files_scan_failure_check"):
        await mark(engine, tenant, file_id, scan_failure="scan_abandoned")


# ================================================ the queue identity, on a real Redis


async def _redis():
    from arq.connections import RedisSettings, create_pool

    try:
        return await create_pool(RedisSettings.from_dsn(REDIS_URL))
    except Exception:  # pragma: no cover - environment dependent
        pytest.skip("no Redis reachable for the queue identity test")


async def test_a_second_enqueue_collapses_and_a_retained_result_would_block_a_re_enqueue() -> None:
    from koras_api.core.scan_jobs import FILE_SCAN, scan_idempotency_key, scan_payload

    redis = await _redis()
    tenant, file_id = str(uuid.uuid4()), str(uuid.uuid4())
    queue = ArqJobQueue(REDIS_URL)
    job_id = job_id_for(FILE_SCAN, tenant, scan_idempotency_key(file_id))
    try:
        kwargs = {
            "tenant_id": tenant,
            "payload": scan_payload(file_id),
            "idempotency_key": scan_idempotency_key(file_id),
        }
        first = await queue.enqueue(FILE_SCAN, **kwargs)
        second = await queue.enqueue(FILE_SCAN, **kwargs)
        assert not first.duplicate and second.duplicate and first.job_id == second.job_id == job_id

        # The job ran an hour ago and its result is retained: the queue still says "duplicate".
        await redis.delete("arq:job:" + job_id)
        await redis.set("arq:result:" + job_id, b"retained", ex=3600)
        assert (await queue.enqueue(FILE_SCAN, **kwargs)).duplicate
        # The sweep's cleanup is what lets a due file be queued again.
        await redis.delete("arq:result:" + job_id)
        assert not (await queue.enqueue(FILE_SCAN, **kwargs)).duplicate
    finally:
        await redis.delete("arq:job:" + job_id, "arq:result:" + job_id)
        await redis.zrem("arq:queue", job_id)
        await queue.aclose()
        await redis.aclose()


# ============================== tenant fairness and bounded reads 

ADMIN_URL = os.environ.get("MIGRATE_DATABASE_URL", "").replace(
    "postgresql://", "postgresql+asyncpg://", 1
)
_RUN_OFFSET_DAYS = 5000 + uuid.uuid4().int % 20000
_arenas = iter(range(10**6))


class Arena:
    """A stretch of time no other test (or earlier run) has put a file in.

    The database is shared, so a fairness test selects only its own rows by giving
    them creation times in a window of their own and a watermark at its start.
    """

    def __init__(self) -> None:
        self.now = NOW + timedelta(days=_RUN_OFFSET_DAYS + 3 * next(_arenas))
        self.watermark = self.now - timedelta(days=1)

    def cfg(self, **overrides) -> ScanSweepSettings:
        return config(file_scan_sweep_not_before=self.watermark, **overrides)

    async def seed(self, session, *, age: timedelta, tenant=None, **file) -> tuple[str, str]:
        return await _seed(session, created_at=self.now - age, tenant=tenant, **file)

    async def first_page(self, engine, cfg) -> list[DueFile]:
        async with sessions(engine)() as session:
            return await select_due(session, config=cfg, now=self.now, cursor=FairCursor())

    def params(self, **extra) -> dict:
        return {
            "now": self.now.replace(tzinfo=None),
            "not_before": self.watermark,
            "due_from": self.watermark.replace(tzinfo=None),
            "max_bytes": 10**9,
            "limit": 100_000,
            "start": "00000000-0000-0000-0000-000000000000",
            **extra,
        }


@pytest.fixture
def arena(monkeypatch) -> Arena:
    # The database is shared with every other test, so hundreds of unrelated tenants may hold
    # pending files; the walk's probe budget is widened so it reaches this test's own.
    from koras_worker.tasks import scan_sweep

    monkeypatch.setattr(scan_sweep, "MAX_TENANTS_PER_RUN", 100_000)
    return Arena()


async def test_a_tenant_with_many_older_due_files_does_not_crowd_out_other_tenants(
    engine, arena
) -> None:
    async with sessions(engine)() as session:
        poison, _ = await arena.seed(session, age=600 * MIN)
        for n in range(1, 40):
            await arena.seed(session, age=(600 + n) * MIN, tenant=poison)
        quiet, q1 = await arena.seed(session, age=30 * MIN)
        _, q2 = await arena.seed(session, age=29 * MIN, tenant=quiet)
        _, s1 = await arena.seed(session, age=25 * MIN)

    page = await arena.first_page(engine, arena.cfg(file_scan_sweep_batch_size=10))

    assert {q1, q2, s1} <= {d.file_id for d in page}, "the other tenants are in the first page"
    assert len(page) <= 10
    # Ten slots over three tenants is a share of three each: the poison tenant has no more
    # than its share of this page, and takes whatever the others leave on the next.
    assert sum(d.tenant_id == poison for d in page) == 3


async def test_only_final_key_rows_are_selected(engine, arena) -> None:
    """A row the runtime holds without an attempt must not be re-selected."""
    from koras_api.core.upload_window import final_key_for, incoming_key

    async with sessions(engine)() as session:
        tenant, legacy = await arena.seed(session, age=600 * MIN)
        _, incoming = await arena.seed(session, age=602 * MIN, tenant=tenant)
        _, final = await arena.seed(session, age=603 * MIN, tenant=tenant)
        _, other_tenants_key = await arena.seed(session, age=604 * MIN, tenant=tenant)
    await mark(engine, tenant, legacy, storage_key=f"tenants/{tenant}/imports/{legacy}/a.csv")
    await mark(
        engine,
        tenant,
        incoming,
        storage_key=incoming_key(tenant, "imports", incoming, str(uuid.uuid4()), "a.csv"),
    )
    await mark(
        engine,
        tenant,
        final,
        storage_key=final_key_for(
            incoming_key(tenant, "imports", final, str(uuid.uuid4()), "a.csv"), str(uuid.uuid4())
        ),
    )
    await mark(
        engine,
        tenant,
        other_tenants_key,
        storage_key=f"tenants/{tenant}/imports/{other_tenants_key}/final/x/y/a.csv",
    )

    selected = {
        d.file_id for d in await arena.first_page(engine, arena.cfg(file_scan_sweep_batch_size=50))
    }
    assert final in selected
    assert not ({legacy, incoming, other_tenants_key} & selected)


async def test_sixty_older_held_rows_do_not_starve_legitimate_pending_files(
    engine, arena
) -> None:
    from koras_api.core.upload_window import incoming_key

    async with sessions(engine)() as session:
        tenant, first = await arena.seed(session, age=2000 * MIN)
        held = {first}
        for n in range(1, 60):
            _, h = await arena.seed(session, age=(2000 + n) * MIN, tenant=tenant)
            held.add(h)
        _, legit1 = await arena.seed(session, age=30 * MIN, tenant=tenant)
        _, legit2 = await arena.seed(session, age=29 * MIN, tenant=tenant)
    for file_id in held:
        await mark(
            engine,
            tenant,
            file_id,
            storage_key=incoming_key(tenant, "imports", file_id, str(uuid.uuid4()), "a.csv"),
        )
    assert len(held) == 60
    # A page smaller than the held set: with the held rows selected (oldest due first) the
    # legitimate files would not appear in it at all.
    page = await arena.first_page(engine, arena.cfg(file_scan_sweep_batch_size=5))
    ids = {d.file_id for d in page}
    assert {legit1, legit2} <= ids and not (held & ids)


async def test_a_whole_run_reaches_every_tenant_and_spends_spare_capacity_on_the_busy_one(
    engine, arena
) -> None:
    async with sessions(engine)() as session:
        busy, _ = await arena.seed(session, age=600 * MIN)
        for n in range(1, 60):
            await arena.seed(session, age=(600 + n) * MIN, tenant=busy)
        _, o1 = await arena.seed(session, age=30 * MIN)
    found = await due_files(
        engine,
        arena.now,
        file_scan_sweep_not_before=arena.watermark,
        file_scan_sweep_batch_size=10,
        file_scan_sweep_max_batches=4,
    )
    assert o1 in {d.file_id for d in found}
    assert sum(d.tenant_id == busy for d in found) > 20, "the busy tenant uses the spare slots"
    assert len(found) <= 40, "never more than batch x pages in one run"


async def test_the_tenant_waiting_longest_goes_first_and_the_order_wraps_round(
    engine, arena
) -> None:
    from koras_worker.tasks import scan_sweep

    async with sessions(engine)() as session:
        ta, _ = await arena.seed(session, age=100 * MIN)
        tb, _ = await arena.seed(session, age=900 * MIN)  # the oldest due file overall
        tc, _ = await arena.seed(session, age=200 * MIN)
    async with sessions(engine)() as session:
        await session.execute(AS_PROVISIONING)
        order = await scan_sweep._fair_order(session, arena.params())
        await session.rollback()
    assert order[0] == tb, "its file has waited longest"
    ring = sorted([ta, tb, tc])
    start = ring.index(tb)
    assert order == ring[start:] + ring[:start], "tenant-id order, wrapping round"


async def test_served_files_stop_being_first_so_the_rotation_moves_on(engine, arena) -> None:
    async with sessions(engine)() as session:
        busy, _ = await arena.seed(session, age=900 * MIN)
        for n in range(1, 30):
            await arena.seed(session, age=(900 + n) * MIN, tenant=busy)
        _, o1 = await arena.seed(session, age=100 * MIN)
    cfg = arena.cfg(file_scan_sweep_batch_size=4)
    page = await arena.first_page(engine, cfg)
    assert o1 in {d.file_id for d in page}
    served = [d for d in page if d.tenant_id == busy]
    for d in served:  # they ran: their next attempt is a back-off away
        await mark(engine, busy, d.file_id, scan_attempts=1, scan_attempted_at=arena.now - 1 * MIN)
    again = await arena.first_page(engine, cfg)
    assert not {d.file_id for d in served} & {d.file_id for d in again}


async def test_exhausted_files_stay_in_the_fair_selection(engine, arena) -> None:
    async with sessions(engine)() as session:
        poison, p1 = await arena.seed(session, age=900 * MIN)
        _, q1 = await arena.seed(session, age=100 * MIN)
    await mark(
        engine,
        poison,
        p1,
        scan_attempts=40,
        scan_failure="scanner_unavailable",
        scan_attempted_at=arena.now - 2 * 60 * MIN,
    )
    page = await arena.first_page(engine, arena.cfg())
    assert {p1, q1} == {d.file_id for d in page}, "past the threshold, and still reconcilable"


# -------------------------------------------------- the reads are index reads, not sorts

needs_admin = pytest.mark.skipif(
    not ADMIN_URL, reason="plan checks need the admin connection (MIGRATE_DATABASE_URL)"
)


def _plan_nodes(plan: dict) -> list[dict]:
    nodes = [plan]
    for child in plan.get("Plans", []):
        nodes += _plan_nodes(child)
    return nodes


async def _explain_as_admin(
    sql: str, params: dict, *, keep: str, analyze: bool = False
) -> list[dict]:
    """The plan, with every index but `keep` removed (inside a transaction that is undone).

    A freshly loaded table has no statistics, and the planner may then prefer the other
    valid index -- the sweep has two -- for a handful of rows, depending on what ran before
    (it did: this assertion failed when the three scanner suites ran together). Taking every
    other index away, and forbidding the sequential scan and the sort, asks the question that
    matters and gives one answer whatever ran first: can the expected index deliver these
    rows in order, from the front? If a query and an index expression differed, a Sort or a
    sequential scan would be all that was left.
    """
    import json

    from sqlalchemy.ext.asyncio import create_async_engine

    admin = create_async_engine(ADMIN_URL)
    try:
        async with admin.connect() as conn:
            trans = await conn.begin()
            others = (
                await conn.execute(
                    text(
                        "select i.indexname from pg_indexes i where i.schemaname = 'public' "
                        "and i.tablename = 'files' and i.indexname <> :keep "
                        "and not exists (select 1 from pg_constraint c where c.conname = i.indexname)"
                    ),
                    {"keep": keep},
                )
            ).all()
            for (name,) in others:
                await conn.execute(text(f'drop index public."{name}"'))
            for setting in ("enable_seqscan", "enable_sort", "enable_incremental_sort"):
                await conn.execute(text(f"set local {setting} = off"))
            options = "analyze, format json" if analyze else "format json"
            raw = (await conn.execute(text(f"explain ({options}) {sql}"), params)).scalar()
            await trans.rollback()
    finally:
        await admin.dispose()
    doc = json.loads(raw) if isinstance(raw, str) else raw
    return _plan_nodes(doc[0]["Plan"])


@needs_admin
async def test_the_selection_reads_through_the_due_indexes_and_never_sorts(engine, arena) -> None:
    from koras_worker.tasks import scan_sweep

    async with sessions(engine)() as session:
        t, _ = await arena.seed(session, age=100 * MIN)
        await arena.seed(session, age=90 * MIN, tenant=t)
    page_params = arena.params(tenants=[t], after_due=[None], after_id=[None], share=5)
    cases = {
        "first owner": (scan_sweep._first_owner_sql(), "files_scan_due_idx", arena.params()),
        "tenant walk": (
            scan_sweep._tenants_sql(wrapped=False),
            "files_scan_due_tenant_idx",
            arena.params(),
        ),
        "wrapped walk": (
            scan_sweep._tenants_sql(wrapped=True),
            "files_scan_due_tenant_idx",
            arena.params(),
        ),
        "tenant page": (scan_sweep._page_sql(), "files_scan_due_tenant_idx", page_params),
    }
    for name, (sql, index, params) in cases.items():
        nodes = await _explain_as_admin(sql, params, keep=index)
        used = {n.get("Index Name") for n in nodes if n.get("Index Name")}
        kinds = {n["Node Type"] for n in nodes}
        assert index in used, f"{name}: expected {index}, plan used {used or kinds}"
        assert not any(
            n["Node Type"].startswith("Seq Scan") for n in nodes
        ), f"{name}: sequential scan of files"
        # The tenant walk puts the few tenants it found (at most `limit`) in order: the one
        # sort allowed, over the walk's own output and never over files. The first-owner and
        # page reads must not sort at all.
        if "walk" not in name:
            assert "Sort" not in kinds and "Incremental Sort" not in kinds, f"{name}: sorts"


@needs_admin
async def test_files_that_are_not_yet_due_are_never_read(engine, arena) -> None:
    """300 pending files that are all inside their back-off cost the first read nothing."""
    from koras_worker.tasks import scan_sweep

    async with sessions(engine)() as session:
        busy, _ = await arena.seed(session, age=900 * MIN)
        for n in range(1, 300):
            await arena.seed(session, age=(900 + n) * MIN, tenant=busy)
        due_tenant, due_file = await arena.seed(session, age=60 * MIN)
    # Every one of the busy tenant's files was attempted a minute ago: not due for 12 more.
    async with sessions(engine)() as session:
        await session.execute(AS_PROVISIONING)
        await session.execute(
            text(
                "update public.files set scan_attempts = 1, scan_attempted_at = :at "
                "where tenant_id = cast(:t as uuid)"
            ),
            {"t": busy, "at": arena.now - 1 * MIN},
        )
        await session.commit()
    nodes = await _explain_as_admin(
        scan_sweep._first_owner_sql(), arena.params(), keep="files_scan_due_idx", analyze=True
    )
    scans = [n for n in nodes if n["Node Type"].startswith("Index")]
    assert scans and {n["Index Name"] for n in scans} == {"files_scan_due_idx"}
    visited = max(n.get("Actual Rows", 0) + n.get("Rows Removed by Filter", 0) for n in scans)
    assert visited <= 5, f"read {visited} index entries to find the first due file"
    found = await arena.first_page(engine, arena.cfg(file_scan_sweep_batch_size=10))
    assert [d.file_id for d in found] == [due_file]
    assert due_tenant == found[0].tenant_id


# ---------------------- a specific failure outlives a cancellation, on a real database


async def test_an_interrupted_attempt_does_not_replace_the_recorded_specific_failure(
    engine,
) -> None:
    async with sessions(engine)() as session:
        tenant, file_id = await _seed(session, created_at=NOW - 30 * MIN)
    await run_scan(engine, tenant, file_id, FakeScanner.unavailable(), at=NOW)
    scanner = Blocking()
    task = asyncio.ensure_future(run_scan(engine, tenant, file_id, scanner, at=NOW + 13 * MIN))
    await asyncio.wait_for(scanner.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    stored = await _row(engine, tenant, file_id)
    assert (stored["scan_status"], stored["scan_failure"]) == ("pending", "scanner_unavailable")
    assert stored["scan_attempts"] == 2, "the interrupted attempt still counts"
    actions = [a for a, _, _ in await _audit(engine, tenant, file_id)]
    assert actions.count("storage.object.scan_failed") == 1


async def test_a_failure_written_by_another_step_mid_attempt_survives_the_cancellation(
    engine,
) -> None:
    async with sessions(engine)() as session:
        tenant, file_id = await _seed(session, created_at=NOW - 30 * MIN)
    scanner = Blocking()
    task = asyncio.ensure_future(run_scan(engine, tenant, file_id, scanner, at=NOW))
    await asyncio.wait_for(scanner.started.wait(), 5)
    await mark(engine, tenant, file_id, scan_failure="integrity_mismatch")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await _row(engine, tenant, file_id))["scan_failure"] == "integrity_mismatch"
