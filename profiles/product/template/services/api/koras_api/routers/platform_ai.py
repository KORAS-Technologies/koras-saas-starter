"""The private platform contract's AI half: what the tenants used, per day.

Its own module because the assistant is a capability and the platform
router is not; `main.py` includes this beside the platform router, under
the same prefix and the same limiter, only when the capability is generated.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel

from ..core.ai import usage_days_since
from ..core.database import PlatformSession
from ..core.platform_auth import PlatformMachineDep

router = APIRouter(tags=["platform"])


class AiUsageDay(BaseModel):
    """One tenant's AI usage on one UTC day for one alias, provider and model."""

    tenant_id: str
    day: date
    model_alias: str
    provider: str
    model: str
    calls: int
    errors: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    #: Successful calls made beyond the plan's allowance under pay as you go,
    #: and what they are billable at: cost times the rate stamped on each.
    overage_calls: int = 0
    billable_micros: int = 0
    #: List-price cost in millionths of a US dollar; rows with no estimate add nothing.
    estimated_cost_micros: int


class AiUsageReport(BaseModel):
    since: date
    days: list[AiUsageDay]


#: How far back the platform may ask in one call. Its collector asks from the
#: last day it holds, minus one, so a month is generous; a year is a mistake.
_USAGE_WINDOW_DAYS = 92


@router.get("/ai-usage", response_model=AiUsageReport)
async def ai_usage(
    _principal: PlatformMachineDep,
    session: PlatformSession,
    since: date | None = None,
) -> AiUsageReport:
    """What this product's tenants used the assistant for, per day, from `since`.

    Aggregates only, and every tenant's, because the caller is the platform
    collecting for the estate rather than a customer reading their own. The
    window is bounded on this side: a collector that fell behind by a year
    catches up in a few calls, not one that never returns.
    """
    today = datetime.now(UTC).date()
    earliest = today - timedelta(days=_USAGE_WINDOW_DAYS)
    start = since if since is not None and since >= earliest else earliest
    if start > today:
        start = today
    days = await usage_days_since(session, start)
    return AiUsageReport(since=start, days=[AiUsageDay(**row) for row in days])
