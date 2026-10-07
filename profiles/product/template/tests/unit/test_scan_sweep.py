# ruff: noqa: ANN001, ANN002, ANN003, ANN201, ANN202, ANN204, ANN401, E501, S101, S608
"""The scan reconciliation sweep's logic, and its boundaries (`secure_files`).

The selection SQL (what is due, the watermark, the ceiling, the back-off, tenant
isolation, pagination) needs a server and is proved in
`tests/integration/test_scan_sweep_real.py`. Here: that it is always on and its watermark
only narrows, the bounded paging, what is enqueued and under what identity, that a stale retained
result is dropped before the enqueue and nothing else is, that one bad file does
not stop a page, and that the module writes nothing.
"""

from __future__ import annotations

import ast
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

pytest.importorskip("koras_worker")
from koras_api.core.scan_jobs import FILE_SCAN  # noqa: E402
from koras_queue import Enqueued, RecordingJobQueue, job_id_for  # noqa: E402
from koras_worker.tasks import scan_sweep  # noqa: E402
from koras_worker.tasks.scan_sweep import (  # noqa: E402
    BACKOFF_CAP_SECONDS,
    BACKOFF_FIRST_SECONDS,
    DueFile,
    ScanSweepSettings,
    backoff_seconds,
    sweep,
)

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
WATERMARK = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"
SWEEP_SOURCE = Path(scan_sweep.__file__)


def fid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def settings_for(**overrides: Any) -> ScanSweepSettings:
    values: dict[str, Any] = {
        "file_scan_sweep_not_before": WATERMARK,
        "file_scan_backend": "clamd",
    }
    values.update(overrides)
    return ScanSweepSettings(**values)


class LiveRecorder(RecordingJobQueue):
    """Records like the stock queue but answers as a real one (not `simulated`)."""

    async def enqueue(self, task, **kwargs):
        result = await super().enqueue(task, **kwargs)
        return Enqueued(task=result.task, job_id=result.job_id)


class Pages:
    """Scripted pages, in place of the SQL. The last one closes the cursor, as the SQL does."""

    def __init__(self, files: list[DueFile], batch: int) -> None:
        self.chunks = [files[i : i + batch] for i in range(0, len(files), batch)]
        self.calls = 0

    async def __call__(self, session, *, config, now, cursor):
        self.calls += 1
        if self.calls > len(self.chunks):
            cursor.open = []
            return []
        if cursor.open is None:
            cursor.open = ["tenants"]
        if self.calls == len(self.chunks):
            cursor.open = []
        return self.chunks[self.calls - 1]


class Session:
    rolled_back = 0

    async def execute(self, *args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("the sweep logic must not touch the session itself")

    async def rollback(self) -> None:
        self.rolled_back += 1


def due(n: int, tenant: str = TENANT_A) -> DueFile:
    return DueFile(fid(n), tenant, NOW - timedelta(minutes=n))


class Forgotten(list):
    async def __call__(self, job_id: str) -> None:
        self.append(job_id)


async def run(monkeypatch, files, *, queue=None, forget=None, **overrides):
    config = settings_for(**overrides)
    pages = Pages(files, config.file_scan_sweep_batch_size)
    monkeypatch.setattr(scan_sweep, "select_due", pages)
    queue = queue if queue is not None else LiveRecorder()
    forget = forget if forget is not None else Forgotten()
    report = await sweep(Session(), queue, forget, config=config, now=NOW)
    return report, queue, forget, pages


# ------------------------------------------------------- always on, and only ever narrowed


def test_the_sweep_has_no_enable_switch_and_the_watermark_is_optional(monkeypatch) -> None:
    for name in (
        "FILE_SCAN_SWEEP_NOT_BEFORE",
        "FILE_SCAN_SWEEP_BATCH_SIZE",
        "FILE_SCAN_SWEEP_MAX_BATCHES",
    ):
        monkeypatch.delenv(name, raising=False)
    config = ScanSweepSettings(_env_file=None)
    assert config.file_scan_sweep_not_before is None
    assert not [f for f in ScanSweepSettings.model_fields if "enabled" in f or "environment" in f]


def test_a_cleared_watermark_reads_as_absent(monkeypatch) -> None:
    monkeypatch.setenv("FILE_SCAN_SWEEP_NOT_BEFORE", "")
    assert ScanSweepSettings(_env_file=None).file_scan_sweep_not_before is None


async def test_without_a_watermark_the_sweep_selects_from_the_beginning(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    class Recording(Pages):
        async def __call__(self, session, *, config, now, cursor):
            seen["config"] = config
            return await super().__call__(session, config=config, now=now, cursor=cursor)

    config = settings_for(file_scan_sweep_not_before=None)
    pages = Recording([due(1)], config.file_scan_sweep_batch_size)
    monkeypatch.setattr(scan_sweep, "select_due", pages)
    report = await sweep(Session(), LiveRecorder(), Forgotten(), config=config, now=NOW)
    assert (report.state, report.selected, report.enqueued) == ("ran", 1, 1)
    assert seen["config"].file_scan_sweep_not_before is None
    assert scan_sweep._BEGINNING == datetime(1970, 1, 1, tzinfo=UTC)


async def test_with_backend_none_the_sweep_selects_and_enqueues_nothing(monkeypatch) -> None:
    report, queue, forget, pages = await run(monkeypatch, [due(1)], file_scan_backend="none")
    assert report.state == "scanner_inactive"
    assert queue.jobs == [] and pages.calls == 0 and forget == []


async def test_the_cron_entry_skips_loudly_with_no_database(monkeypatch, caplog) -> None:
    caplog.set_level("ERROR")
    monkeypatch.setattr(scan_sweep.settings, "database_url", "")
    result = await scan_sweep.sweep_pending_scans({})
    assert result == {"state": "skipped", "reason": "no database"}
    assert "DATABASE_URL" in caplog.text


def test_the_sweep_is_one_cron_entry_every_five_minutes_in_the_worker() -> None:
    worker = Path(scan_sweep.__file__).parents[1] / "worker.py"
    text = worker.read_text(encoding="utf-8")
    assert text.count("cron(sweep_pending_scans") == 1
    assert "minute=set(range(0, 60, SWEEP_INTERVAL_MINUTES))" in text
    assert scan_sweep.SWEEP_INTERVAL_MINUTES == 5


# ----------------------------------------------------------------- what is enqueued


async def test_each_due_file_is_enqueued_as_the_existing_task_under_its_own_tenant(
    monkeypatch,
) -> None:
    files = [due(1, TENANT_A), due(2, TENANT_B)]
    report, queue, _, _ = await run(monkeypatch, files)
    assert (report.state, report.selected, report.enqueued) == ("ran", 2, 2)
    assert [(j.task, j.tenant_id, dict(j.payload), j.idempotency_key) for j in queue.jobs] == [
        ("file.scan", TENANT_A, {"file_id": fid(1)}, f"scan:{fid(1)}"),
        ("file.scan", TENANT_B, {"file_id": fid(2)}, f"scan:{fid(2)}"),
    ]


async def test_a_job_never_carries_anything_but_the_file_id(monkeypatch) -> None:
    _, queue, _, _ = await run(monkeypatch, [due(1)])
    assert set(queue.jobs[0].payload) == {"file_id"}
    assert "http" not in str(queue.jobs[0].as_dict()).lower()


async def test_a_stale_retained_result_is_dropped_for_that_job_id_before_the_enqueue(
    monkeypatch,
) -> None:
    order: list[str] = []

    class Queue(LiveRecorder):
        async def enqueue(self, task, **kwargs):
            order.append("enqueue")
            return await super().enqueue(task, **kwargs)

    class Forget(Forgotten):
        async def __call__(self, job_id):
            order.append("forget")
            await super().__call__(job_id)

    _, _, forgotten, _ = await run(monkeypatch, [due(7, TENANT_B)], queue=Queue(), forget=Forget())
    assert order == ["forget", "enqueue"]
    assert forgotten == [job_id_for(FILE_SCAN, TENANT_B, f"scan:{fid(7)}")]


async def test_a_job_the_queue_already_holds_collapses_and_is_counted_as_a_duplicate(
    monkeypatch,
) -> None:
    class Held(RecordingJobQueue):
        async def enqueue(self, task, **kwargs):
            return Enqueued(task=task.name, job_id="x", duplicate=True)

    report, _, _, _ = await run(monkeypatch, [due(1), due(2)], queue=Held())
    assert (report.selected, report.enqueued, report.duplicate) == (2, 0, 2)


async def test_a_sweep_run_twice_enqueues_the_same_identity_both_times(monkeypatch) -> None:
    _, queue, _, _ = await run(monkeypatch, [due(1)])
    await run(monkeypatch, [due(1)], queue=queue)
    assert len({(j.tenant_id, j.idempotency_key) for j in queue.jobs}) == 1


async def test_one_file_failing_to_enqueue_does_not_stop_the_page(monkeypatch) -> None:
    class Flaky(LiveRecorder):
        async def enqueue(self, task, **kwargs):
            if kwargs["payload"]["file_id"] == fid(1):
                raise ConnectionError("redis")
            return await super().enqueue(task, **kwargs)

    report, queue, _, _ = await run(monkeypatch, [due(1), due(2), due(3)], queue=Flaky())
    assert (report.selected, report.enqueued, report.failed) == (3, 2, 1)
    assert [j.payload["file_id"] for j in queue.jobs] == [fid(2), fid(3)]


async def test_a_failing_result_cleanup_counts_as_a_failure_and_enqueues_nothing_for_that_file(
    monkeypatch,
) -> None:
    class Broken(Forgotten):
        async def __call__(self, job_id):
            raise ConnectionError("redis")

    report, queue, _, _ = await run(monkeypatch, [due(1)], forget=Broken())
    assert (report.failed, report.enqueued) == (1, 0) and queue.jobs == []


# --------------------------------------------------------- bounded, deterministic paging


async def test_paging_is_bounded_by_batch_size_and_by_pages_per_run(monkeypatch) -> None:
    files = [due(n) for n in range(1, 11)]
    report, queue, _, pages = await run(
        monkeypatch, files, file_scan_sweep_batch_size=3, file_scan_sweep_max_batches=2
    )
    assert (report.pages, report.selected) == (2, 6)
    assert [j.payload["file_id"] for j in queue.jobs] == [fid(n) for n in range(1, 7)]
    assert pages.calls == 2, "no third page is asked for"


async def test_a_short_page_ends_the_run_without_asking_again(monkeypatch) -> None:
    report, _, _, pages = await run(
        monkeypatch, [due(1), due(2)], file_scan_sweep_batch_size=5, file_scan_sweep_max_batches=4
    )
    assert report.pages == 1 and pages.calls == 1


async def test_an_empty_selection_is_a_quiet_run(monkeypatch) -> None:
    report, queue, _, _ = await run(monkeypatch, [])
    assert (report.state, report.selected, report.pages) == ("ran", 0, 0) and queue.jobs == []


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("file_scan_sweep_batch_size", 0),
        ("file_scan_sweep_batch_size", 501),
        ("file_scan_sweep_max_batches", 0),
        ("file_scan_sweep_max_batches", 21),
    ],
)
def test_the_bounds_cannot_be_lifted_past_their_ceiling(name: str, value: int) -> None:
    with pytest.raises(ValueError):
        settings_for(**{name: value})


def test_the_most_one_run_can_enqueue_is_bounded() -> None:
    config = settings_for()
    assert config.file_scan_sweep_batch_size * config.file_scan_sweep_max_batches <= 500 * 20
    assert (config.file_scan_sweep_batch_size, config.file_scan_sweep_max_batches) == (50, 4)


# ---------------------------------------------------------------- the back-off schedule


def test_backoff_doubles_from_twelve_minutes_and_caps_at_one_hour() -> None:
    assert [backoff_seconds(n) for n in (1, 2, 3, 4, 5, 6, 12, 40, 32767)] == [
        720,
        1440,
        2880,
        3600,
        3600,
        3600,
        3600,
        3600,
        3600,
    ]
    assert BACKOFF_FIRST_SECONDS == 720 and BACKOFF_CAP_SECONDS == 3600


def test_the_first_retry_is_after_the_queue_timeout_so_a_retry_never_overlaps_a_run() -> None:
    from koras_api.core.scan_jobs import SCAN_TIMEOUT_SECONDS

    assert BACKOFF_FIRST_SECONDS > SCAN_TIMEOUT_SECONDS


def test_backoff_never_decreases_and_never_stops() -> None:
    values = [backoff_seconds(n) for n in range(0, 200)]
    assert values == sorted(values) and max(values) == BACKOFF_CAP_SECONDS and min(values) > 0


# ------------------------------------------------------- the sweep writes nothing


def _statements() -> list[str]:
    """Every SQL statement the sweep can send, built exactly as it sends them."""
    return [
        str(scan_sweep._PROVISIONING),
        scan_sweep._first_owner_sql(),
        scan_sweep._tenants_sql(wrapped=False),
        scan_sweep._tenants_sql(wrapped=True),
        scan_sweep._page_sql(),
    ]


def test_the_sweep_holds_no_write_and_every_statement_is_a_read_by_identifier() -> None:
    statements = _statements()
    assert len(statements) == 5
    for sql in statements:
        assert re.match(r"\s*(select|with recursive)\b", sql, re.I), sql
        assert not re.search(r"\b(update|insert|delete|truncate|alter|drop)\b", sql, re.I), sql
    # Identifiers and the due time are all that leaves the database. The page query is the
    # only one that returns files, and its select list is checked column by column.
    page = scan_sweep._page_sql()
    selected = page.split(" from unnest")[0]
    assert selected == "select f.id::text as id, f.tenant_id::text as tenant_id, f.due_at as due_at"
    for sql in statements:
        # `storage_key` is named only inside the final-shape predicate; it is never returned.
        assert sql.count("storage_key") == sql.count("storage_key ~ ")
        for column in ("checksum", "scan_failure", "content_type", "uploaded_by"):
            assert column not in sql, column
    source = SWEEP_SOURCE.read_text(encoding="utf-8")
    assert not re.search(r"session\.(add|merge|delete|commit|flush)\b", source)


def test_the_sweep_source_contains_no_write_statement_literal() -> None:
    tree = ast.parse(SWEEP_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not re.match(r"\s*(update|insert|delete)\b", node.value, re.I), node.value


def test_the_sweep_does_not_import_the_transitions_or_the_scanner() -> None:
    tree = ast.parse(SWEEP_SOURCE.read_text(encoding="utf-8"))
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not {m for m in imported if "transition" in m or "clamd" in m or "runtime" in m}


# ------------------------------------------------------------------ hardening


@pytest.mark.parametrize(
    "bad", ["0", "2026-10-05", "2026-10-05T00:00:00", "yesterday", "1790000000"]
)
def test_the_watermark_must_be_an_rfc3339_instant_with_an_offset(bad: str) -> None:
    with pytest.raises(ValueError):
        ScanSweepSettings(file_scan_sweep_not_before=bad)


def test_a_naive_datetime_watermark_is_refused() -> None:
    with pytest.raises(ValueError):
        settings_for(file_scan_sweep_not_before=datetime(2026, 10, 5))


@pytest.mark.parametrize("good", ["2026-10-05T00:00:00Z", "2026-10-05T02:00:00+02:00"])
def test_an_explicit_instant_is_accepted_and_aware(good: str) -> None:
    parsed = ScanSweepSettings(file_scan_sweep_not_before=good).file_scan_sweep_not_before
    assert parsed is not None and parsed.utcoffset() is not None


async def test_a_queue_that_only_records_is_not_counted_as_enqueued(monkeypatch) -> None:
    class Simulated(RecordingJobQueue):
        pass  # the stock recording queue answers simulated=True

    report, _, _, _ = await run(monkeypatch, [due(1)], queue=Simulated())
    assert (report.enqueued, report.failed) == (0, 1)


async def test_a_malformed_bound_refuses_and_names_the_setting(monkeypatch, caplog) -> None:
    caplog.set_level("ERROR")
    monkeypatch.setenv("FILE_SCAN_SWEEP_NOT_BEFORE", "0")
    assert await scan_sweep.sweep_pending_scans({}) == {"state": "invalid_config"}
    assert "file_scan_sweep_not_before" in caplog.text and "1970" not in caplog.text


# ------------------------------------- the indexes and the query use one expression

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "00041_file_scan_due_indexes.sql"


def _squash(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip().lower()


def test_the_index_expression_in_the_migration_is_the_one_the_sweep_queries_with() -> None:
    from koras_api.core.upload_window import SCAN_READ_DELAY_SECONDS

    unattempted = SCAN_READ_DELAY_SECONDS + scan_sweep._UNATTEMPTED_GRACE_SECONDS
    assert unattempted == 1260, "changing the window or the grace is a new migration"
    expression = _squash(scan_sweep.due_expression(unattempted))
    migration = _squash(MIGRATION.read_text(encoding="utf-8"))
    assert migration.count(expression) == 2, "both indexes carry exactly the sweep's expression"
    assert scan_sweep._due() == scan_sweep.due_expression(unattempted)


def test_the_migration_creates_two_partial_indexes_and_retires_the_one_nothing_reads() -> None:
    migration = _squash(MIGRATION.read_text(encoding="utf-8"))
    assert "drop index if exists public.files_scan_pending_idx" in migration
    for name in ("files_scan_due_idx", "files_scan_due_tenant_idx"):
        assert f"create index if not exists {name}" in migration
    assert migration.count("where status = 'ready' and scan_status = 'pending' and size_bytes <= 104857600") == 2
    assert "set local lock_timeout" in migration
    assert re.search(r"\(\s*tenant_id, \(case when", migration), "the tenant index leads with the tenant"
    # the SQL's pending predicate is the index's, or the planner cannot use the index
    from koras_worker.scanning.config import MAX_SCAN_BYTES

    assert MAX_SCAN_BYTES == 104857600
    assert scan_sweep._PENDING == (
        "status = 'ready' and scan_status = 'pending' and size_bytes <= 104857600"
    )


def test_the_expression_is_immutable_sql_only() -> None:
    expression = scan_sweep.due_expression(1260).lower()
    assert "at time zone 'utc'" in expression and "make_interval" in expression
    assert "now()" not in expression and "current_" not in expression
    assert re.search(r"timestamptz|::timestamptz", expression) is None


def test_the_watermark_bound_cannot_admit_a_file_the_watermark_excludes() -> None:
    owed = scan_sweep._owed()
    assert "created_at >= :not_before" in owed, "the deciding test is unchanged"
    assert ":due_from" in owed and owed.count(":due_from") == 1


def test_every_selection_admits_only_a_final_key() -> None:
    """The runtime holds any other key without an attempt; never re-select it."""
    for sql in (
        scan_sweep._first_owner_sql(),
        scan_sweep._page_sql(),
        scan_sweep._tenants_sql(wrapped=False),
        scan_sweep._tenants_sql(wrapped=True),
    ):
        assert "^tenants/[^/]+/[^/]+/[^/]+/final/[^/]+/[^/]+$" in sql
        assert "restore_requests" not in sql
        assert not re.search(r"\b(update|insert|delete)\b", sql, re.I), "the sweep writes nothing"
    assert "f.storage_key" in scan_sweep._tenants_sql(wrapped=False)


def test_the_sql_final_shape_is_the_python_final_shape() -> None:
    """The regular expression in SQL and `is_final_key` agree on every key below."""
    from koras_api.core.upload_window import final_key_for, incoming_key, is_final_key

    tenant, file_id, generation = TENANT_A, fid(1), "44444444-4444-4444-8444-444444444444"
    incoming = incoming_key(tenant, "documents", file_id, generation, "a.csv")
    keys = [
        final_key_for(incoming, generation),
        incoming,
        f"tenants/{tenant}/documents/{file_id}/a.csv",
        f"tenants/{tenant}/documents/{file_id}/final/{generation}/a.csv/b",
        f"tenants/{tenant}/documents/{file_id}/final//a.csv",
    ]
    pattern = scan_sweep._FINAL_SHAPE.split("'")[1]
    for key in keys:
        assert bool(re.search(pattern, key)) is is_final_key(key), key
