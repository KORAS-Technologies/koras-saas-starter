"""The `file.scan` task, declared once (ADR 0013, `secure_files`).

**Here, and not in the worker, for the reason `koras_import/jobs.py` gives:** a
`TaskDefinition` carries no coroutine so that whoever enqueues can hold it
without holding whoever runs it. The worker runs `file.scan`; the upload finalizer and the
reconciliation sweep, both in the worker, enqueue it, and each imports this module rather
than spell the name a second time. The worker image carries this one file (see the
Dockerfile) and the worker binds it by name, loudly: a worker that started with the task
silently unbound would accept a job and never run it.

Standard library and `koras_queue` only, so the worker can carry it.

**Retry.** Tried once. A retry inside the queue is an unbounded loop the sweep is meant to
own, with a back-off that caps at about an hour and never stops. A second automatic attempt
here would count a second `scan_attempts` for what the sweep schedules on its own. A failed
run leaves the file `pending`, which is the state the sweep selects.

**Identity.** The idempotency key is `scan:<file_id>`. The queue turns it into
the job id (`koras_queue.job_id_for`, which hashes in the task name and the
tenant), so two enqueues of one file collapse while one is outstanding and two
tenants can never collide. The key is carried on the envelope so the handler can
refuse a job whose key and payload disagree.

**The payload is one bounded identifier.** `{"file_id": "<uuid>"}`. The tenant is
the envelope's, which the enqueue refuses to leave blank. There is no URL, no
bucket, no key, no host and no credential for a payload to carry, and the queue
refuses a payload key named like a credential in any case.
"""

from __future__ import annotations

import uuid

from koras_queue import RetryPolicy, TaskDefinition

#: The only key a `file.scan` payload may carry.
PAYLOAD_KEY = "file_id"

#: Above the scanner's own per-file wall clock (`FILE_SCAN_TIMEOUT_SECONDS`,
#: 120 s by default, never more than 600 s) plus the object read around it. The
#: queue enforces this by cancelling the coroutine; what normally ends a scan is
#: the scanner's own timeout, which records a hold. A cancelled run has counted
#: its attempt and recorded nothing, and the file stays `pending` for the sweep.
SCAN_TIMEOUT_SECONDS = 660

FILE_SCAN = TaskDefinition(
    name="file.scan",
    summary="Scan one finalized file for malware; clean only on a full release.",
    retry=RetryPolicy(attempts=1),
    timeout_seconds=SCAN_TIMEOUT_SECONDS,
    tags=("secure_files",),
)


def _canonical(value: str, what: str) -> str:
    try:
        if str(uuid.UUID(value)) == value:
            return value
    except (ValueError, AttributeError, TypeError):
        pass
    raise ValueError(f"{what} must be a canonical UUID")


def scan_idempotency_key(file_id: str) -> str:
    """The canonical job identity for one file: `scan:<file_id>`."""
    return f"scan:{_canonical(file_id, 'file_id')}"


def scan_payload(file_id: str) -> dict[str, str]:
    """The whole payload of a `file.scan` job."""
    return {PAYLOAD_KEY: _canonical(file_id, "file_id")}
