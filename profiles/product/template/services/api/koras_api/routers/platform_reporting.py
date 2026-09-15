"""The private platform contract's activity half: what the tenants did, per day.

The same shape as the AI half in `platform_ai.py`: aggregates over every
tenant, on the provisioning session, for the machine identity the platform
holds toward this product. Counts of audited actions and of the distinct
people behind them, by day, action and outcome -- never who did what, which
stays in `audit_events` under the tenant's own policies. The platform's
collector keeps it per organization and its Usage & Adoption and Security
reports read it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from ..core.database import PlatformSession
from ..core.platform_auth import PlatformMachineDep

router = APIRouter(tags=["platform"])


class ActivityDay(BaseModel):
    """One tenant's audited activity on one UTC day for one action and outcome."""

    tenant_id: str
    day: date
    action: str
    outcome: str
    events: int
    #: Distinct actors behind those events on that day.
    actors: int


class ActivityReport(BaseModel):
    since: date
    days: list[ActivityDay]


#: The same window the AI half allows: the collector asks from the last day it
#: holds, minus one, so a month is generous.
_ACTIVITY_WINDOW_DAYS = 92

_ACTIVITY_DAYS = text(
    "select tenant_id::text as tenant_id, "
    " (created_at at time zone 'UTC')::date as day, action, outcome, "
    " count(*)::int as events, count(distinct actor_id)::int as actors "
    "from public.audit_events "
    "where created_at >= cast(:since as date) "
    "group by 1, 2, 3, 4 "
    "order by 2, 1, 3, 4"
)


@router.get("/activity", response_model=ActivityReport)
async def activity(
    _principal: PlatformMachineDep,
    session: PlatformSession,
    since: date | None = None,
) -> ActivityReport:
    """What this product's tenants did, per day, from `since`. Aggregates only."""
    today = datetime.now(UTC).date()
    earliest = today - timedelta(days=_ACTIVITY_WINDOW_DAYS)
    start = since if since is not None and since >= earliest else earliest
    if start > today:
        start = today
    result = await session.execute(_ACTIVITY_DAYS, {"since": start})
    return ActivityReport(
        since=start, days=[ActivityDay(**dict(row)) for row in result.mappings().all()]
    )
