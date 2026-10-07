"""The `file.finalize` task, declared once (ADR 0013, `secure_files`).

**Here, and not in the worker**, for the reason `koras_queue` gives: a
`TaskDefinition` carries no coroutine, so whoever enqueues can hold it without
holding whoever runs it. The API enqueues it when an upload is confirmed
(`finalize_enqueue.py`); the worker binds it by name, loudly, and a sweep in
the worker runs the same function for any upload whose job was lost.

Standard library and `koras_queue` only, so the worker image can carry this one
file.

**Retry.** Tried once. A failed run leaves the file on its incoming key and not
releasable, which is the state the sweep selects; a second automatic attempt
inside the queue would count a second attempt for what the sweep schedules on
its own, with a back-off.

**Identity.** The idempotency key is `finalize:<file_id>`. The queue turns it
into the job id (`koras_queue.job_id_for`, which hashes in the task name and the
tenant), so two enqueues of one file collapse while one is outstanding and two
tenants can never collide.

**The payload is one bounded identifier.** `{"file_id": "<uuid>"}`. The tenant
is the envelope's. There is no URL, no object key, no bucket and no credential
for a payload to carry, and the queue refuses a payload key named like a
credential in any case.
"""

from __future__ import annotations

import uuid

from koras_queue import RetryPolicy, TaskDefinition

#: The only key a `file.finalize` payload may carry.
PAYLOAD_KEY = "file_id"

#: Above the time to read an object of the hard size ceiling twice (the incoming
#: bytes and the final copy are each hashed) and copy it once. The queue enforces
#: it by cancelling the coroutine; a cancelled run leaves the file on its
#: incoming key, which is not releasable and is what the sweep selects.
FINALIZE_TIMEOUT_SECONDS = 1800

FILE_FINALIZE = TaskDefinition(
    name="file.finalize",
    summary="Copy one uploaded file to a final key and verify it against its claimed SHA-256.",
    retry=RetryPolicy(attempts=1),
    timeout_seconds=FINALIZE_TIMEOUT_SECONDS,
    tags=("secure_files",),
)


def _canonical(value: str, what: str) -> str:
    try:
        if str(uuid.UUID(value)) == value:
            return value
    except (ValueError, AttributeError, TypeError):
        pass
    raise ValueError(f"{what} must be a canonical UUID")


def finalize_idempotency_key(file_id: str) -> str:
    """The canonical job identity for one file: `finalize:<file_id>`."""
    return f"finalize:{_canonical(file_id, 'file_id')}"


def finalize_payload(file_id: str) -> dict[str, str]:
    """The whole payload of a `file.finalize` job."""
    return {PAYLOAD_KEY: _canonical(file_id, "file_id")}
