"""Background work a request can ask for.

The KORAS worker has always run scheduled sweeps. What it could not do, until
this package stopped being a one-line comment, is accept work *when something
happens* -- so every feature that needed it either used FastAPI background
tasks, which die with the process, or added a cron job that polls a table for
things to do.

Three parts, and nothing else:

``TaskDefinition``
    A name, a summary, a retry policy and a timeout. Declared in a module both
    the API and the worker import. It holds no coroutine, which is what keeps
    the API from importing the worker.

``JobQueue``
    ``queue_for(redis_url)`` gives one. It enqueues, and it tells you whether
    the enqueue was real. With no Redis configured it records, warns, and
    answers ``simulated`` -- because a queue that quietly drops work is the
    thing this package exists to remove.

``worker_functions``
    Turns bound tasks into what the worker runs, applying each task's own
    retry policy and timeout, and refusing a duplicate name at import.

Adding a task is three edits and no new machinery::

    # somewhere both sides import
    REBUILD_INDEX = TaskDefinition(
        name="search.rebuild_index",
        summary="Rebuild one tenant's search index after a bulk change.",
        retry=RetryPolicy(attempts=5, first_delay_seconds=10),
        timeout_seconds=900,
    )

    # services/worker/koras_worker/tasks/product.py
    PRODUCT_TASKS: list[BoundTask] = [BoundTask(REBUILD_INDEX, rebuild_index)]

    # in a route
    await jobs.enqueue(REBUILD_INDEX, tenant_id=tenant.id, payload={"since": iso})

Two things the worker's own configuration decides, and they are worth knowing
before promising anyone anything. It polls every five seconds rather than twice
a second, so an enqueued job starts within about five seconds and not sooner;
that was a deliberate trade recorded as R-018, where polling twice a second
cost 170,000 Redis commands a day on an idle platform. And it runs at most ten
jobs at once, so a burst queues rather than fanning out.
"""

from .queue import (
    MAX_PAYLOAD_BYTES,
    ArqJobQueue,
    Enqueued,
    JobEnvelope,
    JobQueue,
    JsonValue,
    PayloadRefused,
    QueueError,
    RecordingJobQueue,
    job_id_for,
    queue_for,
)
from .tasks import (
    DEFAULT_RETRY,
    TRY_ONCE,
    BoundTask,
    Handler,
    RetryPolicy,
    TaskDefinition,
    names,
)
from .worker import worker_functions

__all__ = [
    "DEFAULT_RETRY",
    "MAX_PAYLOAD_BYTES",
    "TRY_ONCE",
    "ArqJobQueue",
    "BoundTask",
    "Enqueued",
    "Handler",
    "JobEnvelope",
    "JobQueue",
    "JsonValue",
    "PayloadRefused",
    "QueueError",
    "RecordingJobQueue",
    "RetryPolicy",
    "TaskDefinition",
    "job_id_for",
    "names",
    "queue_for",
    "worker_functions",
]
