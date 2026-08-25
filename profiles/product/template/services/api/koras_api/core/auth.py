"""Authentication for the API.

Verification and authorisation are kept apart: a token that cannot be verified
is 401, a verified caller lacking authority is 403. Collapsing the two tells an
attacker which tokens are real.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from koras_auth import JWKSCache, JWTClaims, TokenVerificationError, verify_token

from .settings import settings

_log = logging.getLogger(__name__)
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
            client_id=settings.zitadel_client_id,
            # `verify_token` defaults this to None, so the issuer is checked
            # only if the caller asks. The keys already come from this instance,
            # which is why the omission never showed -- but that is the next
            # check covering for this one, and OIDC Core 3.1.3.7 asks for both.
            # Normalized the way JWKSCache normalizes it, so the expected issuer
            # and the key source cannot disagree about a trailing slash.
            issuer=settings.zitadel_domain.rstrip("/"),
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


AuthDep = Annotated[JWTClaims, Depends(require_auth)]
