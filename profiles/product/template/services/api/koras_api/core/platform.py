"""What the Control Plane says about this caller's organization, read by the API.

The web tier already reads the platform's portal routes -- entitlements,
branding -- with the customer's own token, forwarded as it arrived. This is the
same read from the API, for the two answers the API has to act on rather than
merely display: where a customer's files go, and how much they may store. Same
credential, same routes, same argument: the portal resolves the organization
from the token and has nowhere to put another one, so this service cannot ask
about a customer other than the one calling it, even by mistake.

No machine credential is held for this and none is needed. FOLLOW_UPS F2b is
the reason a product must not hold the identity that the platform's
machine-only routes admit; the customer's token is the one identity a product
is entitled to act with, and it expires with the session.

Cached for a minute per organization and route. A policy changes once a
quarter and an entitlement once a month; an upload page lists files every
few seconds. An unreachable platform is a miss, not an error: the caller
decides what to do without an answer, and for storage that is the product's
own default -- which is also what the platform would have said for a customer
nobody has decided anything for.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .settings import settings

_log = logging.getLogger(__name__)

_TTL_SECONDS = 60.0
_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class PortalAnswer:
    """The platform answered. `body` is None when it answered 404.

    Kept apart from "no answer" on purpose: a 404 is a fact about this
    organization -- no subscription, no policy of its own -- and is cached
    and acted on, while an unreachable platform is nothing to act on.
    """

    body: dict[str, Any] | None


# (organization id, path) -> (expires at, answer). Small by construction:
# one entry per organization per route, and a process serves one product.
_cache: dict[tuple[str, str], tuple[float, PortalAnswer]] = {}


def configured() -> bool:
    return bool(settings.koras_control_plane_url)


async def read_portal(path: str, *, organization_id: str, token: str) -> PortalAnswer | None:
    """One portal route, for the organization the token belongs to.

    None means "no answer": the platform is unconfigured, unreachable, or
    refused. The three are logged apart -- an unconfigured platform is a
    supported state and says nothing, the other two are something to fix --
    and treated alike by callers, because a customer cannot act on the
    difference and the product's default is the right fallback for all of
    them.
    """
    base = settings.koras_control_plane_url.rstrip("/")
    if not base:
        return None

    key = (organization_id, path)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached is not None and cached[0] > now:
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{base}{path}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
    except httpx.HTTPError as error:
        _log.warning("the platform could not be reached for %s: %s", path, error)
        return None

    if response.status_code == 404:
        # This organization holds nothing for this product on that route --
        # a platform default for storage, no subscription for entitlements.
        # A real answer, cached like one.
        answer = PortalAnswer(None)
    elif response.status_code >= 400:
        _log.warning(
            "the platform refused %s with %s; the product's own defaults apply",
            path,
            response.status_code,
        )
        return None
    else:
        try:
            parsed = response.json()
        except ValueError:
            _log.warning("the platform answered %s with something that is not JSON", path)
            return None
        answer = PortalAnswer(parsed if isinstance(parsed, dict) else None)

    _cache[key] = (now + _TTL_SECONDS, answer)
    return answer


def forget(organization_id: str) -> None:
    """Drop what is cached for one organization. Tests, and a future webhook."""
    for key in [key for key in _cache if key[0] == organization_id]:
        del _cache[key]
