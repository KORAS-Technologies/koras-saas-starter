"""What an import may cost the worker it runs in, and what stops it.

GR-352C. `koras-import` has its own suites for the reader the worker now uses
and for the answers it gives. What only exists once that reader is inside a
job is asserted here, against the product's own task and not a copy of it:

**One import at a time.** The worker has ten job slots and one machine's
memory. An accepted import was measured fitting that memory once, so the heavy
part of a dry run or a commit is held behind a slot, and a second import waits
holding nothing. The test counts how many are inside at once.

**The event loop keeps turning.** The reading runs on a thread. Run inline it
stopped everything else the worker does for as long as it took.

**A job that is cancelled stops reading.** The queue's timeout cancels a
coroutine, and a coroutine cannot stop a parse that has no `await` in it:
before this, a job past its timeout read on to the end of the file. The
cancellation is handed to the budget the reader asks, and the test waits for
the thread to have ended -- not for the coroutine to have returned, which
proves nothing.

**A run that spends its time fails with a sentence**, through the path every
other refusal takes.

Each of the four has a second test showing that the first can fail: the slot
widened, the read put back inline, the cancellation not passed on, the budget
never asked. A guard that cannot fire proves nothing about what it stands in
front of.

Nothing here is the transaction -- that needs a database, and
`tests/integration/test_import_commit_atomic.py` is where it is asked.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

# The worker builds its `Settings()` at import. This file runs alone as well as
# in the suite.
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import koras_worker.tasks.imports as task  # noqa: E402
from koras_import import (  # noqa: E402
    BudgetExceeded,
    FieldSpec,
    ImportTarget,
    Operation,
    Validation,
    WorkBudget,
    Written,
    build_registry,
)
from koras_queue import JobEnvelope  # noqa: E402

TENANT = "00000000-0000-4000-8000-000000000001"


async def _writer(_session: object, request: Any) -> Written:  # noqa: ANN401
    return Written(created=len(request.rows))


TARGET = ImportTarget(
    key="probe.people",
    label_key="import.target.probe.people",
    permission="imports.manage",
    fields=(FieldSpec(name="name", label_key="import.field.name", required=True),),
    match_keys=("name",),
    operations=(Operation.SKIP_DUPLICATE,),
    writer=_writer,
)


@dataclass
class _Run:
    id: str
    status: str
    target: str = TARGET.key
    operation: str = Operation.SKIP_DUPLICATE.value
    format: str = "csv"
    source_file_id: str = "file-1"
    requested_by: str = "user-1"
    committed_by: str | None = "user-2"
    job_id: str | None = None
    error: str | None = None


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, *_: object, **__: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _Engine:
    async def dispose(self) -> None:
        return None


class _SourceRefused(RuntimeError):
    pass


@dataclass
class _Store:
    """The run store, with the reading replaced by whatever a test hands in.

    Everything else is the smallest thing that lets the product's own task run
    from its first line to its last. What is under test is the task.
    """

    read: Callable[[Callable[[], None] | None], None]
    runs: dict[str, _Run] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)
    abandoned: dict[str, str] = field(default_factory=dict)
    SourceRefused: type[Exception] = _SourceRefused

    async def get(self, _session: object, run_id: str) -> _Run | None:
        return self.runs.get(run_id)

    async def source_bytes(self, *_: object) -> bytes:
        return b"Name\nAda\n"

    def examine(self, _raw: bytes, _target: object, _run: object, *, watch: Any = None) -> Any:  # noqa: ANN401
        self.read(watch)
        verdict = Validation(rows=1, valid=1, errors=())
        return SimpleNamespace(verdict=verdict, template_version=None)

    def prepare(self, _raw: bytes, _target: object, _run: object, *, watch: Any = None) -> Any:  # noqa: ANN401
        self.read(watch)
        return Validation(rows=1, valid=1, errors=()), ({"name": "Ada"},)

    async def predict_outcome(self, _session: object, *, examined: Any, **_: object) -> Any:  # noqa: ANN401
        return examined.verdict, None

    async def record_validation(self, _session: object, run: _Run, **_: object) -> Any:  # noqa: ANN401
        run.status = "validated"
        return SimpleNamespace(value="validated")

    async def begin_commit(self, _session: object, run: _Run) -> None:
        run.status = "committing"

    async def record_commit(self, _session: object, run: _Run, **_: object) -> None:
        run.status = "committed"

    async def fail(self, _session: object, run: _Run, reason: str) -> None:
        run.status = "failed"
        self.failed[run.id] = reason

    async def abandon(self, _session: object, run: _Run, reason: str) -> bool:
        run.status = "failed"
        self.abandoned[run.id] = reason
        return True


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., _Store]]:
    """The product's task, over a store a test controls."""

    async def nothing(*_: object, **__: object) -> None:
        return None

    def install(read: Callable[[Callable[[], None] | None], None], **runs: str) -> _Store:
        store = _Store(read=read)
        for run_id, status in runs.items():
            store.runs[run_id] = _Run(id=run_id, status=status)
        monkeypatch.setattr(task, "_run_store", lambda: store)
        return store

    monkeypatch.setattr(task, "settings", SimpleNamespace(database_url="postgresql://x/y"))
    monkeypatch.setattr(task, "_engine", _Engine)
    monkeypatch.setattr(task, "async_sessionmaker", lambda *_, **__: _Session)
    monkeypatch.setattr(task, "_registry", lambda: build_registry([TARGET]))
    monkeypatch.setattr(task, "_object_store", lambda: object())
    monkeypatch.setattr(task, "_record", nothing)
    monkeypatch.setattr(task, "_witness", nothing)
    monkeypatch.setattr(task, "_tell", nothing)
    yield install


def _job(run_id: str) -> JobEnvelope:
    return JobEnvelope(task="imports.validate", tenant_id=TENANT, payload={"run_id": run_id})


class _Inside:
    """How many reads are in progress at once, and the most there ever were."""

    def __init__(self, seconds: float = 0.05) -> None:
        self.seconds = seconds
        self.lock = threading.Lock()
        self.now = 0
        self.most = 0
        self.total = 0

    def __call__(self, _watch: Callable[[], None] | None) -> None:
        with self.lock:
            self.now += 1
            self.total += 1
            self.most = max(self.most, self.now)
        time.sleep(self.seconds)
        with self.lock:
            self.now -= 1


# ── one import at a time ─────────────────────────────────────────────────────


#: Two dry runs and two commits, each in the state its job expects.
FOUR = {
    "v1": "validating",
    "v2": "validating",
    "c1": "commit_requested",
    "c2": "commit_requested",
}


async def _four_at_once(store: _Store) -> list[dict[str, Any]]:
    return await asyncio.gather(
        task.validate_run({}, _job("v1")),
        task.commit_run({}, _job("c1")),
        task.validate_run({}, _job("v2")),
        task.commit_run({}, _job("c2")),
    )


async def test_two_imports_are_never_read_at_once(worker: Callable[..., _Store]) -> None:
    inside = _Inside()
    store = worker(inside, **FOUR)
    assert task.IMPORT_SLOTS == 1

    answers = await _four_at_once(store)

    assert [answer["status"] for answer in answers] == ["ok", "ok", "ok", "ok"]
    assert inside.total == 4
    assert inside.most == 1, f"{inside.most} imports were read at the same moment"
    # Nobody was refused for waiting: all four finished.
    assert {run.status for run in store.runs.values()} == {"validated", "committed"}


async def test_the_count_above_does_rise_when_the_slot_is_widened(
    worker: Callable[..., _Store], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(task, "IMPORT_SLOTS", 4)
    inside = _Inside()
    store = worker(inside, **FOUR)

    await _four_at_once(store)

    assert inside.most > 1


async def test_a_waiting_import_holds_no_file(worker: Callable[..., _Store]) -> None:
    """The slot is taken before the source is fetched, not around the parse.

    A second import that had already fetched its file would be waiting with up
    to 64 MiB in hand, which is the memory the slot exists to keep apart.
    """
    fetched: list[str] = []
    release = threading.Event()

    def read(_watch: Callable[[], None] | None) -> None:
        release.wait(5)

    store = worker(read, v1="validating", v2="validating")
    real = store.source_bytes

    async def source_bytes(*args: object) -> bytes:
        fetched.append("fetched")
        return await real(*args)

    store.source_bytes = source_bytes  # type: ignore[method-assign]
    both = asyncio.gather(task.validate_run({}, _job("v1")), task.validate_run({}, _job("v2")))
    for _ in range(100):
        await asyncio.sleep(0.01)
        if fetched:
            break
    await asyncio.sleep(0.05)
    assert fetched == ["fetched"], "the second import fetched its file while the first was read"
    release.set()
    await both
    assert fetched == ["fetched", "fetched"]


# ── the loop keeps turning ───────────────────────────────────────────────────


async def _ticks_while_reading(store_for: Callable[..., _Store]) -> int:
    """How many times another coroutine ran while a file was being read."""
    reading = threading.Event()
    release = threading.Event()

    def read(_watch: Callable[[], None] | None) -> None:
        reading.set()
        release.wait(2)

    store_for(read, v1="validating")
    job = asyncio.ensure_future(task.validate_run({}, _job("v1")))
    ticks = 0
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not job.done():
        await asyncio.sleep(0.01)
        # Counted only while the read is still going: a turn taken after it
        # has finished says nothing about whether the loop was free during it.
        if reading.is_set() and not job.done():
            ticks += 1
            if ticks >= 5:
                break
    release.set()
    await job
    return ticks


async def test_another_job_runs_while_a_file_is_read(worker: Callable[..., _Store]) -> None:
    assert await _ticks_while_reading(worker) >= 5


async def test_the_loop_test_above_does_fail_for_an_inline_read(
    worker: Callable[..., _Store], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def inline(_budget: WorkBudget, work: Callable[[], Any]) -> Any:  # noqa: ANN401
        return work()

    monkeypatch.setattr(task, "_off_loop", inline)
    # The read holds the loop for its two seconds, and nothing else runs.
    assert await _ticks_while_reading(worker) == 0


# ── a cancelled job stops reading ────────────────────────────────────────────


class _Endless:
    """A read that goes on until it is told to stop, and says when it has."""

    def __init__(self, *, asks: bool = True) -> None:
        self.asks = asks
        self.started = threading.Event()
        self.ended = threading.Event()
        self.give_up = threading.Event()

    def __call__(self, watch: Callable[[], None] | None) -> None:
        self.started.set()
        # Endless as far as any test here is concerned, and not as far as the
        # suite is: a read that is never told to stop -- which is the defect
        # these tests exist for -- must fail its test rather than hold the
        # interpreter open behind it for ever.
        patience = time.monotonic() + 20
        try:
            while not self.give_up.is_set() and time.monotonic() < patience:
                if self.asks and watch is not None:
                    watch()
                time.sleep(0.005)
        finally:
            self.ended.set()


async def test_a_job_the_queue_times_out_stops_reading_and_says_so(
    worker: Callable[..., _Store],
) -> None:
    read = _Endless()
    store = worker(read, v1="validating")

    # What the queue does at a job's timeout: cancel the coroutine.
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(task.validate_run({}, _job("v1")), timeout=0.3)

    assert read.started.is_set()
    assert read.ended.is_set(), "the job was cancelled and its thread went on reading"
    # And the run is not left saying `validating` for ever.
    assert store.abandoned == {"v1": task._INTERRUPTED}
    assert store.runs["v1"].status == "failed"


async def test_a_commit_the_queue_times_out_stops_reading_and_says_so(
    worker: Callable[..., _Store],
) -> None:
    read = _Endless()
    store = worker(read, c1="commit_requested")

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(task.commit_run({}, _job("c1")), timeout=0.3)

    assert read.ended.is_set()
    assert store.abandoned == {"c1": task._INTERRUPTED}


async def test_the_stop_test_above_does_fail_when_the_cancellation_is_not_passed_on(
    worker: Callable[..., _Store], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without `budget.cancel()` the thread reads on, which is what it did."""
    monkeypatch.setattr(WorkBudget, "cancel", lambda _self: None)
    monkeypatch.setattr(task, "_STOP_GRACE_SECONDS", 0.2)
    read = _Endless()
    worker(read, v1="validating")
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(task.validate_run({}, _job("v1")), timeout=0.2)
        assert not read.ended.is_set()
    finally:
        read.give_up.set()
        read.ended.wait(2)


async def test_a_finished_run_is_not_marked_by_a_late_cancellation(
    worker: Callable[..., _Store],
) -> None:
    store = worker(lambda _watch: None, v1="validated", c1="committed")
    await task._abandon(_job("v1"))
    await task._abandon(_job("c1"))
    await task._abandon(_job("nobody"))
    assert store.abandoned == {}


# ── a run that spends its time fails with a sentence ─────────────────────────


async def test_a_dry_run_past_its_budget_fails_and_records_why(
    worker: Callable[..., _Store], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(task, "WORK_BUDGET_SECONDS", 0.1)
    read = _Endless()
    store = worker(read, v1="validating")

    answer = await asyncio.wait_for(task.validate_run({}, _job("v1")), timeout=5)

    assert answer == {"status": "failed", "reason": "unreadable"}
    assert read.ended.is_set()
    assert "took longer than one run is allowed" in store.failed["v1"]
    # Recorded by the path every refusal takes, not by the cancellation's.
    assert store.abandoned == {}


async def test_a_commit_past_its_budget_writes_nothing_and_records_why(
    worker: Callable[..., _Store], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(task, "WORK_BUDGET_SECONDS", 0.1)
    written: list[int] = []

    async def writer(_session: object, request: Any) -> Written:  # noqa: ANN401
        written.append(len(request.rows))
        return Written(created=len(request.rows))

    monkeypatch.setattr(
        task,
        "_registry",
        lambda: build_registry(
            [
                ImportTarget(
                    key=TARGET.key,
                    label_key=TARGET.label_key,
                    permission=TARGET.permission,
                    fields=TARGET.fields,
                    match_keys=TARGET.match_keys,
                    operations=TARGET.operations,
                    writer=writer,
                )
            ]
        ),
    )
    read = _Endless()
    store = worker(read, c1="commit_requested")

    answer = await asyncio.wait_for(task.commit_run({}, _job("c1")), timeout=5)

    assert answer["status"] == "failed"
    assert "took longer than one run is allowed" in answer["reason"]
    assert written == [], "the writer was called for a file that was never finished reading"
    assert store.runs["c1"].status == "failed"


async def test_the_budget_test_above_does_fail_for_a_read_that_never_asks(
    worker: Callable[..., _Store], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(task, "WORK_BUDGET_SECONDS", 0.1)
    read = _Endless(asks=False)
    worker(read, v1="validating")
    job = asyncio.ensure_future(task.validate_run({}, _job("v1")))
    await asyncio.sleep(0.5)
    try:
        # Five budgets later it is still reading: a limit nothing asks is not one.
        assert not job.done() and not read.ended.is_set()
    finally:
        read.give_up.set()
        await job


def test_the_budget_starts_when_the_slot_is_held_and_is_under_the_queue_s() -> None:
    from koras_import import COMMIT_RUN, VALIDATE_RUN

    # The limit that can end the work has to arrive before the one that cannot.
    assert task.WORK_BUDGET_SECONDS < VALIDATE_RUN.timeout_seconds
    assert task.WORK_BUDGET_SECONDS < COMMIT_RUN.timeout_seconds
    assert issubclass(BudgetExceeded, task.ReadRefused)


# ── the rows a writer is handed ──────────────────────────────────────────────


async def test_the_writer_is_handed_the_rows_that_were_prepared_and_no_copy(
    worker: Callable[..., _Store], monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = ({"name": "Ada"}, {"name": "Grace"})
    seen: list[Any] = []

    async def writer(_session: object, request: Any) -> Written:  # noqa: ANN401
        seen.append(request.rows)
        return Written(created=len(request.rows))

    monkeypatch.setattr(
        task,
        "_registry",
        lambda: build_registry(
            [
                ImportTarget(
                    key=TARGET.key,
                    label_key=TARGET.label_key,
                    permission=TARGET.permission,
                    fields=TARGET.fields,
                    match_keys=TARGET.match_keys,
                    operations=TARGET.operations,
                    writer=writer,
                )
            ]
        ),
    )
    store = worker(lambda _watch: None, c1="commit_requested")
    store.prepare = lambda *_, **__: (Validation(rows=2, valid=2, errors=()), prepared)  # type: ignore[method-assign]

    answer = await task.commit_run({}, _job("c1"))

    assert answer["status"] == "ok" and answer["created"] == 2
    assert seen[0] is prepared


# ── memory handed back, where there is a way to ──────────────────────────────


class _Library:
    """A C library, as far as `_give_back` is concerned."""

    def __init__(self) -> None:
        self.trimmed: list[int] = []

    def malloc_trim(self, pad: int) -> int:
        self.trimmed.append(pad)
        return 1


def test_freed_memory_is_handed_back_through_the_c_library_s_own_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library = _Library()
    asked: list[str] = []

    def load(name: str) -> _Library:
        asked.append(name)
        return library

    monkeypatch.setattr(task.ctypes, "CDLL", load)
    task._give_back()
    assert asked == ["libc.so.6"] and library.trimmed == [0]


@pytest.mark.parametrize(
    "missing",
    [OSError("libc.so.6: cannot open shared object file"), FileNotFoundError("no such library")],
    ids=["no-such-library", "not-found"],
)
def test_a_platform_with_no_such_library_is_a_worker_that_does_nothing_here(
    monkeypatch: pytest.MonkeyPatch, missing: Exception
) -> None:
    # Windows, macOS, and any image whose C library is not glibc.
    def load(_name: str) -> None:
        raise missing

    monkeypatch.setattr(task.ctypes, "CDLL", load)
    task._give_back()


def test_a_c_library_without_the_call_is_the_same(monkeypatch: pytest.MonkeyPatch) -> None:
    # A library that loads under that name and has no `malloc_trim`.
    monkeypatch.setattr(task.ctypes, "CDLL", lambda _name: object())
    task._give_back()


async def test_an_import_finishes_where_nothing_can_be_handed_back(
    worker: Callable[..., _Store], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Handing memory back is a courtesy to the machine and not a step of the job.

    The dry run and the commit both end as they would have, on a platform
    where the library is not there to ask.
    """

    def load(_name: str) -> None:
        raise OSError("not this platform")

    monkeypatch.setattr(task.ctypes, "CDLL", load)
    store = worker(lambda _watch: None, v1="validating", c1="commit_requested")

    checked = await task.validate_run({}, _job("v1"))
    written = await task.commit_run({}, _job("c1"))

    assert (checked["status"], written["status"]) == ("ok", "ok")
    assert (store.runs["v1"].status, store.runs["c1"].status) == ("validated", "committed")
