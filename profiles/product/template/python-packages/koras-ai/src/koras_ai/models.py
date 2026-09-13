"""Model aliases, and how one becomes a gateway model name.

Product code asks for `koras-balanced`. It never asks for a provider's model
name, because that name is a decision the platform makes per customer -- a
customer who routes confidential work to a private model gets the same alias
answered by a different route -- and a decision the product would otherwise
have to re-deploy to change.

The catalogue is the product's own default: for each alias, the routes it can
serve, in order, each naming a provider and the gateway model that provider
answers as. The Control Plane's routing policy, where one exists for this
customer and alias, chooses the providers and may name the model; the
catalogue supplies whatever the policy left out. `resolve` is where the two
meet.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from .errors import configuration, invalid_alias


class ModelAlias(StrEnum):
    """The names product code may use. A closed set, so a typo is an error."""

    FAST = "koras-fast"
    BALANCED = "koras-balanced"
    REASONING = "koras-reasoning"
    EMBEDDING = "koras-embedding"
    VISION = "koras-vision"


_ALIASES = frozenset(alias.value for alias in ModelAlias)


def is_alias(value: str) -> bool:
    return value in _ALIASES


@dataclass(frozen=True)
class ModelRoute:
    """One way of serving an alias: a provider, and the model it answers as.

    `provider` is the platform's vocabulary -- `openai`, `anthropic`, or a name
    a customer's own policy invented -- and `model` is the name the gateway
    lists for it. Neither reaches product code.
    """

    provider: str
    model: str


class ModelCatalogue:
    """The product's default routes per alias, in preference order."""

    def __init__(self, routes: Mapping[str, Sequence[ModelRoute]]) -> None:
        for alias in routes:
            if not is_alias(alias):
                raise invalid_alias(alias)
        self._routes: dict[str, tuple[ModelRoute, ...]] = {
            alias: tuple(candidates) for alias, candidates in routes.items()
        }

    def aliases(self) -> tuple[str, ...]:
        return tuple(sorted(self._routes))

    def routes_for(self, alias: str) -> tuple[ModelRoute, ...]:
        if not is_alias(alias):
            raise invalid_alias(alias)
        routes = self._routes.get(alias, ())
        if not routes:
            raise configuration(f"no model serves {alias}")
        return routes

    def resolve(
        self,
        alias: str,
        providers: Sequence[str] | None = None,
        model: str | None = None,
        *,
        fallback_model: str | None = None,
    ) -> tuple[ModelRoute, ...]:
        """The routes to try, in order, for this alias under this policy.

        No policy is the catalogue's own order. A policy names providers in
        the order to try them; the first is the primary, and a model the
        policy names applies to the primary alone, `fallback_model` to the
        second alone -- a model name belongs to one provider, and the policy
        stated which. A provider the policy names but the catalogue has no
        route for is skipped along with the model named for it, and a policy
        that leaves nothing is a configuration error rather than a silent
        fall-through to the default: the customer chose those providers, and
        answering with a different one would be exactly the decision the
        policy exists to prevent.
        """
        defaults = self.routes_for(alias)
        if providers is None:
            return defaults

        by_provider = {route.provider: route for route in defaults}
        named = {0: model, 1: fallback_model}
        chosen: list[ModelRoute] = []
        for position, provider in enumerate(providers):
            route = by_provider.get(provider)
            if route is None:
                continue
            if named.get(position):
                route = ModelRoute(provider=provider, model=named[position] or route.model)
            chosen.append(route)

        if not chosen:
            raise configuration(
                f"none of the providers the policy names can serve {alias}",
                detail=f"policy providers {list(providers)!r}; catalogue {list(by_provider)!r}",
            )
        return tuple(chosen)
