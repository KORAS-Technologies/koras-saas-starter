"""Authentication for the API.

Verification and authorisation are kept apart: a token that cannot be verified
is 401, a verified caller lacking authority is 403. Collapsing the two tells an
attacker which tokens are real.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from koras_auth import JWKSCache, JWTClaims, TokenVerificationError, verify_token

from .settings import settings

_bearer = HTTPBearer(auto_error=True)

# One cache for this environment's ZITADEL instance. Keys are fetched once and
# reused; fetching per request would put two outbound round trips on every call
# and make the identity provider a hard dependency of all traffic.
_jwks = JWKSCache(settings.zitadel_domain)


async def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> JWTClaims:
    try:
        return await verify_token(
            credentials.credentials,
            jwks=_jwks,
            project_id=settings.zitadel_project_id,
        )
    except TokenVerificationError as exc:
        # The reason is logged, not returned: it distinguishes an expired token
        # from a forged one, which is not the caller's business.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


AuthDep = Annotated[JWTClaims, Depends(require_auth)]
