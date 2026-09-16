"""The private platform contract's governance half: what this product holds, per tenant.

Aggregates only, on the provisioning session, for the machine identity the
platform holds toward this product. The Control Plane's collector reads these
so its console can answer estate questions -- is retention working, is anything
under hold, is anybody exporting -- without reading anybody's records.

**What is deliberately not here, and why it changed.** An earlier sketch of this
contract promised the provider serving each tenant and the quota ceiling they
are held to. Both were wrong to ask for: the provider comes from the Control
Plane's own storage policy and the ceiling from its own entitlement catalogue,
so the platform would have been asking a product to report facts the platform
already owns -- and the product could not answer honestly anyway, because it
reads both with the *customer's* token and a collector has no customer token.
What a product knows that the platform does not is what it actually stored, and
that is what these routes carry.

Counts throughout. No object keys, no filenames, no actor ids, no hold reasons
-- a hold reason names a matter, and a matter usually names a person.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from ..core.database import PlatformSession
from ..core.platform_auth import PlatformMachineDep

router = APIRouter(tags=["platform"])

#: The same window the activity half allows, for the same reason: a collector
#: asks from the last day it holds, and a month is generous.
WINDOW_DAYS = 92


class StorageSummary(BaseModel):
    """One tenant's stored objects, as the product sees them."""

    tenant_id: str
    #: Rows the tenant can still reach: `ready` plus `quarantined`.
    objects: int
    bytes_stored: int
    #: Withheld by a scan. Non-zero here is the estate's early warning.
    quarantined: int
    #: Marked purged and not yet removed from the bucket -- the lifecycle sweep
    #: could not delete the object. Reconciliation finds these later.
    stranded: int
    #: How many objects carry a digest, and how many of those a provider
    #: corroborated. The difference is the honest measure of integrity: a
    #: claim is not a measurement.
    with_checksum: int
    checksum_verified: int
    #: Objects with no retention date resolved yet. A large number means the
    #: lifecycle sweep is not running, which nothing else would show.
    retention_unresolved: int
    #: Objects a hold is keeping past their date.
    held: int


class AuditSummary(BaseModel):
    """One tenant's audit rows by class, and how far back they reach."""

    tenant_id: str
    classification: str
    events: int
    #: The oldest row of this class. Older than the class's retention allows
    #: means the sweep has stopped, and the log is the only other place that
    #: would say so.
    oldest: datetime | None


class HoldSummary(BaseModel):
    tenant_id: str
    scope: str
    status: str
    holds: int


class ExportSummary(BaseModel):
    tenant_id: str
    status: str
    exports: int
    rows_exported: int


class GovernanceReport(BaseModel):
    since: date
    storage: list[StorageSummary]
    audit: list[AuditSummary]
    holds: list[HoldSummary]
    exports: list[ExportSummary]


_STORAGE = text(
    "select tenant_id::text as tenant_id, "
    " count(*) filter (where status in ('ready', 'quarantined'))::int as objects, "
    " coalesce(sum(size_bytes) filter (where status = 'ready'), 0)::bigint as bytes_stored, "
    " count(*) filter (where status = 'quarantined')::int as quarantined, "
    " count(*) filter (where status = 'purged')::int as stranded, "
    " count(*) filter (where checksum_sha256 is not null)::int as with_checksum, "
    " count(*) filter (where checksum_verified_at is not null)::int as checksum_verified, "
    " count(*) filter (where retain_until is null "
    "                    and status in ('ready', 'quarantined'))::int as retention_unresolved, "
    " count(*) filter (where legal_hold = true)::int as held "
    "from public.files "
    "group by 1 order by 1"
)

_AUDIT = text(
    "select tenant_id::text as tenant_id, classification, "
    " count(*)::int as events, min(created_at) as oldest "
    "from public.audit_events "
    "group by 1, 2 order by 1, 2"
)

_HOLDS = text(
    "select tenant_id::text as tenant_id, scope, status, count(*)::int as holds "
    "from public.legal_holds "
    "group by 1, 2, 3 order by 1, 2, 3"
)

_EXPORTS = text(
    "select tenant_id::text as tenant_id, status, count(*)::int as exports, "
    " coalesce(sum(rows_exported), 0)::int as rows_exported "
    "from public.audit_exports "
    "where created_at >= cast(:since as date) "
    "group by 1, 2 order by 1, 2"
)


@router.get("/governance", response_model=GovernanceReport)
async def governance(
    _principal: PlatformMachineDep,
    session: PlatformSession,
    since: date | None = None,
) -> GovernanceReport:
    """Storage, audit, holds and exports for every tenant. Aggregates only.

    One route rather than four, because the collector wants all of it at once
    and four round trips per product per sweep is three more chances for a
    partial picture nobody notices.

    `since` bounds the export counts alone. The rest are current state rather
    than a window: how many objects exist now, how many rows are held now.
    """
    today = datetime.now(UTC).date()
    earliest = today - timedelta(days=WINDOW_DAYS)
    start = since if since is not None and since >= earliest else earliest
    if start > today:
        start = today

    storage = (await session.execute(_STORAGE)).mappings().all()
    audit = (await session.execute(_AUDIT)).mappings().all()
    holds = (await session.execute(_HOLDS)).mappings().all()
    exports = (await session.execute(_EXPORTS, {"since": start})).mappings().all()

    return GovernanceReport(
        since=start,
        storage=[StorageSummary(**dict(row)) for row in storage],
        audit=[AuditSummary(**dict(row)) for row in audit],
        holds=[HoldSummary(**dict(row)) for row in holds],
        exports=[ExportSummary(**dict(row)) for row in exports],
    )
