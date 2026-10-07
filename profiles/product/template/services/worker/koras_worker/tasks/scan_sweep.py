"""The scan reconciliation sweep (ADR 0013, `secure_files`).

**What it is for.** The upload finalizer enqueues `file.scan` the moment a file reaches its
final key, and that can be lost: the queue unreachable, a worker restarted between the swap
and the enqueue, a job that failed or was interrupted. Every one of those leaves the file
`pending`. This sweep finds files that are still `pending` on a final key and due, and puts
the *same* `file.scan` job back on the *same* queue under the same identity. It is a safety
net, not a second scanner:

- it **writes no scan state**. There is no `update`, `insert` or `delete` in this
  file, and a static test holds that. Every change to a file goes through the
  worker's `file.scan`, whose transitions are the guarded ones.
- it creates **no queue, worker or service**. It is one cron entry in the
  existing worker.
- it **never decides a verdict** and never releases anything.
- it **never touches an incoming key**: those are the finalizer's own sweep
  (`tasks/finalize.py`), and the scanner reads only a final key.

**It is always on.** A product with `secure_files` has a scanner by construction, so the
sweep has no enable switch. `FILE_SCAN_SWEEP_NOT_BEFORE`, an RFC 3339 instant, can only
*narrow* it: the sweep then selects only files created at or after it, which is how an
operator works through a backlog in stages. Absent, it selects everything from the
beginning. It cannot release a file or skip a scan; a file it does not select stays
`pending`, which is withheld.

**Selection** (cross-tenant reads on the provisioning context, through
`files_select_provisioning`; they select identifiers and the due time, nothing else):

    status = 'ready' and scan_status = 'pending' and a final key
    and created_at >= NOT_BEFORE                 (when set)
    and size_bytes <= FILE_SCAN_MAX_BYTES        (a larger file cannot change its answer)
    and due_at <= now

`due_at` is when the file is next owed an attempt:

- never attempted: `created_at + 16 min (the upload window) + 5 min`. The grace is
  one sweep interval, so the sweep does not race the finalizer's own hand-off. (A file on a
  final key has normally been attempted already, by the finalizer, which counts its attempt
  in the same column; its due time is then that attempt's back-off.)
- attempted: `scan_attempted_at + min(12 min * 2^(attempts - 1), 1 h)`. The first
  retry is 12 minutes after the last attempt began, which is longer than the
  queue's own 660 s job timeout, so a retry can never overlap a run still in
  flight. Then 24, 48 and 60 minutes, and 60 for ever: the back-off caps at an
  hour and **never stops**. Nothing here compares attempts with a limit, so a file
  that has reached `FILE_SCAN_MAX_ATTEMPTS` (where `scan_exhausted` was written,
  once, by the transition) is selected exactly as before.

**Tenant fairness.** One tenant's files must not use all the
slots of a run. Selection is therefore by tenant, not by the global due order:

1. *Who goes first.* The tenant that owns the oldest due file. A tenant that has been
   served has moved its files' `due_at` forward, so it stops being first and the one
   waiting longest takes its place: the rotation needs no stored cursor, is the same
   for the same data, and no tenant with a due file can stay behind for ever.
2. *Which tenants.* Those with at least one due file, in tenant-id order from the
   first, wrapping around, among the first `MAX_TENANTS_PER_RUN` tenants that hold a
   pending file. Found by an index skip scan, one probe per tenant, never a sort of
   the pending set and never a read of a tenant's not-yet-due files.
3. *How many each.* A page holds at most `FILE_SCAN_SWEEP_BATCH_SIZE` files, split
   evenly over the tenants still open (at least one each), oldest due first within
   a tenant. A tenant that returned fewer than its share has nothing more due and
   closes; the others go on to the next page, so spare capacity goes to whoever
   still has work and a single tenant still gets the whole run. A page's files are
   enqueued round-robin across tenants.

The most one run enqueues is bounded: `FILE_SCAN_SWEEP_BATCH_SIZE` per page and
`FILE_SCAN_SWEEP_MAX_BATCHES` pages per run. A run that hits the bound stops; the next
tick resumes by selection, because a file that has run has moved its own `due_at`,
and one still queued is deduplicated by the queue.

**Bounded reads.** Every read is an index range read of a few rows: two
partial indexes (migration `00041`) on the due time itself, as an immutable
expression, one led by it and one by the tenant. No page sorts the pending set. The
expression below must stay the same text as the index's, or the planner cannot use
it; `tests/integration/test_scan_sweep_real.py` fails when it does not.

**Tenant safety.** The enqueue takes the tenant from the same row as the file id
and from nothing else, and the handler re-reads the file under that tenant's
forced RLS with the tenant in the predicate. A file id cannot be paired with
another tenant's envelope from here, and if it were the handler finds no row.

**The retained result.** The queue library refuses to enqueue a job id it still
holds a *result* for, for `keep_result` (an hour by default), and the identity of
a scan is fixed (`scan:<file_id>`). Without this, a run that finished at minute 0
would silently turn the minute-12 re-enqueue into a "duplicate". A file that is
selected is by definition due, so any result retained for it is stale, and it is
dropped before the enqueue. A job that is still *queued* is not touched, so a
genuine duplicate still collapses.
"""

from __future__ import annotations

import importlib
import logging
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from typing import Any, Literal

from arq.constants import result_key_prefix
from koras_queue import JobQueue, job_id_for, queue_for
from pydantic import Field, ValidationError, field_validator
from pydantic_settings import SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from ..scanning.config import MAX_SCAN_BYTES, scanner_active
from ..settings import SweepSettings, settings
from .scan import declaration

logger = logging.getLogger(__name__)

#: The sweep's cadence, stated once for the cron entry and the grace below.
SWEEP_INTERVAL_MINUTES = 5

#: Not due until the upload window has surely closed, plus one sweep interval.
_UNATTEMPTED_GRACE_SECONDS = SWEEP_INTERVAL_MINUTES * 60

#: First retry delay, and the cap. 720 s exceeds the queue's 660 s job timeout.
BACKOFF_FIRST_SECONDS = 720
BACKOFF_CAP_SECONDS = 3600

#: The exponent is clamped so the arithmetic never overflows however many attempts.
_MAX_DOUBLINGS = 10

#: The most tenants one run steps over while looking for those with an owed file. Each
#: costs two index lookups, so this bounds the discovery however many tenants hold pending
#: files. A tenant beyond it is not forgotten: the owner of the oldest owed file is always
#: first (see the module), so whoever has waited longest is reached whatever its id.
MAX_TENANTS_PER_RUN = 500

_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")

#: The pending predicate is the indexes' own, including the fixed scan ceiling: a file above
#: it is held `over_ceiling` for ever, so it is kept out of the indexes and never walked.
#: `file_scan_max_bytes` can lower the ceiling further (a filter), never raise it.
_PENDING = f"status = 'ready' and scan_status = 'pending' and size_bytes <= {MAX_SCAN_BYTES}"


def due_expression(unattempted_seconds: int) -> str:
    """When a pending file is next owed an attempt, as SQL, in UTC.

    **This text is also the definition of the indexes in migration `00041`**, so it is
    written to be immutable (`AT TIME ZONE 'UTC'` and plain numbers; adding an interval
    to a `timestamptz` is only stable) and its constants are inlined, never bound: an
    expression index is used only for the same expression. A change here is a migration.
    """
    return (
        "(case when scan_attempted_at is null "
        f"then (created_at at time zone 'UTC') + make_interval(secs => {int(unattempted_seconds)}) "
        "else (scan_attempted_at at time zone 'UTC') + make_interval(secs => least("
        f"{BACKOFF_FIRST_SECONDS} * power(2, least(greatest(scan_attempts - 1, 0), "
        f"{_MAX_DOUBLINGS})), "
        f"{BACKOFF_CAP_SECONDS})) end)"
    )


@cache
def _due() -> str:
    return due_expression(_window_seconds() + _UNATTEMPTED_GRACE_SECONDS)


#: A final key (`tenants/<t>/<cat>/<file>/final/<generation>/<name>`), the SQL form of
#: `upload_window.is_final_key`. Only such a key is ever scanned.
_FINAL_SHAPE = "~ '^tenants/[^/]+/[^/]+/[^/]+/final/[^/]+/[^/]+$'"


@cache
def _owed(alias: str = "files") -> str:
    """The test for "this pending file is owed an attempt now, and this sweep may have it".

    `due >= :due_from` is the watermark again, in a form the index can use. A file created
    at or after the watermark is due after it (its due time is its creation or last attempt
    plus a positive wait), so no such file is excluded by it; and a file created before the
    watermark and long since due is excluded without being read, instead of being read and
    discarded by `created_at` on every run. `created_at >= :not_before` remains the test
    that decides, so the extra bound can only skip rows, never admit one.

    **A key that is not a final key is never owed** (the runtime holds such a row without
    counting an attempt, so its due time never moves, and selecting it on every run would
    spend the oldest-due slots on rows that can never be scanned and starve the rest). An
    incoming key is the finalizer's; any other shape is not one the scanner reads. The same
    predicate as the runtime's (`upload_window.is_final_key`), and only ever a further
    exclusion. `alias` names the `files` relation of the enclosing query.
    """
    return (
        f"{_due()} <= :now and {_due()} >= :due_from "  # noqa: S608 - constants and a fixed alias
        "and created_at >= :not_before and size_bytes <= :max_bytes "
        f"and {alias}.storage_key {_FINAL_SHAPE}"
    )


@cache
def _first_owner_sql() -> str:
    """The tenant of the oldest owed file: the first rows of the global due index."""
    return (
        "select tenant_id::text as tenant_id from public.files "  # noqa: S608 - constants only
        f"where {_PENDING} and {_owed()} "
        f"order by {_due()}, id limit 1"
    )


@cache
def _tenants_sql(*, wrapped: bool) -> str:
    """Tenants that have an owed file, in id order: one index probe per tenant, at most `:limit`.

    The walk steps from each tenant id to the next one that has any pending file, a lookup
    on the leading column of the tenant index, so it costs the same however many files
    a tenant holds or how many are not yet due. Each tenant found is then asked once
    whether it has an owed file (a range read of its own index entries). `wrapped` is the
    part of the circle before the first tenant.
    """
    seed = "tenant_id < cast(:start as uuid)" if wrapped else "tenant_id >= cast(:start as uuid)"
    step = "and f.tenant_id < cast(:start as uuid) " if wrapped else ""
    return (
        "with recursive walk(tenant_id, n) as ("  # noqa: S608 - constants only
        f" select (select tenant_id from public.files where {_PENDING} and {seed} "
        "  order by tenant_id limit 1), 1"
        " union all"
        f" select (select f.tenant_id from public.files f where {_PENDING} "
        f"  and f.tenant_id > w.tenant_id {step}order by f.tenant_id limit 1), w.n + 1"
        " from walk w where w.tenant_id is not null and w.n < :limit"
        ") select w.tenant_id::text as tenant_id from walk w "
        "where w.tenant_id is not null and exists ("
        f" select 1 from public.files f where {_PENDING} and f.tenant_id = w.tenant_id "
        f"  and {_owed('f')}) order by w.n"
    )


@cache
def _page_sql() -> str:
    """Up to `:share` owed files for each named tenant, after that tenant's own cursor.

    Identifiers and the due time only; `files_select_provisioning` admits the read and
    nothing here names a column that holds a key, a name or a digest.
    """
    return (
        "select f.id::text as id, f.tenant_id::text as tenant_id, f.due_at as due_at "  # noqa: S608
        "from unnest(cast(:tenants as uuid[]), cast(:after_due as timestamp[]), "
        "            cast(:after_id as uuid[])) as t(tenant_id, after_due, after_id) "
        "cross join lateral ("
        f" select id, tenant_id, {_due()} as due_at from public.files "
        f" where {_PENDING} and tenant_id = t.tenant_id and {_owed()} "
        f"  and (t.after_due is null or ({_due()}, id) > (t.after_due, t.after_id)) "
        f" order by {_due()}, id limit :share"
        ") f"
    )


class ScanSweepSettings(SweepSettings):
    """Read when the sweep runs, so a test needs no import-time environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    #: The sweep re-enqueues scans, so it needs a scanner that can answer: with backend
    #: `none` it enqueues nothing (and a product with the capability does not start).
    file_scan_backend: Literal["none", "clamd"] = "none"
    #: Optional, and only ever narrowing. Files created before it are not selected. Absent,
    #: the sweep selects everything from the beginning.
    file_scan_sweep_not_before: datetime | None = None
    file_scan_sweep_batch_size: int = Field(default=50, ge=1, le=500)
    file_scan_sweep_max_batches: int = Field(default=4, ge=1, le=20)
    file_scan_max_bytes: int = Field(default=MAX_SCAN_BYTES, gt=0, le=MAX_SCAN_BYTES)

    @field_validator("file_scan_sweep_not_before", mode="before")
    @classmethod
    def _an_explicit_instant_with_an_offset(cls, value: object) -> object:
        """RFC 3339 with `T` and `Z` or an offset, or a timezone-aware datetime. Nothing looser.

        `"0"` would parse as 1970 and a bare date or naive time has no defined zone;
        each would silently widen or shift the activation point.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("FILE_SCAN_SWEEP_NOT_BEFORE must carry a timezone")
            return value
        if isinstance(value, str) and _RFC3339.match(value.strip()):
            return value.strip()
        raise ValueError(
            "FILE_SCAN_SWEEP_NOT_BEFORE must be an RFC 3339 instant, e.g. 2026-10-05T00:00:00Z"
        )


_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([Zz]|[+-]\d{2}:\d{2})$")


@dataclass(frozen=True, slots=True)
class DueFile:
    file_id: str
    tenant_id: str
    #: UTC, naive: the SQL computes it in `timestamp`, which is what the indexes hold.
    due_at: datetime


@dataclass(frozen=True, slots=True)
class SweepReport:
    #: `scanner_inactive` (nothing could scan what was enqueued) or `ran`.
    state: str
    selected: int = 0
    enqueued: int = 0
    duplicate: int = 0
    failed: int = 0
    pages: int = 0
    tenants: int = 0


@dataclass(slots=True)
class FairCursor:
    """Where a run is in its tenant-fair walk. One per run; `select_due` advances it."""

    #: Tenants that may still have due files, in the order they are served; `None`
    #: until the first page discovers them.
    open: list[str] | None = None
    #: Each tenant's last row, so its next page continues after it.
    after: dict[str, DueFile] = field(default_factory=dict)
    #: Every tenant that took part.
    seen: set[str] = field(default_factory=set)

    @property
    def exhausted(self) -> bool:
        return self.open is not None and not self.open


def backoff_seconds(attempts: int) -> int:
    """The wait after an attempt count, for the tests and the docs. SQL computes the same."""
    doublings = min(max(attempts - 1, 0), _MAX_DOUBLINGS)
    return int(min(BACKOFF_FIRST_SECONDS * (2**doublings), BACKOFF_CAP_SECONDS))


#: "From the beginning": what an absent `FILE_SCAN_SWEEP_NOT_BEFORE` means.
_BEGINNING = datetime(1970, 1, 1, tzinfo=UTC)


def _window_seconds() -> int:
    """The upload window the scanner may not read inside, from the one module that states it."""
    window = importlib.import_module("koras_api.core.upload_window")
    return int(window.SCAN_READ_DELAY_SECONDS)


def _utc(moment: datetime) -> datetime:
    """A naive UTC time, which is what the due expression is compared with."""
    return moment.astimezone(UTC).replace(tzinfo=None)


async def _fair_order(
    session: Any,  # noqa: ANN401
    params: dict[str, Any],
) -> list[str]:
    """Tenants with a due file, the owner of the oldest first, wrapping around the id space."""
    first = (await session.execute(text(_first_owner_sql()), params)).scalar()
    if first is None:
        return []
    params = {**params, "start": first}
    ordered = [
        r[0] for r in (await session.execute(text(_tenants_sql(wrapped=False)), params)).all()
    ]
    room = params["limit"] - len(ordered)
    if room > 0:
        params = {**params, "limit": room}
        ordered += [
            r[0] for r in (await session.execute(text(_tenants_sql(wrapped=True)), params)).all()
        ]
    return ordered


async def select_due(
    session: Any,  # noqa: ANN401 - an open session
    *,
    config: ScanSweepSettings,
    now: datetime,
    cursor: FairCursor,
) -> list[DueFile]:
    """One tenant-fair page of files owed an attempt. A read; the transaction is rolled back.

    At most `FILE_SCAN_SWEEP_BATCH_SIZE` files, shared evenly by the open tenants
    (see the module). The cursor records who is still open and where each tenant stopped.
    """
    if cursor.exhausted:
        return []
    not_before = config.file_scan_sweep_not_before or _BEGINNING
    params: dict[str, Any] = {
        "now": _utc(now),
        "not_before": not_before,
        "due_from": _utc(not_before),
        "max_bytes": config.file_scan_max_bytes,
        "limit": MAX_TENANTS_PER_RUN,
    }
    # A group of tenants can come up empty (their files were served since they were
    # listed); the next group is read in the same call, so a page is empty only when no
    # open tenant has anything left. Each pass closes at least one tenant, so it ends.
    while not cursor.exhausted:
        page = await _read_group(session, config=config, params=params, cursor=cursor)
        if page:
            return page
    return []


async def _read_group(
    session: Any,  # noqa: ANN401
    *,
    config: ScanSweepSettings,
    params: dict[str, Any],
    cursor: FairCursor,
) -> list[DueFile]:
    """The next group of open tenants (at most a page's worth) and their share of the page."""
    batch = config.file_scan_sweep_batch_size
    try:
        await session.execute(_PROVISIONING)
        if cursor.open is None:
            cursor.open = await _fair_order(session, params)
        chosen, waiting = cursor.open[:batch], cursor.open[batch:]
        if not chosen:
            return []
        share = max(1, batch // len(chosen))
        rows = (
            (
                await session.execute(
                    text(_page_sql()),
                    {
                        **params,
                        "tenants": chosen,
                        "after_due": [
                            cursor.after[t].due_at if t in cursor.after else None for t in chosen
                        ],
                        "after_id": [
                            cursor.after[t].file_id if t in cursor.after else None for t in chosen
                        ],
                        "share": share,
                    },
                )
            )
            .mappings()
            .all()
        )
    finally:
        await session.rollback()

    by_tenant: dict[str, list[DueFile]] = defaultdict(list)
    for r in rows:
        by_tenant[r["tenant_id"]].append(DueFile(r["id"], r["tenant_id"], r["due_at"]))
    still_open: list[str] = []
    for tenant in chosen:
        got = by_tenant.get(tenant, [])
        if got:
            cursor.after[tenant] = got[-1]
            cursor.seen.add(tenant)
        if len(got) == share:
            still_open.append(tenant)  # it may have more; one that came up short has not
    cursor.open = waiting + still_open
    # Round-robin, so the queue works the tenants in turn rather than one after another.
    ordered: list[DueFile] = []
    for rank in range(share):
        for tenant in chosen:
            if rank < len(by_tenant.get(tenant, [])):
                ordered.append(by_tenant[tenant][rank])
    return ordered


async def sweep(
    session: Any,  # noqa: ANN401
    queue: JobQueue,
    forget_result: Callable[[str], Awaitable[None]],
    *,
    config: ScanSweepSettings,
    now: datetime,
) -> SweepReport:
    """One sweep run. Reads, then enqueues `file.scan`; writes nothing else."""
    if not scanner_active(config.file_scan_backend):
        logger.warning("file scan sweep: no scanner is configured, so it enqueues nothing")
        return SweepReport("scanner_inactive")

    contract = declaration()
    selected = enqueued = duplicate = failed = pages = 0
    cursor = FairCursor()
    while pages < config.file_scan_sweep_max_batches:
        page = await select_due(session, config=config, now=now, cursor=cursor)
        if not page:
            break
        pages += 1
        for due in page:
            selected += 1
            key = contract.scan_idempotency_key(due.file_id)
            try:
                await forget_result(job_id_for(contract.FILE_SCAN, due.tenant_id, key))
                result = await queue.enqueue(
                    contract.FILE_SCAN,
                    tenant_id=due.tenant_id,
                    payload=contract.scan_payload(due.file_id),
                    idempotency_key=key,
                )
            except Exception as error:  # noqa: BLE001 - one file never stops the page
                failed += 1
                logger.error(
                    "file scan sweep could not enqueue file %s of tenant %s (%s)",
                    due.file_id,
                    due.tenant_id,
                    type(error).__name__,
                )
                continue
            if result.simulated:
                failed += 1  # nothing was queued: no queue is configured
                logger.error("file scan sweep: no queue is configured, nothing was enqueued")
            elif result.duplicate:
                duplicate += 1
            else:
                enqueued += 1
        if cursor.exhausted:
            break

    report = SweepReport("ran", selected, enqueued, duplicate, failed, pages, len(cursor.seen))
    logger.info(
        "file scan sweep: selected=%d enqueued=%d duplicate=%d failed=%d pages=%d tenants=%d",
        report.selected,
        report.enqueued,
        report.duplicate,
        report.failed,
        report.pages,
        report.tenants,
    )
    return report


def _engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )


async def sweep_pending_scans(ctx: dict[str, Any]) -> dict[str, Any]:
    """The cron entry. Skips, loudly, with no database."""
    try:
        config = ScanSweepSettings()
    except ValidationError as error:
        names = sorted({str(e["loc"][0]) for e in error.errors() if e["loc"]})
        logger.error("file scan sweep refused to run: invalid settings %s", names)
        return {"state": "invalid_config"}
    if not settings.database_url:
        logger.error("file scan sweep skipped: the worker has no DATABASE_URL")
        return {"state": "skipped", "reason": "no database"}

    redis = ctx.get("redis")

    async def forget(job_id: str) -> None:
        if redis is not None:
            await redis.delete(result_key_prefix + job_id)

    queue = queue_for(str(settings.redis_url))
    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            report = await sweep(session, queue, forget, config=config, now=datetime.now(UTC))
    finally:
        await queue.aclose()
        await engine.dispose()
    return {
        "state": report.state,
        "selected": report.selected,
        "enqueued": report.enqueued,
        "duplicate": report.duplicate,
        "failed": report.failed,
        "tenants": report.tenants,
    }
