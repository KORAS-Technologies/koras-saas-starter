"""Handing a finalized file to the scanner (ADR 0013, `secure_files`).

The one place a finalized file becomes a `file.scan` job. The upload finalizer calls it once a
file is on its final key, the reconciliation sweep enqueues the same job under the same
identity (`scan_jobs`), and so does a restore for the file it has just written
(`tasks/restore_scan.py`, which is generated only with `storage_governance`). None of them is a
request: the API never enqueues a scan, because a file is not scannable until the worker has
finalized it.

**It only enqueues.** The payload is `{"file_id": "<uuid>"}` and the tenant is the
envelope's; the identity is `scan:<file_id>` (`scan_jobs`). There is no URL, no object key,
no bucket and no credential in a job, and the queue refuses a payload key named like one in
any case.

**It does not wait.** The upload window has already passed by the time a file is final (the
finalizer defers until `FINALIZE_DELAY_SECONDS`, which is longer than the scanner's own
read gate), so the job is enqueued for now. A job that nevertheless ran early would be
deferred by the run itself, which reads nothing and counts nothing.

**A failed enqueue leaves the file pending.** Nothing is written to the file, the failure is
logged by name only, and the sweep -- the control for exactly this -- picks the file up once
it is due. Standard library and `koras_queue` only, so the worker can carry it.
"""

from __future__ import annotations

import logging

from koras_queue import Enqueued, JobQueue

from .scan_jobs import FILE_SCAN, scan_idempotency_key, scan_payload

logger = logging.getLogger(__name__)


async def enqueue_scan(
    jobs: JobQueue,
    *,
    tenant_id: str,
    file_id: str,
    actor_id: str = "",
    delay_seconds: float | None = None,
) -> Enqueued | None:
    """Enqueue `file.scan` for one finalized file. `None` when the enqueue failed.

    Never raises for a queue or network fault: the file is still `pending` and
    the sweep recovers it. A malformed id is a programming error and does raise.

    `delay_seconds` is for a caller that knows the scanner's read gate has not opened yet (a
    restore's new row, whose `created_at` is now); the finalizer and the sweep enqueue for now.
    """
    key = scan_idempotency_key(file_id)
    payload = scan_payload(file_id)
    try:
        return await jobs.enqueue(
            FILE_SCAN,
            tenant_id=tenant_id,
            payload=payload,
            actor_id=actor_id,
            idempotency_key=key,
            delay_seconds=delay_seconds,
        )
    except Exception as error:  # noqa: BLE001 - the file is final; the sweep recovers this
        logger.error(
            "file.scan was not enqueued for file %s of tenant %s (%s); the sweep will recover it",
            file_id,
            tenant_id,
            type(error).__name__,
        )
        return None
