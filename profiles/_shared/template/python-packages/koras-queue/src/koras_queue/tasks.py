"""What a background task is, and how often it may be tried.

A task is declared once, in a module both the API and the worker can import,
and bound to a handler in the worker. The declaration carries no code, which is
what lets the side that *enqueues* hold it without holding the side that *runs*
it.

The shape follows every other registry in this repository: a frozen dataclass
validated in ``__post_init__`` so a bad declaration is a traceback at import
rather than a 500 for a customer, and a dotted lower-case key so a task name
reads like an audit action or a report key rather than like a function.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

#: The same shape an audit action and a report key use. A task name is read in
#: a log line, a queue key and a failure report, so it is prose-adjacent rather
#: than a Python identifier.
_DOTTED = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

#: What a handler is handed: the worker context arq builds, and the envelope
#: the enqueueing side filled in.
Handler = Callable[[dict[str, Any], "JobEnvelopeLike"], Awaitable[Any]]

#: Structural stand-in so this module does not import ``queue`` and ``queue``
#: can import this one. The real type is ``koras_queue.queue.JobEnvelope``.
JobEnvelopeLike = Any


@dataclass(frozen=True)
class RetryPolicy:
    """How often a failing task is tried again, and how long between tries.

    Declared per task rather than inherited from the queue library's defaults,
    because the defaults are invisible and therefore never argued with. A task
    that talks to a mail server should back off; a task that recomputes
    something from the database should probably not be retried at all.

    ``attempts`` counts the first try. ``attempts=1`` means no retry, which is
    the right answer for anything a person is waiting on and can repeat
    themselves.

    **There is no jitter**, and with more than a handful of simultaneous
    failures that matters: they retry in lockstep and hit the recovering
    dependency together. Adding it is a change to this class alone, and it is
    left out until something has actually been seen to thunder, because an
    untestable default is worse than a stated limit.
    """

    attempts: int = 3
    first_delay_seconds: float = 5.0
    backoff: float = 2.0
    max_delay_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempts is at least 1 -- one try is not a retry")
        if self.first_delay_seconds < 0:
            raise ValueError("first_delay_seconds cannot be negative")
        if self.backoff < 1:
            raise ValueError(
                "backoff below 1 shortens each delay, which is not a backoff"
            )
        if self.max_delay_seconds < self.first_delay_seconds:
            raise ValueError("max_delay_seconds is below first_delay_seconds")

    def delay_for(self, attempt: int) -> float:
        """Seconds to wait before attempt ``attempt + 1``.

        ``attempt`` is 1-based and is what the queue library reports as the try
        number, so the first failure asks for ``delay_for(1)`` and gets
        ``first_delay_seconds``.
        """
        if attempt < 1:
            raise ValueError("attempt is 1-based")
        delay = self.first_delay_seconds * (self.backoff ** (attempt - 1))
        return min(delay, self.max_delay_seconds)


#: Three tries, five seconds apart doubling. Chosen because the first thing to
#: use this queue talks to a mail server, and a mail server that refuses a
#: connection is usually willing twenty seconds later.
DEFAULT_RETRY = RetryPolicy()

#: Tried once and not again. For work a person is waiting on, where a silent
#: second attempt is worse than a visible failure they can repeat.
TRY_ONCE = RetryPolicy(attempts=1)


@dataclass(frozen=True)
class TaskDefinition:
    """One kind of background work, named once.

    Holds no handler on purpose. The API imports this to enqueue; the worker
    imports it to bind. If it carried the coroutine, the API would import the
    worker, and the dependency arrow between a request and a sweep would point
    the wrong way.
    """

    name: str
    summary: str
    retry: RetryPolicy = DEFAULT_RETRY
    #: Overrides the worker's own job timeout for this task alone. A long
    #: import validation can declare the time it needs without every sweep
    #: inheriting the same patience.
    timeout_seconds: int = 300
    #: Free-form labels, for a future operator surface. Nothing reads them.
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not _DOTTED.match(self.name):
            raise ValueError(
                f"task name {self.name!r} must be dotted lower-case, "
                "like 'notifications.dispatch'"
            )
        if not self.summary.strip():
            raise ValueError(
                f"task {self.name} needs a summary -- it is what a failure "
                "report has to describe the work with"
            )
        if self.timeout_seconds < 1:
            raise ValueError(f"task {self.name} needs a positive timeout")


@dataclass(frozen=True)
class BoundTask:
    """A declaration and the coroutine that answers it.

    Kept as one object rather than two parallel lists because two parallel
    lists drift: a declaration with no handler is a job that enqueues and never
    runs, and a handler with no declaration is code nothing can reach. Neither
    is representable here.
    """

    definition: TaskDefinition
    handler: Handler

    @property
    def name(self) -> str:
        return self.definition.name


def names(bound: Mapping[str, BoundTask] | list[BoundTask]) -> list[str]:
    """Every task name in a binding, sorted. For logs and for tests."""
    if isinstance(bound, Mapping):
        return sorted(bound)
    return sorted(task.name for task in bound)
