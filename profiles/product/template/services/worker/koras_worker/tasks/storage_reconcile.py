"""The reconciliation sweep: what the bucket holds against what the index says.

Two comments have promised this since migration 00005 -- "an object without a
row is a leak the reconciliation sweep can find", "the object stays for the
sweep" -- and it could not be written, because the storage protocol had no way
to ask a bucket what it holds. It has a listing operation since 2026-09-15.

**It reports and deletes nothing.** An object this cannot match to a row is
not proof of a leak: a listing that failed part way looks exactly like a
prefix with fewer objects in it, and acting on that difference deletes a
customer's file. Deleting is a later decision with a person behind it;
finding is the part that has no downside.

What it can and cannot see is worth stating plainly. The worker holds the
platform's own credentials and nothing else: a customer's storage policy is
read by the API with that customer's token, and the worker has no token and no
machine identity toward the platform (FOLLOW_UPS F2b). So this reconciles the
platform's default bucket. A tenant whose policy names a bucket of their own
is counted as unverifiable rather than reported as missing -- the difference
between "the object is gone" and "the object is somewhere this process cannot
look" is the difference between an alert and a false alarm.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from koras_storage import ObjectStore, S3ObjectStore, StorageSettings, resolve_destination
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..settings import settings


class ReconcileSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    #: Off unless asked for. Listing every tenant's prefix costs provider
    #: requests, and a product with a hundred files does not need it.
    storage_reconcile_enabled: bool = False

    #: Hours a pending row is given to become ready before it is stale. The
    #: signed upload URL lasts fifteen minutes; a day is generous enough that
    #: a slow client is never called an orphan.
    storage_pending_stale_hours: int = 24

    storage_endpoint: str = ""
    storage_bucket: str = ""
    storage_region: str = ""
    storage_access_key: str = ""
    storage_secret_key: str = ""


reconcile = ReconcileSettings()

logger = logging.getLogger(__name__)

#: One page of a prefix: large enough that a small tenant is one request,
#: small enough that a large one does not arrive as a single list in memory.
PAGE = 1000

#: Pages one tenant is read for before the result is called partial.
MAX_PAGES = 50

_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")
_AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)
_TENANTS = text("select id::text as id from public.tenants where status = 'active' order by id")
_KEYS = text(
    "select storage_key, status from public.files where tenant_id = cast(:tenant_id as uuid)"
)
#: Objects under a tenant's prefix that no `files` row will ever claim. Export
#: artifacts -- audit and reporting alike -- are written to `exports/` with a
#: row in their own table and none in `files`, so a sweep that asked `files`
#: alone reported every export a customer had ever produced as an orphan.
#:
#: Through a function rather than by reading the tables, and the difference is
#: the point: a report export row carries the report, the filename and who
#: asked for it, and `130_report_schedules_isolation.sql` asserts the worker
#: sees none of that. Keys are what a reconciliation needs, so keys are all it
#: is given. The function also handles `report_exports` being absent in a
#: product generated without the reporting capability.
_CLAIMED_ELSEWHERE = text(
    "select public.claimed_storage_keys(cast(:tenant_id as uuid)) as storage_key"
)

_STALE_PENDING = text(
    "select count(*) as stale from public.files "
    "where tenant_id = cast(:tenant_id as uuid) and status = 'pending' and created_at < :before"
)
_AUDIT_INSERT = text(
    "insert into public.audit_events "
    " (tenant_id, actor_id, action, target_type, target_id, outcome, details, classification) "
    "values (cast(:tenant_id as uuid), 'system', 'storage.reconcile.orphan_found', "
    " 'tenant', :tenant_id, 'ok', cast(:details as jsonb), 'audit')"
)


@dataclass(frozen=True)
class TenantReconciliation:
    """What one tenant's prefix and index said about each other."""

    tenant_id: str
    objects: int
    rows: int
    #: Objects in the bucket that no row claims: a leak, or a confirmation
    #: that failed after the PUT.
    orphan_objects: int
    #: Ready rows whose object is not in the platform bucket. Missing, or
    #: stored under a policy of the tenant's own; this cannot tell which.
    unverifiable_rows: int
    #: Pending rows too old to still be arriving.
    stale_pending: int
    #: True when the listing did not finish, and every count above is a floor
    #: rather than a total.
    partial: bool


def list_prefix(
    store: ObjectStore, prefix: str, *, pages: int = MAX_PAGES
) -> tuple[set[str], bool]:
    """Every key under a prefix, and whether the listing finished.

    Bounded: a tenant with more objects than `pages` pages is reported as
    partial rather than read forever. A caller that treats a partial listing
    as a complete one invents orphans.
    """
    keys: set[str] = set()
    cursor: str | None = None
    for _ in range(pages):
        page = store.list(prefix, cursor=cursor, limit=PAGE)
        keys.update(item.key for item in page.objects)
        if not page.truncated or page.cursor is None:
            return keys, False
        cursor = page.cursor
    return keys, True


async def reconcile_tenant(
    session: AsyncSession, store: ObjectStore, tenant_id: str, *, stale_hours: int
) -> TenantReconciliation:
    """Compare one tenant's prefix with one tenant's rows. Changes nothing."""
    rows = (await session.execute(_KEYS, {"tenant_id": tenant_id})).all()
    ready = {row.storage_key for row in rows if row.status == "ready"}
    known = {row.storage_key for row in rows}

    # Export artifacts are stored objects with no `files` row. They are claimed,
    # not orphaned, and counting them as orphans would have made the sweep's
    # headline number grow with ordinary use of the product.
    claimed = (await session.execute(_CLAIMED_ELSEWHERE, {"tenant_id": tenant_id})).all()
    known.update(row.storage_key for row in claimed)

    keys, partial = list_prefix(store, f"tenants/{tenant_id}/")
    before = datetime.now(UTC) - timedelta(hours=stale_hours)
    stale = (
        await session.execute(_STALE_PENDING, {"tenant_id": tenant_id, "before": before})
    ).one()

    return TenantReconciliation(
        tenant_id=tenant_id,
        objects=len(keys),
        rows=len(rows),
        # A partial listing cannot produce a trustworthy orphan count: the
        # keys it did not read look exactly like keys that are not there.
        orphan_objects=0 if partial else len(keys - known),
        unverifiable_rows=0 if partial else len(ready - keys),
        stale_pending=int(stale.stale),
        partial=partial,
    )


def _store() -> ObjectStore:
    """The platform's own default destination, and no policy but that one."""
    destination = resolve_destination(
        None,
        StorageSettings(
            endpoint=reconcile.storage_endpoint,
            bucket=reconcile.storage_bucket,
            region=reconcile.storage_region,
            access_key=reconcile.storage_access_key,
            secret_key=reconcile.storage_secret_key,
        ),
    )
    return S3ObjectStore(destination)


def _engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )


async def record_finding(session: AsyncSession, finding: TenantReconciliation) -> None:
    """One audit row per tenant that had something, on that tenant's context.

    The audit table admits an insert only for the tenant the row belongs to,
    so the sweep leaves the provisioning context to write and the caller puts
    it back. Counts only: an object key is half a signed URL and is never a
    detail.
    """
    await session.execute(_AS_TENANT, {"tenant_id": finding.tenant_id})
    await session.execute(
        _AUDIT_INSERT,
        {
            "tenant_id": finding.tenant_id,
            "details": json.dumps(
                {
                    "orphan_objects": finding.orphan_objects,
                    "stale_pending": finding.stale_pending,
                    "unverifiable_rows": finding.unverifiable_rows,
                    "objects": finding.objects,
                    "rows": finding.rows,
                }
            ),
        },
    )
    await session.commit()


async def reconcile_storage(ctx: dict[str, Any]) -> dict[str, Any]:
    """The nightly comparison. Skips, loudly, when it cannot or should not run."""
    del ctx
    if not reconcile.storage_reconcile_enabled:
        return {"status": "skipped", "reason": "not enabled"}
    if not settings.database_url:
        logger.warning("storage reconciliation skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}
    if not reconcile.storage_bucket or not reconcile.storage_access_key:
        logger.warning("storage reconciliation skipped: the worker has no storage credentials")
        return {"status": "skipped", "reason": "no storage"}

    store = _store()
    engine = _engine()
    findings: list[TenantReconciliation] = []
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(_PROVISIONING)
            tenants = [row.id for row in (await session.execute(_TENANTS)).all()]
            for tenant_id in tenants:
                try:
                    finding = await reconcile_tenant(
                        session,
                        store,
                        tenant_id,
                        stale_hours=reconcile.storage_pending_stale_hours,
                    )
                except Exception:
                    # One unreachable prefix is not a reason to stop looking at
                    # the rest, and the sweep changes nothing either way.
                    logger.exception("storage reconciliation failed for one tenant")
                    await session.rollback()
                    await session.execute(_PROVISIONING)
                    continue
                findings.append(finding)
                if finding.orphan_objects or finding.stale_pending:
                    await record_finding(session, finding)
                    await session.execute(_PROVISIONING)
    finally:
        await engine.dispose()

    orphans = sum(f.orphan_objects for f in findings)
    stale = sum(f.stale_pending for f in findings)
    unverifiable = sum(f.unverifiable_rows for f in findings)
    logger.info(
        "storage reconciliation: %d tenant(s), %d orphan object(s), %d stale pending row(s), "
        "%d row(s) this process cannot verify",
        len(findings),
        orphans,
        stale,
        unverifiable,
    )
    return {
        "status": "ok",
        "tenants": len(findings),
        "orphan_objects": orphans,
        "stale_pending": stale,
        "unverifiable_rows": unverifiable,
        "partial": [f.tenant_id for f in findings if f.partial],
    }
