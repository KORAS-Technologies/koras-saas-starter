# ruff: noqa: ANN001, ANN002, ANN003, ANN201, ANN202, ANN204, ANN401, E501, S101, S608
"""One tenant's files cannot use every slot of a sweep run.

The selection's SQL (the index reads, the immutable expression, forced RLS) is proved
against PostgreSQL in `tests/integration/test_scan_sweep_real.py`. Here the *algorithm*
is proved with an in-memory table that answers the sweep's three queries the way the
SQL does: who goes first, which tenants, and each tenant's next due files. What is
proved: a tenant with hundreds of older due files does not crowd out the others;
spare capacity goes to whoever still has work; the rotation is deterministic and
stateless; every file is eventually served; and the work per run stays bounded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

pytest.importorskip("koras_worker")
from koras_queue import Enqueued, RecordingJobQueue  # noqa: E402
from koras_worker.tasks import scan_sweep  # noqa: E402
from koras_worker.tasks.scan_sweep import (  # noqa: E402
    FairCursor,
    ScanSweepSettings,
    select_due,
    sweep,
)

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
NAIVE_NOW = NOW.replace(tzinfo=None)
WATERMARK = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)


def tenant(n: int) -> str:
    return f"{n:08x}-0000-4000-8000-000000000000"


def file_id(tenant_n: int, n: int) -> str:
    return f"{tenant_n:08x}-0000-4000-8000-{n:012d}"


@dataclass
class Row:
    id: str
    tenant_id: str
    due: datetime  # naive UTC, as the SQL computes it


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar(self) -> Any:
        return self._rows[0][0] if self._rows else None

    def all(self) -> list[Any]:
        return self._rows

    def mappings(self) -> _Result:
        return self


class MemoryTable:
    """The pending, ready files, answering the sweep's statements as the SQL does."""

    def __init__(self, rows: list[Row]) -> None:
        self.rows = rows
        self.statements: list[str] = []
        self.rolled_back = 0

    def _due(self, now: datetime) -> list[Row]:
        return sorted((r for r in self.rows if r.due <= now), key=lambda r: (r.due, r.id))

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Result:
        sql = str(statement)
        params = params or {}
        self.statements.append(sql)
        if sql.startswith("select set_config"):
            return _Result([])
        now = params["now"]
        if sql == scan_sweep._first_owner_sql():
            due = self._due(now)
            return _Result([(due[0].tenant_id,)] if due else [])
        if sql in (scan_sweep._tenants_sql(wrapped=False), scan_sweep._tenants_sql(wrapped=True)):
            wrapped = sql == scan_sweep._tenants_sql(wrapped=True)
            tenants = sorted({r.tenant_id for r in self._due(now)})
            start = params["start"]
            pick = [t for t in tenants if (t < start if wrapped else t >= start)]
            return _Result([(t,) for t in pick[: params["limit"]]])
        if sql == scan_sweep._page_sql():
            out: list[dict[str, Any]] = []
            for t, after_due, after_id in zip(
                params["tenants"], params["after_due"], params["after_id"], strict=True
            ):
                mine = [r for r in self._due(now) if r.tenant_id == t]
                if after_due is not None:
                    mine = [r for r in mine if (r.due, r.id) > (after_due, after_id)]
                out += [
                    {"id": r.id, "tenant_id": r.tenant_id, "due_at": r.due}
                    for r in mine[: params["share"]]
                ]
            return _Result(out)
        raise AssertionError(f"unexpected statement: {sql[:80]}")

    async def rollback(self) -> None:
        self.rolled_back += 1


def config(**overrides: Any) -> ScanSweepSettings:
    values: dict[str, Any] = {
        "file_scan_sweep_not_before": WATERMARK,
        "file_scan_backend": "clamd",
    }
    values.update(overrides)
    return ScanSweepSettings(**values)


def rows_for(tenant_n: int, count: int, *, oldest_minutes: int = 600) -> list[Row]:
    """`count` due files for one tenant, spaced a second apart, the first `oldest_minutes` old."""
    start = NAIVE_NOW - timedelta(minutes=oldest_minutes)
    return [
        Row(file_id(tenant_n, n), tenant(tenant_n), start + timedelta(seconds=n))
        for n in range(count)
    ]


class Live(RecordingJobQueue):
    async def enqueue(self, task, **kwargs):
        result = await super().enqueue(task, **kwargs)
        return Enqueued(task=result.task, job_id=result.job_id)


async def forget(job_id: str) -> None:
    return None


async def pages_of(table: MemoryTable, cfg: ScanSweepSettings) -> list[list[Any]]:
    """Every page one run would read, without enqueueing."""
    cursor, out = FairCursor(), []
    for _ in range(cfg.file_scan_sweep_max_batches):
        page = await select_due(table, config=cfg, now=NOW, cursor=cursor)
        if not page:
            break
        out.append(page)
        if cursor.exhausted:
            break
    return out


# ---------------------------------------------------------------- the poison tenant


async def test_a_tenant_with_hundreds_of_older_due_files_does_not_crowd_out_the_others() -> None:
    poison = rows_for(1, 400, oldest_minutes=900)  # many, and older than anyone's
    others = rows_for(2, 3, oldest_minutes=30) + rows_for(3, 2, oldest_minutes=20)
    table = MemoryTable(poison + others)
    cfg = config()  # 50 per page, 4 pages

    pages = await pages_of(table, cfg)
    chosen = {f.file_id for page in pages for f in page}

    assert all(r.id in chosen for r in others), "every other tenant's due file is in the run"
    assert sum(1 for r in poison if r.id in chosen) <= 50 * 4 - len(others)
    # And in the first page already: the poison tenant is not allowed to use it up.
    first = {f.file_id for f in pages[0]}
    assert all(r.id in first for r in others)


async def test_the_poison_tenant_alone_still_gets_the_whole_run() -> None:
    table = MemoryTable(rows_for(1, 500))
    pages = await pages_of(table, config())
    assert [len(p) for p in pages] == [50, 50, 50, 50], "spare capacity is not wasted"


async def test_a_page_is_shared_evenly_and_a_tenant_that_runs_dry_gives_its_share_back() -> None:
    table = MemoryTable(rows_for(1, 100) + rows_for(2, 100) + rows_for(3, 1))
    pages = await pages_of(table, config(file_scan_sweep_batch_size=10))

    def per_tenant(page):
        counts: dict[str, int] = {}
        for f in page:
            counts[f.tenant_id] = counts.get(f.tenant_id, 0) + 1
        return counts

    # share = 10 // 3 = 3: tenant 3 has one and closes; the others take 3 each.
    assert per_tenant(pages[0]) == {tenant(1): 3, tenant(2): 3, tenant(3): 1}
    # then the two still open split the page: 10 // 2 = 5 each.
    assert per_tenant(pages[1]) == {tenant(1): 5, tenant(2): 5}
    assert all(len(p) <= 10 for p in pages)


async def test_a_page_is_enqueued_round_robin_across_tenants() -> None:
    table = MemoryTable(rows_for(1, 9) + rows_for(2, 9) + rows_for(3, 9))
    (page, *_) = await pages_of(table, config(file_scan_sweep_batch_size=9))
    owners = [f.tenant_id for f in page]
    assert owners[:3] != [owners[0]] * 3, "not one tenant's files after another"
    assert sorted(set(owners[:3])) == sorted({tenant(1), tenant(2), tenant(3)})


async def test_within_a_tenant_the_oldest_due_file_goes_first_and_no_file_repeats() -> None:
    table = MemoryTable(rows_for(1, 30))
    pages = await pages_of(table, config(file_scan_sweep_batch_size=10, file_scan_sweep_max_batches=3))
    ids = [f.file_id for p in pages for f in p]
    assert ids == [file_id(1, n) for n in range(30)]
    assert len(ids) == len(set(ids))


# --------------------------------------------------------------------- bounded work


async def test_one_run_never_selects_more_than_batch_times_pages() -> None:
    tenants_n = 300
    table = MemoryTable([r for n in range(1, tenants_n + 1) for r in rows_for(n, 5)])
    cfg = config(file_scan_sweep_batch_size=20, file_scan_sweep_max_batches=3)
    pages = await pages_of(table, cfg)
    assert sum(len(p) for p in pages) <= 20 * 3
    assert all(len(p) <= 20 for p in pages)


async def test_more_tenants_than_a_page_holds_are_served_over_the_pages_of_the_run() -> None:
    table = MemoryTable([r for n in range(1, 121) for r in rows_for(n, 1)])
    cfg = config(file_scan_sweep_batch_size=50, file_scan_sweep_max_batches=4)
    pages = await pages_of(table, cfg)
    served = {f.tenant_id for p in pages for f in p}
    assert len(served) == 120, "50 + 50 + 20 tenants, one file each"


async def test_tenant_discovery_is_bounded_by_the_limit_passed_to_the_database() -> None:
    table = MemoryTable([r for n in range(1, 40) for r in rows_for(n, 2)])
    cfg = config(file_scan_sweep_batch_size=5, file_scan_sweep_max_batches=2)
    seen_limits: list[int] = []
    real = table.execute

    async def spy(statement, params=None):
        if params and "limit" in params:
            seen_limits.append(params["limit"])
        return await real(statement, params)

    table.execute = spy  # type: ignore[method-assign]
    await pages_of(table, cfg)
    assert seen_limits and max(seen_limits) <= scan_sweep.MAX_TENANTS_PER_RUN


# -------------------------------------------------- deterministic, stateless rotation


async def test_the_tenant_with_the_oldest_due_file_goes_first_and_the_ring_wraps() -> None:
    # tenant 5 owns the oldest file; ids 1..4 come after the wrap.
    rows = [r for n in (1, 2, 3, 4, 6, 7) for r in rows_for(n, 1, oldest_minutes=100)]
    rows += rows_for(5, 1, oldest_minutes=500)
    table = MemoryTable(rows)
    cursor = FairCursor()
    await select_due(table, config=config(), now=NOW, cursor=cursor)
    assert cursor.seen == {tenant(n) for n in range(1, 8)}
    order = await scan_sweep._fair_order(table, {"now": NAIVE_NOW, "not_before": WATERMARK, "max_bytes": 1, "limit": 100})
    assert order == [tenant(n) for n in (5, 6, 7, 1, 2, 3, 4)]


async def test_the_same_data_gives_the_same_selection() -> None:
    rows = rows_for(1, 80) + rows_for(2, 7) + rows_for(3, 130)
    first = await pages_of(MemoryTable(list(rows)), config())
    second = await pages_of(MemoryTable(list(rows)), config())
    assert [[f.file_id for f in p] for p in first] == [[f.file_id for f in p] for p in second]


async def test_every_file_is_eventually_served_even_behind_a_much_larger_tenant() -> None:
    """Runs repeat; a file that was enqueued and has run is next due 12 minutes later."""
    table = MemoryTable(rows_for(1, 600, oldest_minutes=900) + rows_for(2, 4, oldest_minutes=10))
    served: set[str] = set()
    clock = NOW
    for _ in range(60):  # five hours of five-minute runs
        cursor = FairCursor()
        for _ in range(4):
            page = await select_due(table, config=config(), now=clock, cursor=cursor)
            if not page:
                break
            for f in page:
                served.add(f.file_id)
                row = next(r for r in table.rows if r.id == f.file_id)
                row.due = clock.replace(tzinfo=None) + timedelta(minutes=12)  # it ran
            if cursor.exhausted:
                break
        clock += timedelta(minutes=5)
    assert {r.id for r in table.rows} <= served


# ------------------------------------------------------------- isolation and the run


async def test_a_file_is_only_ever_paired_with_its_own_tenant() -> None:
    rows = rows_for(1, 6) + rows_for(2, 6)
    pages = await pages_of(MemoryTable(rows), config())
    owner = {r.id: r.tenant_id for r in rows}
    assert all(owner[f.file_id] == f.tenant_id for p in pages for f in p)


async def test_the_sweep_run_reports_how_many_tenants_took_part() -> None:
    table = MemoryTable(rows_for(1, 30) + rows_for(2, 2) + rows_for(3, 2))
    report = await sweep(table, Live(), forget, config=config(), now=NOW)
    assert (report.state, report.tenants) == ("ran", 3)
    assert report.selected == report.enqueued


async def test_a_run_with_nothing_due_reads_and_enqueues_nothing() -> None:
    table = MemoryTable([Row(file_id(1, 1), tenant(1), NAIVE_NOW + timedelta(minutes=5))])
    queue = Live()
    report = await sweep(table, queue, forget, config=config(), now=NOW)
    assert (report.state, report.selected, report.pages, report.tenants) == ("ran", 0, 0, 0)
    assert queue.jobs == []


async def test_every_read_transaction_is_rolled_back() -> None:
    table = MemoryTable(rows_for(1, 3))
    await sweep(table, Live(), forget, config=config(), now=NOW)
    assert table.rolled_back >= 1


# --------------------------------------------- no scanner activated: nothing is enqueued


async def test_the_sweep_enqueues_nothing_when_no_scanner_is_configured() -> None:
    table = MemoryTable(rows_for(1, 5))
    queue = Live()
    report = await sweep(table, queue, forget, config=config(file_scan_backend="none"), now=NOW)
    assert report.state == "scanner_inactive" and queue.jobs == []
    assert table.statements == [], "it did not even read"


async def test_a_group_of_tenants_that_has_nothing_left_does_not_end_the_run_early() -> None:
    """Their files were served after they were listed: the next group is read in the same call."""
    table = MemoryTable(rows_for(1, 1) + rows_for(2, 1) + rows_for(3, 1))
    cfg = config(file_scan_sweep_batch_size=1, file_scan_sweep_max_batches=4)
    cursor = FairCursor()
    first = await select_due(table, config=cfg, now=NOW, cursor=cursor)
    assert [f.tenant_id for f in first] == [tenant(1)]
    table.rows = [r for r in table.rows if r.tenant_id != tenant(2)]  # tenant 2 ran meanwhile
    second = await select_due(table, config=cfg, now=NOW, cursor=cursor)
    assert [f.tenant_id for f in second] == [tenant(3)], "tenant 2 came up empty; 3 is next"
