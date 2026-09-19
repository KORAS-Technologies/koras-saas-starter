"""Handing work to the worker, from a request.

Before this existed nothing in a KORAS product could enqueue anything. The
worker ran nine sweeps and every one of them was cron; the three request paths
that kept working after the response used FastAPI background tasks, which run
in the API process and die with it. A deploy, a crash or an autoscaler taking
the machine away lost the work silently, and the customer's only evidence was
that the thing they asked for never happened.

The seam here is deliberately narrow. It enqueues, and it says whether the
enqueue was real. It does not schedule, does not fan out, does not subscribe,
and does not know what any task does.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .tasks import TaskDefinition

if TYPE_CHECKING:  # pragma: no cover
    # Imported for the annotation alone. The runtime import lives inside
    # `_connection`, so building the queue costs nothing until it is used.
    from arq.connections import ArqRedis

logger = logging.getLogger("koras.queue")

#: What a payload may hold. A job carries a *reference* -- an id, a key, a
#: count -- and the handler reads the thing itself under the tenant's own
#: session. Anything richer is a document in a queue.
JsonValue = str | int | float | bool | None

#: A payload sits in Redis in plain text, is read by anything with the
#: connection string, and outlives the request that made it. The audit envelope
#: refuses these key names for the same reason and this borrows the list rather
#: than inventing a second one.
_FORBIDDEN_PAYLOAD_KEYS = (
    "token",
    "secret",
    "password",
    "key",
    "credential",
    "authorization",
)

#: Bytes, serialised. A job that needs more than this is carrying the work
#: instead of pointing at it, and the fix is a row somewhere with an id.
MAX_PAYLOAD_BYTES = 16 * 1024


class QueueError(RuntimeError):
    """Something about the enqueue was wrong."""


class PayloadRefused(QueueError):
    """The payload named a credential, held a value nothing can serialise, or
    was too large. Never retried -- it will be refused again."""


@dataclass(frozen=True)
class JobEnvelope:
    """What every enqueued job carries, whatever the task.

    **Every job names a tenant, and a blank one is refused.** Not a
    convenience: the database layer raises on a transaction opened without a
    declaration, and a handler with no tenant has nothing to declare. The
    refusal is here, at the enqueue, because that is where a caller still has
    the context to fix it -- three minutes later in a worker log it is an
    anonymous failure.

    An estate-wide enqueued job has no representation, deliberately. Every
    estate-wide thing this repository does today is a cron sweep running on the
    provisioning context. If one ever needs enqueueing, the answer is a scope
    field on this envelope and a handler that declares provisioning -- not a
    blank tenant sliding through.
    """

    task: str
    tenant_id: str
    payload: Mapping[str, JsonValue]
    #: Who asked. Empty for work the system started on its own.
    actor_id: str = ""
    #: What the caller promised was unique about this request. Empty when the
    #: caller made no such promise.
    idempotency_key: str = ""
    enqueued_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id.strip():
            raise QueueError(
                f"task {self.task} was enqueued without a tenant; a handler "
                "with no tenant cannot open a transaction"
            )
        for name, value in self.payload.items():
            lowered = name.lower()
            if any(word in lowered for word in _FORBIDDEN_PAYLOAD_KEYS):
                raise PayloadRefused(
                    f"payload key {name!r} on task {self.task} is named like a "
                    "credential; a queue is not a secret store"
                )
            if not isinstance(value, str | int | float | bool | type(None)):
                raise PayloadRefused(
                    f"payload key {name!r} on task {self.task} holds "
                    f"{type(value).__name__}; a payload is flat and JSON-shaped"
                )
        encoded = json.dumps(dict(self.payload), sort_keys=True).encode()
        if len(encoded) > MAX_PAYLOAD_BYTES:
            raise PayloadRefused(
                f"payload for task {self.task} is {len(encoded)} bytes, over "
                f"the {MAX_PAYLOAD_BYTES}-byte limit; enqueue a reference to "
                "the work rather than the work"
            )

    def as_dict(self) -> dict[str, Any]:
        """The wire form. A plain dict, because the queue library pickles what
        it is given and a pickled dataclass is a deploy away from a class that
        no longer matches."""
        return {
            "task": self.task,
            "tenant_id": self.tenant_id,
            "payload": dict(self.payload),
            "actor_id": self.actor_id,
            "idempotency_key": self.idempotency_key,
            "enqueued_at": (self.enqueued_at or datetime.now(UTC)).isoformat(),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> JobEnvelope:
        """Parse the wire form, on the worker side.

        A job enqueued by an older release can arrive at a newer worker, so a
        missing optional field reads as its default rather than raising.
        """
        stamped = raw.get("enqueued_at")
        return cls(
            task=str(raw["task"]),
            tenant_id=str(raw["tenant_id"]),
            payload=dict(raw.get("payload") or {}),
            actor_id=str(raw.get("actor_id") or ""),
            idempotency_key=str(raw.get("idempotency_key") or ""),
            enqueued_at=datetime.fromisoformat(stamped) if stamped else None,
        )


@dataclass(frozen=True)
class Enqueued:
    """What the caller learns, and it is deliberately not "it worked".

    ``simulated`` is true when there is no queue configured and the job was
    recorded rather than handed over. A route that cannot proceed without real
    background execution reads it and refuses, rather than answering 202 for
    work nothing will do.

    ``duplicate`` is true when the idempotency key had already been enqueued.
    That is a success -- the work is in hand -- and it is reported separately
    because a caller counting jobs would otherwise count it twice.
    """

    task: str
    job_id: str
    simulated: bool = False
    duplicate: bool = False


def job_id_for(task: TaskDefinition, tenant_id: str, idempotency_key: str) -> str:
    """The deduplicating job id for a keyed enqueue.

    The tenant is inside the hash, so two tenants using the same key -- an
    order number, a filename -- do not collide and silently drop one another's
    work.
    """
    digest = hashlib.sha256(
        f"{task.name}\0{tenant_id}\0{idempotency_key}".encode()
    ).hexdigest()
    return f"{task.name}:{digest[:32]}"


@runtime_checkable
class JobQueue(Protocol):
    """Somewhere to put work.

    Mirrors the mail sender protocol next door, including the awkward part:
    ``simulated`` is on the queue as well as on the result, so a caller can ask
    before it does anything expensive.
    """

    @property
    def simulated(self) -> bool: ...

    async def enqueue(
        self,
        task: TaskDefinition,
        *,
        tenant_id: str,
        payload: Mapping[str, JsonValue] | None = None,
        actor_id: str = "",
        idempotency_key: str = "",
        delay_seconds: float | None = None,
    ) -> Enqueued: ...

    async def aclose(self) -> None: ...


class RecordingJobQueue:
    """Records instead of enqueueing, and says so every time.

    For tests, and for a developer machine with no Redis. It is *not* the
    graceful-degradation case the rate limiter has: a rate limiter that cannot
    reach Redis should let the request through, and a queue that cannot reach
    Redis has lost the work. So every call logs a warning and every result says
    ``simulated``. Dropping work quietly is the failure this whole seam exists
    to stop; dropping it loudly is a development convenience.
    """

    def __init__(self) -> None:
        self.jobs: list[JobEnvelope] = []

    @property
    def simulated(self) -> bool:
        return True

    async def enqueue(
        self,
        task: TaskDefinition,
        *,
        tenant_id: str,
        payload: Mapping[str, JsonValue] | None = None,
        actor_id: str = "",
        idempotency_key: str = "",
        delay_seconds: float | None = None,
    ) -> Enqueued:
        del delay_seconds
        envelope = JobEnvelope(
            task=task.name,
            tenant_id=tenant_id,
            payload=payload or {},
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
        self.jobs.append(envelope)
        job_id = (
            job_id_for(task, tenant_id, idempotency_key)
            if idempotency_key
            else f"{task.name}:recorded:{len(self.jobs)}"
        )
        logger.warning(
            "no queue configured: task %s for tenant %s was recorded, not run",
            task.name,
            tenant_id,
        )
        return Enqueued(task=task.name, job_id=job_id, simulated=True)

    async def aclose(self) -> None:
        return None


class ArqJobQueue:
    """The real one.

    The connection pool is opened on first use rather than in the constructor,
    so building the queue is synchronous and a service that never enqueues
    never connects. One lock around the opening, because two concurrent first
    requests would otherwise build two pools and leak one.
    """

    def __init__(self, redis_url: str) -> None:
        if not redis_url:
            raise QueueError("ArqJobQueue needs a Redis URL; use queue_for()")
        self._redis_url = redis_url
        self._pool: ArqRedis | None = None
        self._lock: Any = None

    @property
    def simulated(self) -> bool:
        return False

    async def _connection(self) -> ArqRedis:
        import asyncio

        from arq.connections import RedisSettings, create_pool

        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._pool is None:
                self._pool = await create_pool(
                    RedisSettings.from_dsn(self._redis_url)
                )
        return self._pool

    async def enqueue(
        self,
        task: TaskDefinition,
        *,
        tenant_id: str,
        payload: Mapping[str, JsonValue] | None = None,
        actor_id: str = "",
        idempotency_key: str = "",
        delay_seconds: float | None = None,
    ) -> Enqueued:
        """Hand one job over.

        The envelope is validated before the connection is touched, so a
        payload naming a credential is refused without a round trip.

        **Idempotency is the queue library's job id, and it is not eternal.**
        A keyed enqueue uses a deterministic id, and the queue refuses a second
        job with an id it already holds -- while it holds it. Once the job has
        run and its result has expired, the same key enqueues again. That is
        the right behaviour for "do not run this twice at once" and the wrong
        behaviour for "never run this twice"; a caller needing the second one
        needs a row in the database, not a key here.
        """
        envelope = JobEnvelope(
            task=task.name,
            tenant_id=tenant_id,
            payload=payload or {},
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
        pool = await self._connection()
        job_id = (
            job_id_for(task, tenant_id, idempotency_key) if idempotency_key else None
        )
        job = await pool.enqueue_job(
            task.name,
            envelope.as_dict(),
            _job_id=job_id,
            _defer_by=delay_seconds,
        )
        if job is None:
            # Only reachable with a job id, and it means the id is already
            # held. The work is in hand; this is not a failure.
            logger.info(
                "task %s for tenant %s was already enqueued under the same key",
                task.name,
                tenant_id,
            )
            return Enqueued(
                task=task.name, job_id=job_id or "", duplicate=True
            )
        return Enqueued(task=task.name, job_id=job.job_id)

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None


def queue_for(redis_url: str) -> JobQueue:
    """A queue for this configuration, and never an exception.

    Mirrors the mail package's sender factory: an unconfigured service starts,
    runs, and tells you what it is doing instead of failing at import. The
    difference from mail is what "unconfigured" costs, which is why the
    recording queue warns on every call and the result says ``simulated``.
    """
    if not redis_url:
        return RecordingJobQueue()
    return ArqJobQueue(redis_url)
