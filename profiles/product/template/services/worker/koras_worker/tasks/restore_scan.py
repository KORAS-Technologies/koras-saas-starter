"""Asking for a scan of a file a restore has just made (ADR 0013, `secure_files`).

A restore that brings bytes back -- as a new file or as a replacement object under an
existing file -- leaves a `ready` + `pending` row on a final key, and nothing releases a
`pending` file. Waiting for the scan sweep to notice is not enough: the sweep may be narrowed
by `FILE_SCAN_SWEEP_NOT_BEFORE`, and a replaced file is an old file. So the restore asks for
the scan itself, once the row is committed, under the same job identity the finalizer and the
sweep use (`scan:<file_id>`), through the same enqueue function (`core/scan_enqueue.py`).

**It only enqueues.** No scan state is written here, no verdict is decided and nothing
is released. A failed enqueue changes nothing about the file: it stays `pending`, which every
consumer already withholds.

**A failed enqueue is recoverable without the watermark.** `reconcile_restored_scans`
looks at the restores that completed in the last `LOOKBACK_DAYS` and re-asks for the
scan of any restored file that is still `ready` + `pending` and owed an attempt, on the
sweep's own back-off (`scan_sweep.backoff_seconds`). It does not widen the scan sweep:
the sweep keeps its watermark and writes nothing; this is the restore's own follow-up
and is bounded by the restores it made.

**There is no activation check.** With `secure_files` the scanner is mandatory and the product
refuses to start without one, so a restore never has "no scanner" to defer to: it always asks,
and a worker whose scanner is unreachable holds the file (`pending`, withheld) as for any other.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from arq.constants import result_key_prefix
from koras_queue import JobQueue, job_id_for, queue_for
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..settings import settings
from .scan import declaration
from .scan_sweep import BACKOFF_CAP_SECONDS, BACKOFF_FIRST_SECONDS, backoff_seconds

logger = logging.getLogger(__name__)

#: How far back a completed restore is still watched for a lost scan request. Past it a
#: file that is still pending is a file somebody should look at, and nothing here keeps
#: asking for ever.
LOOKBACK_DAYS = 7

#: The most restored files one pass re-asks for.
RECONCILE_LIMIT = 100

#: A scan job that is queued but not yet run has the scan's own start-up to wait for;
#: never-attempted files are not re-asked until this long after they were due.
_GRACE_SECONDS = 60

_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")

#: Restored files still owed a scan. Cross-tenant, on the provisioning context
#: (`restore_requests_select_provisioning`, `files_select_provisioning`); identifiers and
#: scan counters only. The tenant is taken from the same row as the file id and from
#: nothing else.
_OWED = text(
    "select f.id::text as file_id, f.tenant_id::text as tenant_id, f.created_at, "
    " f.scan_attempts, f.scan_attempted_at, r.finished_at, now() as db_now "
    "from public.restore_requests r "
    "join public.files f on f.id = r.restored_file_id and f.tenant_id = r.tenant_id "
    "where r.status = 'completed' and r.restored_file_id is not null "
    " and r.finished_at > now() - make_interval(days => :days) "
    " and f.status = 'ready' and f.scan_status = 'pending' "
    # Only a final key is ever scanned (`upload_window.is_final_key`); a row on any other key
    # would be re-asked for, and refused, for the whole look-back.
    " and f.storage_key ~ '^tenants/[^/]+/[^/]+/[^/]+/final/[^/]+/[^/]+$' "
    # Owed now, in the statement and before the limit: files inside their back-off must not
    # fill the page and starve the ones that are owed. Same wait as `scan_sweep.backoff_seconds`.
    " and (case when f.scan_attempted_at is null "
    "  then greatest(f.created_at + make_interval(secs => :window), r.finished_at) "
    "       + make_interval(secs => :grace) "
    "  else f.scan_attempted_at + make_interval(secs => least("
    "   :first * power(2, least(greatest(f.scan_attempts - 1, 0), 10)), :cap)) end) <= now() "
    "order by coalesce(f.scan_attempted_at, r.finished_at), f.id limit :limit"
)


#: Beyond the scan job's own timeout, for a clock a little apart from the database's.
_IN_FLIGHT_MARGIN_SECONDS = 300


def in_flight_horizon_seconds() -> int:
    """How long after an attempt began a scan of that attempt may still be running.

    The queue cancels the scan job at `SCAN_TIMEOUT_SECONDS`, and every run counts its
    attempt (`scan_attempted_at`) before it reads anything. Past this horizon, no scan that
    read the file's old object can still be about to commit a verdict.
    """
    return int(declaration().SCAN_TIMEOUT_SECONDS) + _IN_FLIGHT_MARGIN_SECONDS


def _enqueue_module() -> Any:  # noqa: ANN401 - a module, reached by name
    """The API's `scan_enqueue`, by name: the one place a file becomes a scan job."""
    try:
        return importlib.import_module("koras_api.core.scan_enqueue")
    except ImportError as error:
        raise RuntimeError("the scan enqueue module is not on this worker's path") from error


def _window_seconds() -> int:
    """The upload window the scanner may not read inside, from the one module that states it."""
    window = importlib.import_module("koras_api.core.upload_window")
    return int(window.SCAN_READ_DELAY_SECONDS)


def defer_seconds(created_at: datetime, now: datetime) -> float:
    """Seconds until the scanner's read gate opens for this row, never negative.

    A replaced file is old and the gate is long open. A restored copy has a new row, so
    the gate is open `SCAN_READ_DELAY_SECONDS` after it was created; a job that ran before
    that would be deferred by the gate itself and read nothing, so it is landed after.
    """
    opens = created_at + timedelta(seconds=_window_seconds())
    return max(0.0, (opens - now).total_seconds())


@dataclass(frozen=True, slots=True)
class ScanRequest:
    """What `request_scan` did, for the log and the tests. `failed` is never an exception."""

    state: Literal["enqueued", "duplicate", "failed"]


async def request_scan(
    queue: JobQueue,
    forget_result: Any,  # noqa: ANN401 - an async callable taking a job id
    *,
    tenant_id: str,
    file_id: str,
    created_at: datetime,
    now: datetime,
) -> ScanRequest:
    """Enqueue the scan job for one restored file. Never raises for a queue or network fault.

    The retained result of an earlier scan of the same file is dropped first, exactly as the
    sweep does: the job identity is fixed (`scan:<file_id>`) and a replaced file has had a
    scan before, so without it a restore inside the result's retention hour would be
    collapsed as a duplicate of the scan of the bytes it replaced.
    """
    contract = declaration()
    key = contract.scan_idempotency_key(file_id)
    try:
        await forget_result(job_id_for(contract.FILE_SCAN, tenant_id, key))
        result = await _enqueue_module().enqueue_scan(
            queue,
            tenant_id=tenant_id,
            file_id=file_id,
            delay_seconds=defer_seconds(created_at, now) + 1.0,
        )
    except Exception as error:  # noqa: BLE001 - the restore has succeeded; reconcile recovers this
        logger.error(
            "the scan job was not enqueued for restored file %s of tenant %s (%s); "
            "it stays pending and the restore reconciliation will ask again",
            file_id,
            tenant_id,
            type(error).__name__,
        )
        return ScanRequest("failed")
    # `enqueue_scan` answers None for a fault it logged itself, and a simulated result for a
    # process with no queue configured: neither is a job on a queue.
    if result is None or result.simulated:
        logger.error("restore scan request: nothing was enqueued; the reconciliation will ask")
        return ScanRequest("failed")
    return ScanRequest("duplicate" if result.duplicate else "enqueued")


def _forgetter(ctx: dict[str, Any]) -> Any:  # noqa: ANN401
    redis = ctx.get("redis")

    async def forget(job_id: str) -> None:
        if redis is not None:
            await redis.delete(result_key_prefix + job_id)

    return forget


async def request_scans_for_restored(
    ctx: dict[str, Any], restored: list[tuple[str, str, datetime]]
) -> list[ScanRequest]:
    """Ask for the scan of each `(tenant_id, file_id, created_at)` a pass restored.

    Called after the rows are committed. Opens its own queue and closes it; with nothing
    restored it opens nothing.
    """
    if not restored:
        return []
    try:
        queue = queue_for(str(settings.redis_url))
    except Exception as error:  # noqa: BLE001 - the files are committed and pending; reconcile asks
        logger.error(
            "restore scan request: no queue (%s); the reconciliation will ask", type(error).__name__
        )
        return [ScanRequest("failed") for _ in restored]
    forget = _forgetter(ctx)
    try:
        now = datetime.now(UTC)
        return [
            await request_scan(
                queue, forget, tenant_id=tenant, file_id=file_id, created_at=created, now=now
            )
            for tenant, file_id, created in restored
        ]
    finally:
        try:
            await queue.aclose()
        except Exception:  # noqa: BLE001 - closing a queue is never the restore's failure
            logger.warning("restore scan request: the queue did not close cleanly")


def owed(row: Any, now: datetime) -> bool:  # noqa: ANN401 - a row of `_OWED`
    """Whether a restored, pending file is owed another request for its scan.

    Never attempted: once its read gate has opened, a grace after it, and not before the
    restore finished. Attempted: after the sweep's own back-off from the last attempt, so a
    scanner that keeps holding the file is not hammered every pass.
    """
    if row.scan_attempted_at is None:
        due = max(row.created_at + timedelta(seconds=_window_seconds()), row.finished_at)
        return bool(due + timedelta(seconds=_GRACE_SECONDS) <= now)
    wait = timedelta(seconds=backoff_seconds(int(row.scan_attempts)))
    return bool(row.scan_attempted_at + wait <= now)


async def reconcile_restored_scans(ctx: dict[str, Any], session: AsyncSession) -> dict[str, int]:
    """Re-ask for the scan of restored files that are still pending and owed one.

    Reads, then enqueues; it writes no row. Its answer is a count for the log.
    """
    counts = {"selected": 0, "enqueued": 0, "duplicate": 0, "failed": 0}
    await session.execute(_PROVISIONING)
    try:
        rows = (
            await session.execute(
                _OWED,
                {
                    "days": LOOKBACK_DAYS,
                    "limit": RECONCILE_LIMIT,
                    "window": _window_seconds(),
                    "grace": _GRACE_SECONDS,
                    "first": BACKOFF_FIRST_SECONDS,
                    "cap": BACKOFF_CAP_SECONDS,
                },
            )
        ).all()
    finally:
        await session.rollback()
    # One request per file: two completed restores of the same file select it twice, and the job
    # identity (`scan:<file_id>`) is one. The payload names the file, never an object, so what
    # the scanner reads is whatever the row names when it runs -- no generation can be obsolete.
    due: list[Any] = []
    seen: set[str] = set()
    for row in rows:
        if row.file_id not in seen and owed(row, row.db_now):
            seen.add(row.file_id)
            due.append(row)
    if not due:
        return counts
    queue = queue_for(str(settings.redis_url))
    forget = _forgetter(ctx)
    try:
        for row in due:
            counts["selected"] += 1
            asked = await request_scan(
                queue,
                forget,
                tenant_id=row.tenant_id,
                file_id=row.file_id,
                created_at=row.created_at,
                now=row.db_now,
            )
            if asked.state in counts:
                counts[asked.state] += 1
            else:
                counts["failed"] += 1
    finally:
        await queue.aclose()
    logger.info(
        "restore scan reconciliation: selected=%d enqueued=%d duplicate=%d failed=%d",
        counts["selected"],
        counts["enqueued"],
        counts["duplicate"],
        counts["failed"],
    )
    return counts
