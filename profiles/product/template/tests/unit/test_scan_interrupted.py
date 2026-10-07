# ruff: noqa: ANN001, ANN002, ANN003, ANN201, ANN202, ANN204, ANN401, E501, S101, S608
"""A scan attempt cut short by the queue or the worker is `scan_interrupted`.

The queue's job timeout cancels the coroutine; a worker shutting down does the
same. Once the attempt is counted, the run records `scan_interrupted`, leaves the
file pending, keeps the attempt, and lets the cancellation continue. It never
replaces the scanner's own reasons, never touches a file that has already left
`pending`, and a failure to record it never masks the cancellation.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_worker.scanning import ScanDisposition, ScanFailure  # noqa: E402
from koras_worker.scanning import runtime as runtime_module  # noqa: E402
from scanner_support import FakeScanner  # noqa: E402
from test_scan_runtime import run, session_for, source_for  # noqa: E402


class Blocking:
    """A scanner that has taken the stream and never answers, as a hung engine would."""

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def scan(self, source) -> Any:
        self.started.set()
        await asyncio.Event().wait()

    async def ping(self) -> bool:
        return True


async def interrupt(session, scanner=None, *, max_attempts: int = 12) -> None:
    scanner = scanner or Blocking()
    task = asyncio.ensure_future(run(session, source_for(), scanner, max_attempts=max_attempts))
    await asyncio.wait_for(scanner.started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_cancelled_attempt_records_scan_interrupted_and_stays_pending() -> None:
    session = session_for()
    await interrupt(session)
    stored = session.get()
    assert (stored["status"], stored["scan_status"]) == ("ready", "pending")
    assert stored["scan_failure"] == "scan_interrupted"
    assert stored["scan_attempts"] == 1 and stored["scan_attempted_at"] is not None
    assert session.actions.count("storage.object.scan_failed") == 1


async def test_the_queue_timeout_path_is_the_same_cancellation() -> None:
    session = session_for()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(run(session, source_for(), Blocking()), 0.05)
    assert session.get()["scan_failure"] == "scan_interrupted"


async def test_an_interrupted_file_can_later_be_scanned_and_released() -> None:
    session = session_for()
    await interrupt(session)
    result = await run(session, source_for(), FakeScanner.candidate_clean())
    assert result.disposition is ScanDisposition.CLEAN and result.attempts == 2
    stored = session.get()
    assert stored["scan_status"] == "clean" and stored["scan_failure"] is None


async def test_an_interrupted_file_can_later_be_quarantined() -> None:
    session = session_for()
    await interrupt(session)
    result = await run(session, source_for(), FakeScanner.infected())
    assert result.disposition is ScanDisposition.INFECTED
    assert session.get()["scan_status"] == "infected"


async def test_repeated_interruptions_count_every_attempt_and_write_one_failure_event() -> None:
    session = session_for()
    for _ in range(3):
        await interrupt(session)
    assert session.get()["scan_attempts"] == 3
    assert session.actions.count("storage.object.scan_failed") == 1


async def test_interruptions_reach_the_threshold_and_exhaustion_is_written_once() -> None:
    session = session_for()
    for _ in range(5):
        await interrupt(session, max_attempts=3)
    assert session.actions.count("storage.object.scan_exhausted") == 1
    stored = session.get()
    assert stored["scan_attempts"] == 5 and stored["scan_status"] == "pending"


async def test_the_scanner_s_own_reasons_are_not_replaced_by_the_interruption_class() -> None:
    for scanner, expected in (
        (FakeScanner.unavailable(), "scanner_unavailable"),
        (FakeScanner.timeout(), "scan_timeout"),
    ):
        session = session_for()
        await run(session, source_for(), scanner)
        assert session.get()["scan_failure"] == expected


async def test_an_interruption_does_not_replace_an_earlier_specific_failure() -> None:
    """An outage recorded by an earlier attempt is better evidence than the label."""
    session = session_for()
    await run(session, source_for(), FakeScanner.unavailable())
    await interrupt(session)
    stored = session.get()
    assert stored["scan_failure"] == "scanner_unavailable"
    assert stored["scan_attempts"] == 2, "the interrupted attempt is still counted"
    assert session.actions.count("storage.object.scan_failed") == 1, "and no event is added"


@pytest.mark.parametrize("failure", [f for f in ScanFailure if f is not ScanFailure.SCAN_INTERRUPTED])
async def test_no_specific_failure_is_ever_replaced_by_the_interruption_class(failure) -> None:
    session = session_for(scan_failure=failure.value)
    await runtime_module._record_interrupted(
        session, session.get()["tenant_id"], session.get()["id"]
    )
    assert session.get()["scan_failure"] == failure.value
    assert session.actions == [] and session.writes == 0


async def test_a_failure_recorded_during_the_attempt_survives_the_cancellation_that_follows() -> None:
    """The race: the run recorded its own specific reason, then the queue cancelled it."""
    session = session_for()
    scanner = Blocking()
    task = asyncio.ensure_future(run(session, source_for(), scanner))
    await asyncio.wait_for(scanner.started.wait(), 2)
    session.get()["scan_failure"] = "integrity_mismatch"  # committed just before the cancel
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.get()["scan_failure"] == "integrity_mismatch"
    assert session.get()["scan_status"] == "pending" and session.get()["scan_attempts"] == 1


async def test_an_interruption_is_recorded_when_nothing_better_exists_and_only_once() -> None:
    session = session_for()
    for _ in range(2):
        await runtime_module._record_interrupted(
            session, session.get()["tenant_id"], session.get()["id"]
        )
    assert session.get()["scan_failure"] == "scan_interrupted"
    assert session.actions.count("storage.object.scan_failed") == 1


async def test_the_interruption_and_a_later_specific_failure_still_replace_each_other_normally() -> (
    None
):
    """`keep_existing` constrains the weak label only; every other class still updates."""
    session = session_for()
    await interrupt(session)
    await run(session, source_for(), FakeScanner.unavailable())
    assert session.get()["scan_failure"] == "scanner_unavailable"


async def test_a_cancellation_before_the_attempt_is_counted_records_nothing() -> None:
    """The window defers before the attempt; nothing was tried, so nothing is interrupted."""
    from datetime import timedelta

    from object_support import ISSUED

    session = session_for()
    result = await run(session, source_for(), Blocking(), at=ISSUED + timedelta(minutes=10))
    assert result.disposition is ScanDisposition.DEFERRED
    assert session.get()["scan_attempts"] == 0 and session.get()["scan_failure"] is None


async def test_a_file_that_left_pending_before_the_cancellation_is_not_touched() -> None:
    session = session_for(scan_status="infected", scan_failure=None)
    await runtime_module._record_interrupted(
        session, session.get()["tenant_id"], session.get()["id"]
    )
    stored = session.get()
    assert stored["scan_status"] == "infected" and stored["scan_failure"] is None
    assert session.actions == []


async def test_a_failure_to_record_the_interruption_does_not_mask_the_cancellation(
    caplog,
) -> None:
    session = session_for()
    scanner = Blocking()
    task = asyncio.ensure_future(run(session, source_for(), scanner))
    await asyncio.wait_for(scanner.started.wait(), 2)
    session.fail_update = True
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.get()["scan_failure"] is None and session.get()["scan_status"] == "pending"


async def test_a_second_cancellation_during_the_write_does_not_abandon_it() -> None:
    session = session_for()
    scanner = Blocking()
    task = asyncio.ensure_future(run(session, source_for(), scanner))
    await asyncio.wait_for(scanner.started.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.05)  # the shielded write finishes on its own
    assert session.get()["scan_failure"] == "scan_interrupted"


def test_no_other_exception_is_recorded_as_an_interruption() -> None:
    """Only `CancelledError` is caught; a scanner that raises is `scanner_error`, as before."""
    import ast
    import inspect

    source = inspect.getsource(runtime_module)
    handlers = [
        ast.unparse(n.type)
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.ExceptHandler) and n.type
    ]
    assert "asyncio.CancelledError" in handlers
    assert ScanFailure.SCAN_INTERRUPTED.value == "scan_interrupted"
