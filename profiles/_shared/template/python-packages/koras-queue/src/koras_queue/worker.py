"""Turning declarations into the functions the worker runs.

The worker's ``functions`` list is what decides whether an enqueued job has
anywhere to land. Building that list from bound tasks -- rather than by hand --
is what makes "declared but unhandled" and "handled but undeclared"
unrepresentable instead of merely unlikely.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from .queue import JobEnvelope
from .tasks import BoundTask

logger = logging.getLogger("koras.queue")


def worker_functions(bound: Sequence[BoundTask]) -> list[Any]:
    """Build the queue library's function objects from bound tasks.

    Refuses a duplicate name at import, with a traceback that names it, which
    is the convention every registry in this repository follows: a collision
    should be a stack trace on a developer machine rather than a task that
    silently shadows another in production.

    Each task's own timeout and retry count are applied per function, so one
    long task does not raise the ceiling for every short one.
    """
    from arq.worker import func

    seen: dict[str, BoundTask] = {}
    built: list[Any] = []
    for task in bound:
        if task.name in seen:
            raise ValueError(
                f"task {task.name} is bound twice; a duplicate name means one "
                "handler silently shadows the other"
            )
        seen[task.name] = task
        built.append(
            func(
                # The queue library types a worker coroutine as
                # `(ctx, *args, **kwargs)`, because most of its users enqueue
                # positional arguments. Ours takes exactly one argument by
                # construction -- `enqueue` always sends one envelope -- and
                # saying so in the signature is worth more than matching a
                # protocol shaped by a calling convention this package does not
                # use. Narrowed to the call rather than widened at the handler.
                _wrap(task),  # type: ignore[arg-type]
                name=task.name,
                max_tries=task.definition.retry.attempts,
                timeout=task.definition.timeout_seconds,
            )
        )
    return built


def _wrap(task: BoundTask) -> Callable[[dict[str, Any], Mapping[str, Any]], Awaitable[object]]:
    """Parse the envelope, apply the declared backoff, and make the last
    failure loud.

    The queue library retries on its own, immediately and without a policy.
    What this adds is the policy: a delay that grows as declared, and a
    terminal failure that says the task gave up rather than appearing in a log
    as one more exception among many.

    **There is no dead-letter queue.** A destination nothing reads is not
    evidence, and every task that matters owns a row -- an import run, an
    outbox record -- whose status is where a person actually looks. The
    terminal log line names the task, the tenant and the attempt count so that
    row can be found.
    """
    from arq.worker import Retry

    async def run(ctx: dict[str, Any], raw: Mapping[str, Any]) -> object:
        envelope = JobEnvelope.from_dict(raw)
        attempt = int(ctx.get("job_try") or 1)
        try:
            return await task.handler(ctx, envelope)
        except Retry:
            # The handler asked for its own deferral. It knows something this
            # wrapper does not -- a rate-limit header, say -- so it wins.
            raise
        except Exception as error:
            policy = task.definition.retry
            if attempt < policy.attempts:
                delay = policy.delay_for(attempt)
                logger.warning(
                    "task %s for tenant %s failed on attempt %d of %d, "
                    "retrying in %.1fs: %s",
                    task.name,
                    envelope.tenant_id,
                    attempt,
                    policy.attempts,
                    delay,
                    error,
                )
                raise Retry(defer=delay) from error
            logger.error(
                "task %s for tenant %s gave up after %d attempt(s): %s",
                task.name,
                envelope.tenant_id,
                attempt,
                error,
                exc_info=error,
            )
            raise

    run.__name__ = task.name.replace(".", "_")
    run.__qualname__ = run.__name__
    run.__doc__ = task.definition.summary
    return run
