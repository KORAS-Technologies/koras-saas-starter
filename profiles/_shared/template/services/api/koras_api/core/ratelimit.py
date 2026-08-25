"""Rate limiting for the API. R-034.

Two tiers, because the thing most worth protecting sits before authentication
and cannot be keyed on the caller's identity.

**Tier 1, before the token is verified.** Verifying a bearer token means a JWKS
lookup and an asymmetric signature check, and anyone can ask for it without
credentials. There is no tenant and no subject at this point, so the key is the
client address — which arrives through a CDN, so it is read from the forwarded
header rather than from the socket, and only when the deployment says that
header can be trusted.

**Tier 2, after it is verified.** A per-tenant and per-subject quota, keyed on
claims the token proved rather than on anything the caller asserted. A verified
caller can still be abusive, and a tenant sharing one address is not one caller.

Both fail open. See `koras_ratelimit` for why, and for what that costs.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from koras_ratelimit import RateLimit, RateLimitDecision, check

from .auth import AuthDep
from .settings import settings

# Deliberately generous. A limiter exists to stop abuse, not to shape ordinary
# traffic, and one tuned so tightly that a legitimate burst trips it gets
# switched off by whoever it wakes at 3am.
ANONYMOUS_LIMIT = RateLimit(limit=60, window_seconds=60)
AUTHENTICATED_LIMIT = RateLimit(limit=600, window_seconds=60)


def client_identity(request: Request) -> str:
    """Who to limit, before there is a verified caller to name.

    `X-Forwarded-For` is set by anyone who wants to set it. It is trusted only
    where the deployment guarantees a proxy rewrites it -- otherwise a caller
    varies one header and gets a fresh quota per request, which is a limiter
    that limits nobody while appearing to work.

    The leftmost entry is the original client; the rest are proxies.
    """
    if settings.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first

    client = request.client
    return client.host if client else "unknown"


def _refuse(decision: RateLimitDecision) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit exceeded",
        headers=decision.headers,
    )



def caller_identity(claims: object) -> tuple[str, str]:
    """The organization and subject, whichever profile's claim type this is.

    The two profiles model an authenticated caller differently and always have:
    a product carries `JWTClaims(sub, organization_id)`, the Control Plane
    carries `Principal(subject, zitadel_organization_id)`. This module is shared
    by both, so it reads both shapes rather than being copied into each and
    left to drift.

    Both attributes come off a verified token either way. The fallbacks are for
    the shape, never for the trust: nothing here reads a header or a parameter.

    An unidentifiable caller is bucketed as "unknown" rather than waved through.
    That shares one quota between every such caller, which is the safe direction
    -- the alternative is a caller who avoids the limiter by being unreadable.
    """
    subject = getattr(claims, "sub", None) or getattr(claims, "subject", None)
    organization = getattr(claims, "organization_id", None) or getattr(
        claims, "zitadel_organization_id", None
    )
    return (organization or "none", subject or "unknown")


async def limit_anonymous(request: Request) -> RateLimitDecision:
    """Tier 1. Applies to every request, including unauthenticated ones."""
    decision = await check(
        request.app.state.redis,
        bucket="anon",
        identity=client_identity(request),
        limit=ANONYMOUS_LIMIT,
    )
    # Recorded on the request so a middleware can put the headers on the
    # response, including for requests that were allowed.
    request.state.rate_limit = decision
    if not decision.allowed:
        _refuse(decision)
    return decision


async def limit_authenticated(request: Request, claims: AuthDep) -> RateLimitDecision:
    """Tier 2. Keyed on what the token proved, not on what the caller asserted.

    Depends on `AuthDep`, so it cannot run before verification and cannot be
    reached by an unverified caller -- which is the property that makes keying
    on `sub` safe.
    """
    organization, subject = caller_identity(claims)
    decision = await check(
        request.app.state.redis,
        bucket="tenant",
        identity=f"{organization}:{subject}",
        limit=AUTHENTICATED_LIMIT,
    )
    request.state.rate_limit = decision
    if not decision.allowed:
        _refuse(decision)
    return decision


AnonymousRateLimit = Annotated[RateLimitDecision, Depends(limit_anonymous)]
AuthenticatedRateLimit = Annotated[RateLimitDecision, Depends(limit_authenticated)]
