"""Handing work to the worker, from a route.

One queue per process, opened lazily and closed with the application, reached
through a dependency so a route never builds its own. The same shape the Redis
connection for the rate limiter already uses, and for the same reason: a
connection pool built per request is a connection pool leaked per request.

**What a route has to do with the answer.** `Enqueued.simulated` is true when
no Redis is configured, which on a developer machine is most of the time. A
route that answers 202 without reading it is promising work that nothing will
do. Two honest shapes:

    result = await jobs.enqueue(REBUILD_INDEX, tenant_id=tenant.id)
    if result.simulated:
        raise api_error(503, ApiErrorCode.SERVICE_UNAVAILABLE, "...")

or, where the work is genuinely optional, record the row as queued anyway and
let a person see that it never started. What is not acceptable is neither.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from koras_queue import JobQueue, queue_for

from .settings import settings


def job_queue(request: Request) -> JobQueue:
    """The application's queue.

    Built in the lifespan so that `queue_for` is called once and a service
    that never enqueues never opens a connection. Falls back to building one
    if `app.state` has none, which happens in a test that constructs the app
    without running the lifespan -- and which gives a recording queue rather
    than a missing attribute, because a test that fails on `AttributeError`
    tells you nothing about the route it was testing.
    """
    existing = getattr(request.app.state, "jobs", None)
    if existing is not None:
        return existing  # type: ignore[no-any-return]
    return queue_for(settings.redis_url)


JobsDep = Annotated[JobQueue, Depends(job_queue)]
