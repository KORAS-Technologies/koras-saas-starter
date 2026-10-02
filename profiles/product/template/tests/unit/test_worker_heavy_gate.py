"""The worker's heavy gate: one section at a time, and let go on every way out.

GR-352E. `test_worker_heavy_sections.py` asks the product's own jobs whether
they are inside it. This file asks the gate itself, with nothing of any job in
the way, the things a gate can get wrong on its own:

**It lets go.** On a return, on an exception, on a cancellation while inside,
on a cancellation while waiting, and on the one in between -- let in and
cancelled in the same turn of the loop, which is the case a gate written by
hand usually leaks.

**It is fair.** A job that lets go and asks again in the same turn does not go
back in ahead of one that was already waiting. A backup asks two thousand
times a night.

**It is narrow.** A job that never asks is never held up, which is the
difference between this and one job slot.

Each of the three has a test showing the first can fail.
"""

from __future__ import annotations

import asyncio
import os
import weakref

import pytest

# The worker builds its `Settings()` at import. This file runs alone as well as
# in the suite.
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

pytest.importorskip("koras_worker")
from koras_worker import heavy as gate  # noqa: E402
from koras_worker.heavy import BACKUP, IMPORT, REPORT, RESTORE, heavy  # noqa: E402


class _Watch:
    """How many sections are inside at once, and the order they went in."""

    def __init__(self) -> None:
        self.now = 0
        self.most = 0
        self.order: list[str] = []

    async def section(self, kind: str, *, limit: int | None = None, turns: int = 3) -> None:
        async with heavy(kind, limit=limit):
            self.now += 1
            self.most = max(self.most, self.now)
            self.order.append(kind)
            for _ in range(turns):
                await asyncio.sleep(0)
            self.now -= 1


# ── one at a time ────────────────────────────────────────────────────────────


async def test_one_section_is_inside_at_a_time_whatever_its_class() -> None:
    assert gate.HEAVY_SLOTS == 1
    watch = _Watch()

    await asyncio.gather(*(watch.section(kind) for kind in (IMPORT, BACKUP, RESTORE, REPORT) * 3))

    assert len(watch.order) == 12
    assert watch.most == 1


async def test_the_count_above_does_rise_when_the_gate_is_widened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gate, "HEAVY_SLOTS", 3)
    watch = _Watch()

    await asyncio.gather(*(watch.section(kind) for kind in (IMPORT, BACKUP, RESTORE, REPORT) * 3))

    assert watch.most == 3


async def test_a_class_s_own_limit_holds_inside_a_wider_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`IMPORT_SLOTS` is this: imports stay one to a process if the gate is widened."""
    monkeypatch.setattr(gate, "HEAVY_SLOTS", 4)
    imports = _Watch()
    others = _Watch()

    await asyncio.gather(
        *(imports.section(IMPORT, limit=1) for _ in range(4)),
        *(others.section(BACKUP) for _ in range(4)),
    )

    assert imports.most == 1
    assert len(imports.order) == 4 and len(others.order) == 4


async def test_what_is_inside_can_be_read() -> None:
    assert gate.occupancy() == {}
    async with heavy(BACKUP):
        assert gate.occupancy() == {BACKUP: 1}
    assert gate.occupancy() == {}


# ── it lets go ───────────────────────────────────────────────────────────────


async def _goes_in(kind: str = IMPORT) -> None:
    """A section gets in, promptly. The proof that nothing before it leaked."""
    async with asyncio.timeout(2):
        async with heavy(kind):
            assert gate.occupancy() == {kind: 1}
    assert gate.occupancy() == {}


async def test_the_gate_is_let_go_when_the_section_raises() -> None:
    with pytest.raises(RuntimeError):
        async with heavy(REPORT):
            raise RuntimeError("the report could not be rendered")

    await _goes_in()


async def test_the_gate_is_let_go_when_the_section_is_cancelled() -> None:
    inside = asyncio.Event()

    async def job() -> None:
        async with heavy(BACKUP):
            inside.set()
            await asyncio.sleep(60)

    running = asyncio.ensure_future(job())
    await inside.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    await _goes_in()


async def test_a_job_cancelled_while_it_waits_takes_nothing_and_blocks_nobody() -> None:
    """The queue's timeout landing on a job that never got in.

    It must leave the queue, and the one behind it must still be let in when
    the holder lets go -- a cancelled waiter left at the head would hold the
    gate shut for ever with nobody inside it.
    """
    release = asyncio.Event()
    entered: list[str] = []

    async def holder() -> None:
        async with heavy(IMPORT):
            await release.wait()

    async def waiter(name: str) -> None:
        async with heavy(RESTORE):
            entered.append(name)

    holding = asyncio.ensure_future(holder())
    await asyncio.sleep(0)
    first = asyncio.ensure_future(waiter("first"))
    second = asyncio.ensure_future(waiter("second"))
    await asyncio.sleep(0)

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert gate.occupancy() == {IMPORT: 1}

    release.set()
    async with asyncio.timeout(2):
        await asyncio.gather(holding, second)
    assert entered == ["second"]
    assert gate.occupancy() == {}


async def test_a_job_let_in_and_cancelled_in_the_same_turn_gives_its_place_back() -> None:
    """The leak a hand-written gate usually has.

    The holder lets go, which lets the waiter in -- its future is resolved --
    and before the waiter has run again something cancels it. It was given the
    place and will never use it; unless it hands the place back, the gate is
    held by nobody.
    """

    async def waiter() -> None:
        async with heavy(BACKUP):
            pytest.fail("a cancelled job went into its section")

    # Held by hand, so that letting go and cancelling can be one turn of the
    # loop with no `await` between them.
    held = gate._gate()
    await held.acquire(IMPORT, None)
    waiting = asyncio.ensure_future(waiter())
    await asyncio.sleep(0)

    held.release(IMPORT)
    # The waiter has been let in and has not run yet.
    assert gate.occupancy() == {BACKUP: 1}
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting

    await _goes_in()


async def test_the_tests_above_do_fail_for_a_gate_that_is_not_let_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gate._Gate, "release", lambda _self, _kind: None)

    with pytest.raises(RuntimeError):
        async with heavy(REPORT):
            raise RuntimeError("the report could not be rendered")

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.2):
            async with heavy(IMPORT):
                pytest.fail("a section went in beside one that was never let go")


# ── it is fair ───────────────────────────────────────────────────────────────


async def _a_backup_and_an_import() -> list[str]:
    """Three objects copied one after another, and an import that arrives during the first."""
    order: list[str] = []

    async def backup() -> None:
        for number in range(3):
            async with heavy(BACKUP):
                order.append(f"object {number}")
                await asyncio.sleep(0)
                await asyncio.sleep(0)

    async def an_import() -> None:
        async with heavy(IMPORT):
            order.append("import")

    copying = asyncio.ensure_future(backup())
    await asyncio.sleep(0)
    importing = asyncio.ensure_future(an_import())
    await asyncio.gather(copying, importing)
    return order


async def test_a_job_that_lets_go_and_asks_again_waits_behind_one_already_waiting() -> None:
    """A night's backup is two thousand of these, and an import is one."""
    assert await _a_backup_and_an_import() == ["object 0", "import", "object 1", "object 2"]


async def test_the_order_above_is_the_gate_s_doing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A plain counter -- whoever asks next has the free place -- starves the import."""
    waits = gate._Gate.acquire

    async def whoever_asks_next(self: gate._Gate, kind: str, limit: int | None) -> None:
        if self._admits(kind, limit):
            self.held[kind] += 1
            return
        await waits(self, kind, limit)

    def frees_the_place_and_wakes_later(self: gate._Gate, kind: str) -> None:
        self.held[kind] -= 1
        if not self.held[kind]:
            del self.held[kind]
        asyncio.get_running_loop().call_soon(self._admit)

    monkeypatch.setattr(gate._Gate, "acquire", whoever_asks_next)
    monkeypatch.setattr(gate._Gate, "release", frees_the_place_and_wakes_later)

    assert (await _a_backup_and_an_import())[-1] == "import"


# ── it is narrow ─────────────────────────────────────────────────────────────


async def test_a_job_that_holds_no_payload_runs_beside_a_heavy_one() -> None:
    """The outbox sweep, a retention sweep, a product's own task.

    None of them asks for the gate, so none of them waits for it: the gate is
    not one job slot. Ten of them finish while a heavy section is still
    inside.
    """
    release = asyncio.Event()
    finished: list[int] = []

    async def heavy_job() -> None:
        async with heavy(IMPORT):
            await release.wait()

    async def light_job(number: int) -> None:
        await asyncio.sleep(0)
        finished.append(number)

    holding = asyncio.ensure_future(heavy_job())
    await asyncio.sleep(0)
    assert gate.occupancy() == {IMPORT: 1}

    async with asyncio.timeout(2):
        await asyncio.gather(*(light_job(number) for number in range(10)))

    assert sorted(finished) == list(range(10))
    assert not holding.done(), "the heavy section ended before the light jobs did"
    assert gate.occupancy() == {IMPORT: 1}
    release.set()
    await holding


# ── memory handed back, where there is a way to ──────────────────────────────


class _Library:
    """A C library, as far as `give_back` is concerned."""

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

    monkeypatch.setattr(gate.ctypes, "CDLL", load)
    gate.give_back()
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

    monkeypatch.setattr(gate.ctypes, "CDLL", load)
    gate.give_back()


def test_a_c_library_without_the_call_is_the_same(monkeypatch: pytest.MonkeyPatch) -> None:
    # A library that loads under that name and has no `malloc_trim`.
    monkeypatch.setattr(gate.ctypes, "CDLL", lambda _name: object())
    gate.give_back()


class _Payload:
    """Something a job holds in a local while it works: a file, its rows."""


async def _fails_holding(seen: list[weakref.ref[_Payload]]) -> None:
    payload = _Payload()
    seen.append(weakref.ref(payload))
    await asyncio.sleep(0)
    raise RuntimeError("the read failed with the file in hand")


async def test_a_section_that_fails_has_let_go_of_its_payload_before_the_gate_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure is still in hand, as it is while the queue records it. The payload is not.

    An exception holds its traceback, the traceback its frames, and a frame
    its locals. Unless the gate drops them, the next section starts on top of
    everything the failed one had read.
    """
    seen: list[weakref.ref[_Payload]] = []
    alive_when_handed_back: list[bool] = []
    monkeypatch.setattr(
        gate, "give_back", lambda: alive_when_handed_back.append(seen[0]() is not None)
    )

    try:
        async with heavy(IMPORT):
            await _fails_holding(seen)
    except RuntimeError as problem:
        kept = problem  # what a queue recording the failure is doing

    assert kept is not None
    assert alive_when_handed_back == [False], "the payload outlived the section that failed"
    assert seen[0]() is None


async def test_the_test_above_does_fail_when_the_frames_are_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gate, "_let_go_of", lambda _problem: None)
    seen: list[weakref.ref[_Payload]] = []

    try:
        async with heavy(IMPORT):
            await _fails_holding(seen)
    except RuntimeError as problem:
        kept = problem

    assert kept is not None
    assert seen[0]() is not None


async def test_every_section_hands_back_before_it_lets_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Before, so the next section starts from what this one gave back."""
    seen: list[dict[str, int]] = []
    monkeypatch.setattr(gate, "give_back", lambda: seen.append(gate.occupancy()))

    async with heavy(RESTORE):
        pass
    with pytest.raises(RuntimeError):
        async with heavy(REPORT):
            raise RuntimeError("no")

    assert seen == [{RESTORE: 1}, {REPORT: 1}]
