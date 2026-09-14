"""One row per model call, and nothing a customer wrote.

The dimensions the platform needs to meter, bill and debug: who, which tenant,
which agent, which alias, which provider and model answered, how many units in
and out, how long, and whether it worked. No prompt, no answer, no tool
argument. A usage record that carried content would be a second copy of the
conversation with a longer retention and a wider audience.

`UsageRecorder` is the seam. The API writes rows; a test keeps them in memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from .types import Usage


@dataclass(frozen=True)
class UsageEvent:
    tenant_id: str
    user_id: str
    agent_id: str
    model_alias: str
    #: The provider and model that answered, or that was tried when it failed.
    provider: str
    model: str
    usage: Usage
    latency_ms: int
    #: "ok", or the error code that ended the attempt.
    status: str
    created_at: datetime
    conversation_id: str | None = None
    error_code: str | None = None
    #: List-price cost in millionths of a US dollar, or None when the route
    #: carried no price. Never zero for "unknown": zero is a number.
    estimated_cost_micros: int | None = None


class UsageRecorder(Protocol):
    async def record(self, event: UsageEvent) -> None: ...

    async def requests_since(self, tenant_id: str, since: datetime) -> int:
        """How many model calls this tenant has made since `since`, successful or not.

        Failed attempts count too. A caller who can spend the provider's time
        without spending their own allowance has an allowance that does not
        bound anything.
        """
        ...


def month_start(now: datetime | None = None) -> datetime:
    """The first instant of the current calendar month, in UTC.

    Calendar months rather than a rolling window, because that is what the
    plan says -- "per month" -- and what an invoice will say beside it.
    """
    moment = now or datetime.now(UTC)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
