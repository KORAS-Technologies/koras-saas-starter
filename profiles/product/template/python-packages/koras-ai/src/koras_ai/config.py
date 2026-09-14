"""Where the routing decision comes from, and what to do when it is silent.

Two sources. The product's catalogue is always there. The Control Plane's
routing policy is there when the product has a platform configured, and it
answers per customer and per alias.

`fail_closed` is the whole of the difference between the two states this can
run in. With a platform configured, a silent platform -- unreachable, refusing,
or holding no policy for this customer -- is a refusal: an AI capability has
no platform default, on purpose, because routing a customer's data to a
provider nobody chose is exactly the decision the policy makes explicit. With
no platform configured at all, the catalogue decides, which is the documented
bootstrap order: a product may be built and run before any Control Plane is
live, and locally there is never one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from .errors import configuration
from .models import ModelCatalogue, ModelRoute
from .types import Price


@dataclass(frozen=True)
class AliasPolicy:
    """What the platform said about one alias for one customer."""

    providers: tuple[str, ...]
    model: str | None = None
    #: The model the second provider answers as, when the policy names one.
    #: A model name belongs to one provider, so this belongs to the fallback
    #: alone the way `model` belongs to the primary alone.
    fallback_model: str | None = None
    #: List price per model the policy names, so the product can estimate
    #: cost without a price list of its own. Empty when the platform sent
    #: none, and then every usage row's estimate is null rather than zero.
    prices: Mapping[str, Price] = field(default_factory=dict)


class RoutingSource(Protocol):
    """Answers the routing policy for an alias, or None when it has none.

    None is "no policy", and what that means is the configuration's decision,
    not the source's. A source that cannot reach its backing store answers
    None too; the configuration cannot tell the two apart and should not try,
    because the customer cannot act on the difference.
    """

    async def policy_for(self, alias: str) -> AliasPolicy | None: ...


class StaticRouting:
    """No platform: every alias is answered by the catalogue."""

    async def policy_for(self, alias: str) -> AliasPolicy | None:
        return None


@dataclass(frozen=True)
class Limits:
    """The commercial ceilings the runtime enforces per tenant.

    `monthly_requests` is model calls per calendar month; None is no ceiling.
    `tools_enabled` is whether a tool may run at all for this tenant.
    """

    monthly_requests: int | None = None
    tools_enabled: bool = True
    #: Pay as you go beyond the allowance. Off, the allowance is a stop; on,
    #: a call past it is made and stamped billable at `overage_rate_percent`
    #: of its list-price cost (400 is four times), until the month's
    #: billable total reaches `overage_cap_micros`, which is then the stop.
    overage_enabled: bool = False
    overage_rate_percent: int = 400
    overage_cap_micros: int | None = None


@dataclass(frozen=True)
class AIConfiguration:
    catalogue: ModelCatalogue
    routing: RoutingSource
    #: True when a platform is configured, so its silence is a refusal.
    fail_closed: bool
    limits: Limits = Limits()

    async def routes_for(self, alias: str) -> tuple[ModelRoute, ...]:
        policy = await self.routing.policy_for(alias)
        if policy is None:
            if self.fail_closed:
                raise configuration(
                    "AI routing is not configured for this organization",
                    detail=f"no routing policy for {alias} and a platform is configured",
                )
            return self.catalogue.routes_for(alias)
        return self.catalogue.resolve(
            alias,
            policy.providers,
            policy.model,
            fallback_model=policy.fallback_model,
            prices=policy.prices,
        )
