"""Authentication for the platform API.

Verification and authorisation are kept apart: a token that cannot be verified
is 401, a verified caller lacking authority is 403. Collapsing the two tells an
attacker which tokens are real.
"""

from __future__ import annotations

import logging

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from koras_auth import JWKSCache, Principal, TokenVerificationError, verify_token

from .settings import settings

_log = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=True)

# One cache for this environment's ZITADEL instance. Keys are fetched once and
# reused; fetching per request would put two outbound round trips on every call
# and make the identity provider a hard dependency of all traffic.
_jwks = JWKSCache(settings.zitadel_domain)


async def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> Principal:
    try:
        return await verify_token(
            credentials.credentials,
            jwks=_jwks,
            project_id=settings.zitadel_project_id,
            client_id=settings.zitadel_client_id,
        )
    except TokenVerificationError as exc:
        # Logged, not returned. The distinction matters both ways: an expired
        # token and a forged one must look identical to the caller, and must
        # not look identical to whoever is on call.
        #
        # This comment claimed the reason was logged and nothing logged it --
        # no logger was even imported -- so an application answered 401 on
        # every page with no way to find out why.
        _log.warning("token rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


AuthDep = Annotated[Principal, Depends(require_auth)]


def require_platform_staff(principal: AuthDep) -> Principal:
    """Admit only KORAS staff.

    The five platform roles are Control Plane authority and a product
    repository never sees this function -- `koras_platform.platform_roles`
    ships to this profile alone.

    This refused everyone while those roles existed only in the downstream
    repository and not in the template, which was the right failure while it
    lasted: the alternative to refusing everyone is an open platform API. They
    ship here now, so the check is the real one.

    `is_platform_staff` requires both a PLATFORM actor and a role. Either alone
    is not staff -- an organization token carrying a role name it should not
    have is still an organization token.
    """
    if not principal.is_platform_staff:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint requires a platform role",
        )
    return principal


PlatformAuthDep = Annotated[Principal, Depends(require_platform_staff)]
