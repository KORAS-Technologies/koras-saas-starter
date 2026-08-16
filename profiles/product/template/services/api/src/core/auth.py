from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from koras_auth import verify_jwt, JWTClaims
from .settings import settings

_bearer = HTTPBearer()


async def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> JWTClaims:
    claims = await verify_jwt(
        token=credentials.credentials,
        zitadel_domain=settings.zitadel_domain,
        project_id=settings.zitadel_project_id,
    )
    if claims is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return claims


AuthDep = Annotated[JWTClaims, Depends(require_auth)]
