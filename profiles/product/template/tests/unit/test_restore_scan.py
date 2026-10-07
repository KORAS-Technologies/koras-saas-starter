# ruff: noqa: ANN401
"""Asking the scanner about what a restore wrote, with no database (ADR 0013, layer 5).

`restore_scan` is an enqueuer and a reader and nothing else: it writes no row, decides no
verdict and reads no object. These hold that in text, and hold the arithmetic of when a file is
owed another request. The behaviour against a real PostgreSQL (and the order in which a request
follows a commit) is `tests/integration/test_restore_replacement_real.py`.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

sys.path.insert(0, str(Path(__file__).resolve().parent))
pytest.importorskip("koras_worker")
from koras_queue import Enqueued  # noqa: E402
from koras_worker.tasks import restore_scan  # noqa: E402
from koras_worker.tasks.scan_sweep import backoff_seconds  # noqa: E402
from restore_support import FILE, TENANT, Queue  # noqa: E402


def _row(**over: object) -> SimpleNamespace:
    base = {
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "scan_attempts": 0,
        "scan_attempted_at": None,
        "finished_at": datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
    }
    return SimpleNamespace(**{**base, **over})


# -- when a restored file is owed a request ------------------------------------------


def test_the_in_flight_horizon_exceeds_the_scan_jobs_own_timeout() -> None:
    from koras_api.core.scan_jobs import SCAN_TIMEOUT_SECONDS

    assert restore_scan.in_flight_horizon_seconds() > SCAN_TIMEOUT_SECONDS


def test_a_restored_file_never_attempted_is_owed_a_request_after_its_grace() -> None:
    row = _row()
    assert not restore_scan.owed(row, row.finished_at + timedelta(seconds=30))
    assert restore_scan.owed(row, row.finished_at + timedelta(minutes=5))


def test_a_new_row_is_not_re_asked_before_its_read_gate_opens() -> None:
    created = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    row = _row(created_at=created, finished_at=created)
    window = restore_scan._window_seconds()
    assert not restore_scan.owed(row, created + timedelta(seconds=window - 5))
    assert restore_scan.owed(row, created + timedelta(seconds=window + 120))


def test_an_attempted_file_waits_the_sweeps_own_backoff() -> None:
    attempted = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    row = _row(scan_attempts=3, scan_attempted_at=attempted)
    wait = backoff_seconds(3)
    assert not restore_scan.owed(row, attempted + timedelta(seconds=wait - 1))
    assert restore_scan.owed(row, attempted + timedelta(seconds=wait))


def test_the_deferral_of_an_old_row_is_zero_and_of_a_new_one_is_the_window() -> None:
    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    assert restore_scan.defer_seconds(now - timedelta(days=400), now) == 0.0
    assert restore_scan.defer_seconds(now, now) == restore_scan._window_seconds()


def test_the_window_is_the_one_the_scanner_reads_by() -> None:
    from koras_api.core.upload_window import SCAN_READ_DELAY_SECONDS

    assert restore_scan._window_seconds() == SCAN_READ_DELAY_SECONDS


def test_the_reconciliation_selects_only_what_the_scanner_would_read() -> None:
    """A file on a key the scanner refuses to read would be asked for, and refused, for the whole
    look-back: the statement names the final shape."""
    sql = str(restore_scan._OWED)
    assert "'^tenants/[^/]+/[^/]+/[^/]+/final/[^/]+/[^/]+$'" in sql
    assert "f.status = 'ready' and f.scan_status = 'pending'" in sql


# -- the request ---------------------------------------------------------------------


async def _forget(_job_id: str) -> None:
    return None


async def test_a_request_is_the_one_scan_job_for_the_file_and_names_no_object() -> None:
    queue = Queue()
    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

    asked = await restore_scan.request_scan(
        queue,  # type: ignore[arg-type]
        _forget,
        tenant_id=TENANT,
        file_id=FILE,
        created_at=now - timedelta(days=400),
        now=now,
    )

    assert asked.state == "enqueued"
    (job,) = queue.jobs
    assert job["task"] == "file.scan" and job["tenant_id"] == TENANT
    assert job["payload"] == {"file_id": FILE} and job["key"] == f"scan:{FILE}"
    assert job["delay"] <= 2.0, "an old row's gate is open: no deferral is owed"


async def test_a_new_row_is_asked_for_after_its_gate_opens() -> None:
    queue = Queue()
    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

    await restore_scan.request_scan(
        queue,  # type: ignore[arg-type]
        _forget,
        tenant_id=TENANT,
        file_id=FILE,
        created_at=now,
        now=now,
    )

    assert queue.jobs[0]["delay"] >= restore_scan._window_seconds()


async def test_the_retained_result_of_an_earlier_scan_is_dropped_before_the_request() -> None:
    queue = Queue()
    dropped: list[str] = []

    async def forget(job_id: str) -> None:
        assert queue.jobs == [], "dropped first, or the queue refuses the id"
        dropped.append(job_id)

    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    await restore_scan.request_scan(
        queue,  # type: ignore[arg-type]
        forget,
        tenant_id=TENANT,
        file_id=FILE,
        created_at=now,
        now=now,
    )

    assert len(dropped) == 1 and len(queue.jobs) == 1


async def test_a_queue_that_is_down_is_a_failed_request_and_never_an_exception() -> None:
    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

    asked = await restore_scan.request_scan(
        Queue(fail=True),  # type: ignore[arg-type]
        _forget,
        tenant_id=TENANT,
        file_id=FILE,
        created_at=now,
        now=now,
    )

    assert asked.state == "failed"


async def test_a_process_with_no_queue_configured_is_a_failed_request() -> None:
    class Simulated(Queue):
        async def enqueue(self, task: Any, **kwargs: Any) -> Enqueued:  # type: ignore[override]
            return Enqueued(task=task.name, job_id="x", simulated=True)

    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    asked = await restore_scan.request_scan(
        Simulated(),  # type: ignore[arg-type]
        _forget,
        tenant_id=TENANT,
        file_id=FILE,
        created_at=now,
        now=now,
    )

    assert asked.state == "failed"


async def test_a_failure_to_forget_the_old_result_does_not_raise() -> None:
    async def broken(_job_id: str) -> None:
        raise ConnectionError("redis is unreachable")

    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    asked = await restore_scan.request_scan(
        Queue(),  # type: ignore[arg-type]
        broken,
        tenant_id=TENANT,
        file_id=FILE,
        created_at=now,
        now=now,
    )

    assert asked.state == "failed"


async def test_with_nothing_restored_no_queue_is_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(_url: str) -> None:
        raise AssertionError("a queue was opened for nothing")

    monkeypatch.setattr(restore_scan, "queue_for", explode)

    assert await restore_scan.request_scans_for_restored({}, []) == []


async def test_there_is_no_activation_check_a_secure_product_always_asks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scanner is mandatory when `secure_files` is on, so a restore has no "no scanner" case."""
    queue = Queue()
    monkeypatch.setattr(restore_scan, "queue_for", lambda _url: queue)
    monkeypatch.setenv("FILE_SCAN_BACKEND", "none")  # refused at start; never a reason to skip
    now = datetime.now(UTC)

    asked = await restore_scan.request_scans_for_restored({}, [(TENANT, FILE, now)])

    assert [a.state for a in asked] == ["enqueued"] and len(queue.jobs) == 1


# -- what the module may and may not do ----------------------------------------------


def _source() -> str:
    return inspect.getsource(restore_scan)


def test_restore_scan_imports_nothing_from_the_scanner() -> None:
    """What it needs of the scan is the job declaration (`tasks.scan.declaration`) and the
    sweep's back-off. No client, no reader, no transition, no gate."""
    tree = ast.parse(_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "scanning" not in (node.module or ""), node.module
        if isinstance(node, ast.Import):
            assert not any("scanning" in alias.name for alias in node.names)


def test_restore_scan_writes_no_row_and_decides_no_verdict() -> None:
    source = _source()
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith(("#", '"'))
    ).lower()
    # Only reads: every statement it holds begins with `select`.
    statements = re.findall(r'text\(\s*"([a-z]+)', source)
    assert statements and set(statements) <= {"select"}, statements
    for forbidden in (
        "insert into",
        "update public",
        "delete from",
        "scan_status =",
        "commit_clean",
        "commit_infected",
        "transition",
        "clamdscanner",
        "scanobject",
        "objectreader",
        "session.commit",
    ):
        assert forbidden not in code, forbidden


def test_restore_scan_enqueues_only_through_the_one_enqueue_function() -> None:
    source = _source()
    assert source.count("enqueue_scan(") == 1
    assert ".enqueue(" not in source, "a second spelling of the job would be a second identity"
    assert "contract.FILE_SCAN" in source and "contract.scan_payload" not in source
