"""Machine authentication for the private platform API.

Separate from the customer-facing dependency on purpose. These endpoints are
called by the Control Plane, not by people, so admitting a human token would be
wrong even for an administrator: a browser-obtained token reaching an internal
provisioning endpoint is a mistake or an attack.

Keeping the two dependencies apart also means a future change to customer
authentication cannot widen this by accident.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from koras_auth import JWKSCache, JWTClaims, TokenVerificationError, verify_token

from .settings import settings

_bearer = HTTPBearer(auto_error=True)
_jwks = JWKSCache(settings.zitadel_domain)


async def require_platform_machine(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> JWTClaims:
    """Admit only the estate's platform caller.

    Two checks, and the second is the one that makes the docstring true.

    The first is that the token belongs to a machine: a ZITADEL service user
    presents no email and no interactive authentication, and a human token
    reaching an internal provisioning endpoint is a mistake or an attack.

    That alone was the whole gate until 2026-08-31, while this docstring already
    claimed to admit only the Control Plane. It did not. Every machine account in
    the instance passed it -- a valid signature and an absent email are properties
    of *any* service user, including one belonging to another product or created
    by anyone who can make a service account. Verified against the live instance:
    a token minted by an account with no grant on this project was admitted, and
    a token minted by one *with* a grant was indistinguishable from it, because
    the grant reaches neither the audience nor the roles claim. Recorded as R-87.

    So the second check names the caller. `sub` is the only field in the token
    that identifies the account, and comparing it is authorisation layered on
    top of ZITADEL's authentication rather than a substitute for it: the
    signature still has to verify, and the audience still has to be this project.

    Unset means refuse. A security check that no-ops when unconfigured looks
    present and does nothing, which is the defect this whole gate just was.
    """
    try:
        claims = await verify_token(
            credentials.credentials,
            jwks=_jwks,
            project_id=settings.zitadel_project_id,
        )
    except TokenVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if claims.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint requires a machine identity",
        )

    expected = settings.zitadel_platform_caller_sub
    if not expected:
        # 503 rather than 403: nothing is wrong with the caller, and telling
        # them they are forbidden would send an operator looking at the wrong
        # side. This is the product being unconfigured, which is a condition
        # that can be fixed by setting ZITADEL_PLATFORM_CALLER_SUB.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The platform caller is not configured for this environment",
        )

    if claims.sub != expected:
        # The subject presented is deliberately not echoed. It is not secret,
        # but this response goes to whoever asked, and confirming which account
        # was seen turns a refusal into an oracle for enumerating the instance.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint requires the platform caller",
        )

    return claims


PlatformMachineDep = Annotated[JWTClaims, Depends(require_platform_machine)]
