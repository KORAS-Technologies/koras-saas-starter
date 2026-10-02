"""How long one run may spend reading a file, and how it is told to stop.

A queue's timeout is not this. It cancels the coroutine that is *waiting* for
the work, which is the only thing a timeout can do to a coroutine, and reading
a file is not waiting: it is the interpreter handling one parser event after
another with no point at which a cancellation can land. GR-352C measured the
consequence rather than assuming it -- a job whose queue timeout had passed
went on parsing, holding everything it had read, until the parse finished.

So the work asks. `WorkBudget.check` is handed to the safety pass and to the
reader, which call it between chunks of the file and every few hundred rows,
and it raises when the time is spent or when somebody has called `cancel`.
Both are ordinary refusals: the run fails with a sentence, exactly as it does
for a file that cannot be read, and nothing is left running behind it.

**What it does not interrupt** is one call into the standard library -- a
chunk through the XML parser, one record through `csv`. Those are bounded by
the safety envelope rather than by this: a chunk is 256 KiB and a cell is
32,000 characters.

The number a worker passes is its own. See
`docs/features/data-import/worker-resource-envelope.md`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .reading import ReadRefused


class BudgetExceeded(ReadRefused):
    """The run spent its time, or was told to stop.

    A `ReadRefused`, so every caller that already answers one answers this:
    the worker records the sentence on the run and the job ends.
    """


class WorkBudget:
    """A deadline and a stop flag, asked from inside the work.

    Safe to share with one worker thread: `cancel` is called from the event
    loop, `check` from the thread doing the reading, and the flag between them
    is a `threading.Event`.
    """

    def __init__(
        self, seconds: float, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if seconds <= 0:
            raise ValueError("a work budget must be a positive number of seconds")
        self.seconds = seconds
        self._clock = clock
        self._deadline = clock() + seconds
        self._stop = threading.Event()

    def cancel(self) -> None:
        """Stop the work at its next check. Idempotent."""
        self._stop.set()

    @property
    def cancelled(self) -> bool:
        return self._stop.is_set()

    def check(self) -> None:
        """Raise if the work should not continue. Cheap enough to call often."""
        if self._stop.is_set():
            raise BudgetExceeded("this import was stopped before it finished")
        if self._clock() > self._deadline:
            raise BudgetExceeded(
                "this import took longer than one run is allowed; "
                "split the file into smaller files and try again"
            )


__all__ = ["BudgetExceeded", "WorkBudget"]
