"""One heavy thing at a time in this process.

GR-352E. The worker has ten job slots, which is a statement about coroutines
waiting on a database, and one machine's memory, which those slots say nothing
about. GR-352C held imports apart from each other and left everything else
free to run beside one. Measured in the product's own image under the 512 MiB
it is deployed with, that was not enough: the worst accepted import peaked at
357 to 371 MiB by itself, a cross-provider backup of a 64 MiB object took 193
MiB over idle, and the two together reached 499 MiB on one run and the limit
itself on the other. Nothing was killed, and nothing was left.

So the sections of a job that hold a payload share one gate:

- an import, from before its source is fetched to its last statement;
- a backup, for each object it copies and reads back;
- a restore, for each object it brings back;
- a scheduled report, from the query that answers it to the last mail that
  carries it.

**What it is not.** Not a queue, not a lock any other process can see and not
a limit on jobs: a second worker machine has a gate of its own, which is the
scope the memory has, and every job that holds no payload -- the outbox sweep,
the retention sweeps, a product's own tasks -- runs beside a heavy one exactly
as it did. `max_jobs` is still ten.

**One primitive, taken once.** A job never holds two gates, so there is no
order to get wrong. A class that is narrower than the gate -- imports, one to a
process whatever the gate is widened to -- says so as a `limit` on the same
acquisition rather than as a second semaphore taken before or after this one.

**First come, first served.** A backup takes the gate once an object and a
scheduled delivery once a report, so a job with two thousand objects lets go
two thousand times. Whoever was already waiting goes next: without that, a
loop that lets go and asks again in the same turn would never be interrupted,
and an import a person is watching would wait for a night's backup to end.

**A job that is waiting here is a job the queue is timing.** A cron job has
300 seconds and an import may hold the gate for longer than that. The job that
is cancelled while it waits has taken nothing and written nothing, and each of
the three is picked up by its own next run: a schedule stays due, an object
stays without a copy, a restore stays approved. IMPORT-GAP-021 is the same
fact about a second import.

`docs/features/data-import/worker-resource-envelope.md` has the measurements.
"""

from __future__ import annotations

import asyncio
import ctypes
import gc
import logging
import time
import traceback
import weakref
from collections import Counter, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

logger = logging.getLogger(__name__)

#: PROVISIONAL (GR-352E, pending NFR ratification). How many heavy sections
#: this process is inside at once. One, because every measurement that says a
#: heavy job fits this machine is a measurement of one, and the only two that
#: were measured together did not leave room. Raising it is a claim that N
#: peaks fit, and needs that measured first.
#:
#: Per process, which is the scope the memory has.
HEAVY_SLOTS = 1

#: The classes that share the gate. Names rather than strings at the call
#: sites, so that a class spelled two ways is not two classes.
IMPORT = "import"
BACKUP = "backup"
RESTORE = "restore"
REPORT = "report"


class _Gate:
    """Who is inside, and who is waiting, for one event loop."""

    def __init__(self) -> None:
        self.held: Counter[str] = Counter()
        self._waiting: deque[tuple[asyncio.Future[None], str, int | None]] = deque()

    def _admits(self, kind: str, limit: int | None) -> bool:
        if sum(self.held.values()) >= HEAVY_SLOTS:
            return False
        return limit is None or self.held[kind] < limit

    async def acquire(self, kind: str, limit: int | None) -> None:
        # Nobody jumps a queue: a job that could go in at once still waits
        # behind one that asked first.
        if not self._waiting and self._admits(kind, limit):
            self.held[kind] += 1
            return
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        entry = (waiter, kind, limit)
        self._waiting.append(entry)
        try:
            await waiter
        except asyncio.CancelledError:
            if waiter.done() and not waiter.cancelled():
                # Let in and cancelled in the same turn: the place was given
                # and nobody is going to use it.
                self.release(kind)
            else:
                with suppress(ValueError):
                    self._waiting.remove(entry)
                # It may have been the head of the queue, in front of
                # somebody who fits.
                self._admit()
            raise

    def release(self, kind: str) -> None:
        self.held[kind] -= 1
        if not self.held[kind]:
            del self.held[kind]
        self._admit()

    def _admit(self) -> None:
        while self._waiting:
            waiter, kind, limit = self._waiting[0]
            if waiter.done():
                self._waiting.popleft()
                continue
            if not self._admits(kind, limit):
                return
            self._waiting.popleft()
            self.held[kind] += 1
            waiter.set_result(None)


_gates: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _Gate] = weakref.WeakKeyDictionary()


def _gate() -> _Gate:
    """One gate for each event loop, made on first use.

    A waiter is a future and a future belongs to the loop it was made on. A
    worker has one loop for its whole life, and a test suite has many.
    """
    loop = asyncio.get_running_loop()
    gate = _gates.get(loop)
    if gate is None:
        gate = _gates[loop] = _Gate()
    return gate


def occupancy() -> dict[str, int]:
    """Which classes are inside the gate at this moment, and how many of each."""
    return dict(_gate().held)


def give_back() -> None:
    """Return what a heavy section freed to the machine, rather than to the heap.

    A heavy job's memory is mostly strings and buffers, and when it ends they
    are freed -- to the allocator, which keeps the pages. GR-352C watched a
    worker's resident memory stay where its largest import had left it, 329
    MiB of a 512 MiB machine, with nothing in hand: memory no other job could
    be said to be using and none could be promised. `malloc_trim` hands the
    free pages back.

    The C library's own call, where there is one. Anywhere else -- another
    allocator, another platform -- this does nothing, and the worker is what
    it was before: correct, and holding more than it needs.
    """
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        return


def _let_go_of(problem: BaseException) -> None:
    """Drop what a failed section was holding, while the gate is still held.

    An exception carries its traceback, a traceback carries every frame it
    passed through, and a frame carries its locals: the file that was being
    read, the rows that had been parsed. They stay alive for as long as the
    exception does -- which is until the queue has finished recording the
    failure, long after this gate has been let go and the next section has
    started on top of them.

    Measured, not supposed. In the image GR-352 was first measured in, every
    dry run ended in an exception (IMPORT-DEF-020), and the commit that
    followed began with 166 MiB resident where it now begins with 97: the
    69 MiB between them was the dry run's working set, pinned by the failure
    and counted in every import peak that measurement reported.

    The lines of the traceback are untouched, so a log still says where it
    failed. A frame that is still running is skipped.
    """
    seen: set[int] = set()
    link: BaseException | None = problem
    while link is not None and id(link) not in seen:
        seen.add(id(link))
        traceback.clear_frames(link.__traceback__)
        link = link.__cause__ or link.__context__


@asynccontextmanager
async def heavy(kind: str, *, limit: int | None = None) -> AsyncIterator[None]:
    """Hold the gate for the section of a job that holds a payload.

    Taken before the payload is in hand, never after: a job that fetched its
    object and then waited would be waiting with the memory the gate exists to
    keep apart.

    `limit` is how many of this class may be inside at once, for a class that
    is narrower than the gate.

    Let go on every way out -- a return, an exception, a cancellation -- and
    what the section freed is handed back first, so the next one starts from
    what this one gave back and not from what it left behind. A section that
    failed is made to let go of what its frames held before that, or its
    payload would outlive the gate by as long as its exception does.
    """
    gate = _gate()
    asked = time.monotonic()
    await gate.acquire(kind, limit)
    entered = time.monotonic()
    # The evidence that two sections did not overlap is these two lines, in
    # order, in the worker's own log.
    logger.info("heavy: %s entered after waiting %.1fs", kind, entered - asked)
    try:
        yield
    except BaseException as problem:
        _let_go_of(problem)
        raise
    finally:
        try:
            give_back()
        finally:
            gate.release(kind)
            logger.info("heavy: %s left after %.1fs", kind, time.monotonic() - entered)
