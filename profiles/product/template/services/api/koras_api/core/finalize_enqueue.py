"""Handing a confirmed upload to the finalizer (ADR 0013, `secure_files`).

The one place an upload becomes a `file.finalize` job. The files route calls it
after the response, so the finalizer is never a request's problem, and the
worker's sweep runs the same function for an upload whose job was lost.

**It only enqueues.** The payload is `{"file_id": "<uuid>"}` and the tenant is
the envelope's; the identity is `finalize:<file_id>` (`finalize_jobs`).

**It does not shorten the upload window.** The signed PUT for a ticket lives
`UPLOAD_URL_SECONDS` and a request begun inside it can run on for a measured
`IN_FLIGHT_BOUND_SECONDS`; the worker may not copy the incoming object to its
final key until `FINALIZE_DELAY_SECONDS` after the row's `created_at`
(`upload_window`). The job is enqueued *now* but deferred until that instant. A
job that nevertheless ran early is deferred by the finalizer itself, which reads
nothing: the delay here only saves the wasted run. It is not what protects the
object -- the final key is.

**A failed enqueue leaves the file not releasable.** Nothing is written to the
file, the failure is logged by name only, and the sweep -- the control for
exactly this -- picks the file up once it is due. A queue with no Redis behind
it (`Enqueued.simulated`) is reported the same way: the work was not done.
"""

from __future__ import annotations

import logging
from datetime import datetime

from koras_queue import Enqueued, JobQueue

from .finalize_jobs import FILE_FINALIZE, finalize_idempotency_key, finalize_payload
from .upload_window import earliest_finalization

logger = logging.getLogger(__name__)

#: Added to the deferral so the job lands just after the gate opens, not on it.
_AFTER_OPEN_SECONDS = 1.0


def defer_seconds(created_at: datetime, now: datetime) -> float:
    """Seconds until this ticket's object may first be finalized, never negative."""
    return max(0.0, (earliest_finalization(created_at) - now).total_seconds()) + _AFTER_OPEN_SECONDS


async def enqueue_finalize(
    jobs: JobQueue,
    *,
    tenant_id: str,
    file_id: str,
    created_at: datetime,
    now: datetime,
    actor_id: str = "",
) -> Enqueued | None:
    """Enqueue `file.finalize` for one confirmed upload. `None` when the enqueue failed.

    Never raises for a queue or network fault: the file is still on its incoming key,
    which nothing releases, and the sweep recovers it. A malformed id is a programming
    error and does raise.
    """
    key = finalize_idempotency_key(file_id)
    payload = finalize_payload(file_id)
    try:
        enqueued = await jobs.enqueue(
            FILE_FINALIZE,
            tenant_id=tenant_id,
            payload=payload,
            actor_id=actor_id,
            idempotency_key=key,
            delay_seconds=defer_seconds(created_at, now),
        )
    except Exception as error:  # noqa: BLE001 - the upload has succeeded; the sweep recovers this
        logger.error(
            "file.finalize was not enqueued for file %s of tenant %s (%s);"
            " the sweep will recover it",
            file_id,
            tenant_id,
            type(error).__name__,
        )
        return None
    if enqueued.simulated:
        logger.warning(
            "file.finalize for file %s of tenant %s was recorded, not run (no queue is configured);"
            " the file stays on its incoming key until the worker's sweep finalizes it",
            file_id,
            tenant_id,
        )
    return enqueued
