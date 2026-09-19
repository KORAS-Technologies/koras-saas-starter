"""What the queue promises, including when it hands work to nobody.

The assertions that matter here are the refusals. A queue that accepted a job
with no tenant, or a payload carrying a token, or an enqueue that quietly did
nothing, would let a route answer 202 for work that will never happen -- which
is the exact failure this package was written to remove, and the one a happy
path test cannot see.
"""

from __future__ import annotations

from typing import Any

import pytest
from koras_queue import (
    BoundTask,
    JobEnvelope,
    PayloadRefused,
    QueueError,
    RecordingJobQueue,
    RetryPolicy,
    TaskDefinition,
    job_id_for,
    queue_for,
    worker_functions,
)

SAMPLE = TaskDefinition(
    name="sample.work",
    summary="A task that exists so the seam has something to carry.",
)


def test_a_task_name_must_read_like_a_task_name() -> None:
    """Dotted lower-case, the shape an audit action and a report key use.

    A task name appears in a log line, a Redis key and a failure report long
    after the code that chose it. `doStuff` in any of those is a name nobody
    can search for.
    """
    with pytest.raises(ValueError, match="dotted lower-case"):
        TaskDefinition(name="doStuff", summary="no")
    with pytest.raises(ValueError, match="dotted lower-case"):
        TaskDefinition(name="undotted", summary="no")


def test_a_task_needs_a_summary() -> None:
    """It is what a terminal failure has to describe the work with."""
    with pytest.raises(ValueError, match="needs a summary"):
        TaskDefinition(name="sample.blank", summary="   ")


def test_the_backoff_grows_and_then_stops_growing() -> None:
    policy = RetryPolicy(
        attempts=5, first_delay_seconds=5, backoff=2, max_delay_seconds=30
    )
    assert policy.delay_for(1) == 5
    assert policy.delay_for(2) == 10
    assert policy.delay_for(3) == 20
    # Capped rather than doubling forever: a task retried five times should not
    # be waiting forty minutes for the last one.
    assert policy.delay_for(4) == 30
    assert policy.delay_for(5) == 30


def test_a_retry_policy_that_shortens_is_refused() -> None:
    with pytest.raises(ValueError, match="not a backoff"):
        RetryPolicy(backoff=0.5)
    with pytest.raises(ValueError, match="at least 1"):
        RetryPolicy(attempts=0)


def test_a_job_without_a_tenant_is_refused() -> None:
    """The one refusal that has to happen at the enqueue.

    The database layer raises on a transaction opened without a declaration, so
    a handler that reached this state would fail three minutes later in a
    worker log with nothing identifying the caller. Here, the caller is still
    on the stack.
    """
    with pytest.raises(QueueError, match="without a tenant"):
        JobEnvelope(task="sample.work", tenant_id="", payload={})
    with pytest.raises(QueueError, match="without a tenant"):
        JobEnvelope(task="sample.work", tenant_id="   ", payload={})


def test_a_payload_named_like_a_credential_is_refused() -> None:
    """A payload sits in Redis in plain text and outlives the request.

    The same list the audit envelope refuses, for the same reason and borrowed
    rather than reinvented.
    """
    for name in ("token", "api_key", "user_password", "authorization"):
        with pytest.raises(PayloadRefused, match="named like a credential"):
            JobEnvelope(task="sample.work", tenant_id="t1", payload={name: "x"})


def test_a_payload_carrying_a_document_is_refused() -> None:
    """A job points at work; it does not carry it."""
    with pytest.raises(PayloadRefused, match="flat and JSON-shaped"):
        # Deliberately the wrong type: the refusal is a runtime guard against a
        # caller the type checker never saw, which is every caller reading a
        # request body. Ignored rather than cast, so the test says what it is.
        JobEnvelope(
            task="sample.work",
            tenant_id="t1",
            payload={"rows": [1, 2]},  # type: ignore[dict-item]
        )
    with pytest.raises(PayloadRefused, match="over the"):
        JobEnvelope(
            task="sample.work", tenant_id="t1", payload={"blob": "x" * 20_000}
        )


def test_the_envelope_survives_a_round_trip() -> None:
    envelope = JobEnvelope(
        task="sample.work",
        tenant_id="t1",
        payload={"file_id": "f1", "rows": 12},
        actor_id="u1",
        idempotency_key="run-7",
    )
    again = JobEnvelope.from_dict(envelope.as_dict())
    assert again.task == "sample.work"
    assert again.tenant_id == "t1"
    assert again.payload == {"file_id": "f1", "rows": 12}
    assert again.actor_id == "u1"
    assert again.idempotency_key == "run-7"
    assert again.enqueued_at is not None


def test_an_envelope_from_an_older_release_still_parses() -> None:
    """A job enqueued before a deploy arrives at the worker after it."""
    again = JobEnvelope.from_dict({"task": "sample.work", "tenant_id": "t1"})
    assert again.payload == {}
    assert again.actor_id == ""
    assert again.enqueued_at is None


def test_two_tenants_using_one_key_do_not_collide() -> None:
    """The tenant is inside the hash.

    Without it, two customers importing a file both called `contacts.csv` on
    the same afternoon would share a job id, and the second enqueue would be
    reported as a duplicate of the first -- which is one customer's import
    silently never running.
    """
    first = job_id_for(SAMPLE, "tenant-a", "contacts.csv")
    second = job_id_for(SAMPLE, "tenant-b", "contacts.csv")
    assert first != second
    assert first.startswith("sample.work:")
    assert job_id_for(SAMPLE, "tenant-a", "contacts.csv") == first


@pytest.mark.asyncio
async def test_an_unconfigured_queue_records_and_says_so() -> None:
    """The contract a route reads before answering 202.

    A recording queue that claimed not to be simulated would let a product ship
    a feature that works on a developer machine and does nothing in production.
    """
    queue = queue_for("")
    assert isinstance(queue, RecordingJobQueue)
    assert queue.simulated is True

    result = await queue.enqueue(SAMPLE, tenant_id="t1", payload={"n": 1})
    assert result.simulated is True
    assert result.task == "sample.work"
    assert len(queue.jobs) == 1
    assert queue.jobs[0].tenant_id == "t1"


@pytest.mark.asyncio
async def test_the_recording_queue_refuses_what_the_real_one_would() -> None:
    """Otherwise a payload that works locally fails in production only.

    Validation is on the envelope rather than on the transport precisely so
    both queues refuse the same things.
    """
    queue = queue_for("")
    with pytest.raises(QueueError, match="without a tenant"):
        await queue.enqueue(SAMPLE, tenant_id="")
    with pytest.raises(PayloadRefused):
        await queue.enqueue(SAMPLE, tenant_id="t1", payload={"secret": "s"})


def test_a_configured_url_gives_the_real_queue() -> None:
    queue = queue_for("redis://localhost:6379")
    assert queue.simulated is False


def test_binding_a_task_twice_is_refused_at_import() -> None:
    """A duplicate name means one handler silently shadows the other.

    Every registry in this repository refuses a duplicate key with a traceback
    rather than resolving it, for the same reason: a collision found on a
    developer machine costs a minute, and one found in production costs a
    feature that stopped working for no visible reason.
    """

    async def handler(ctx: dict[str, Any], envelope: JobEnvelope) -> None:
        del ctx, envelope

    with pytest.raises(ValueError, match="bound twice"):
        worker_functions([BoundTask(SAMPLE, handler), BoundTask(SAMPLE, handler)])


def test_worker_functions_carry_the_declared_limits() -> None:
    """A long task declares its own patience rather than raising the ceiling.

    The worker's job timeout is 300 seconds for everything; a validation pass
    over a large file needs more, and every sweep inheriting that would mean a
    hung job holds a worker slot for a quarter of an hour.
    """

    async def handler(ctx: dict[str, Any], envelope: JobEnvelope) -> None:
        del ctx, envelope

    slow = TaskDefinition(
        name="sample.slow",
        summary="Takes a while.",
        retry=RetryPolicy(attempts=5),
        timeout_seconds=900,
    )
    built = worker_functions([BoundTask(slow, handler)])
    assert len(built) == 1
    assert built[0].name == "sample.slow"
    assert built[0].max_tries == 5
    assert built[0].timeout_s == 900


@pytest.mark.asyncio
async def test_a_failing_task_asks_for_the_declared_delay() -> None:
    """The policy is the point: the queue library retries with no delay at all.

    Asserted through the wrapper rather than by reading the policy, because the
    policy being right and the wrapper ignoring it is the failure that would
    otherwise ship.
    """
    from arq.worker import Retry

    attempts: list[int] = []

    async def handler(ctx: dict[str, Any], envelope: JobEnvelope) -> None:
        del envelope
        attempts.append(int(ctx["job_try"]))
        raise RuntimeError("the dependency is down")

    task = TaskDefinition(
        name="sample.flaky",
        summary="Fails.",
        retry=RetryPolicy(attempts=3, first_delay_seconds=4, backoff=2),
    )
    (built,) = worker_functions([BoundTask(task, handler)])
    envelope = JobEnvelope(task="sample.flaky", tenant_id="t1", payload={})

    with pytest.raises(Retry) as first:
        await built.coroutine({"job_try": 1}, envelope.as_dict())
    assert first.value.defer_score == 4000

    with pytest.raises(Retry) as second:
        await built.coroutine({"job_try": 2}, envelope.as_dict())
    assert second.value.defer_score == 8000

    # The last attempt re-raises rather than deferring, so the failure is
    # terminal and visible instead of looping forever.
    with pytest.raises(RuntimeError, match="the dependency is down"):
        await built.coroutine({"job_try": 3}, envelope.as_dict())

    assert attempts == [1, 2, 3]


@pytest.mark.asyncio
async def test_a_handler_asking_for_its_own_deferral_wins() -> None:
    """It knows something the policy does not -- a rate-limit header, say."""
    from arq.worker import Retry

    async def handler(ctx: dict[str, Any], envelope: JobEnvelope) -> None:
        del ctx, envelope
        raise Retry(defer=90)

    task = TaskDefinition(name="sample.polite", summary="Backs off itself.")
    (built,) = worker_functions([BoundTask(task, handler)])
    envelope = JobEnvelope(task="sample.polite", tenant_id="t1", payload={})

    with pytest.raises(Retry) as raised:
        await built.coroutine({"job_try": 1}, envelope.as_dict())
    assert raised.value.defer_score == 90_000


@pytest.mark.asyncio
async def test_the_handler_receives_a_parsed_envelope() -> None:
    """Not a dict. A handler that had to parse would each parse differently."""
    seen: list[JobEnvelope] = []

    async def handler(ctx: dict[str, Any], envelope: JobEnvelope) -> str:
        del ctx
        seen.append(envelope)
        return "done"

    (built,) = worker_functions([BoundTask(SAMPLE, handler)])
    envelope = JobEnvelope(
        task="sample.work", tenant_id="t1", payload={"file_id": "f1"}
    )
    answer = await built.coroutine({"job_try": 1}, envelope.as_dict())

    assert answer == "done"
    assert seen[0].tenant_id == "t1"
    assert seen[0].payload["file_id"] == "f1"
