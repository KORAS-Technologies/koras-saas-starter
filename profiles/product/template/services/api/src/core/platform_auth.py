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
    """Admit only the Control Plane service account.

    A ZITADEL service user presents a token with no email and no interactive
    authentication, which is what distinguishes it from a person. That check is
    the whole gate here: an email means a human, and a human does not belong on
    this API.
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

    return claims


PlatformMachineDep = Annotated[JWTClaims, Depends(require_platform_machine)]
