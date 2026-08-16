from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from koras_auth import verify_jwt, JWTClaims
from .settings import settings

_bearer = HTTPBearer()


async def require_platform_auth(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> JWTClaims:
    claims = await verify_jwt(
        token=credentials.credentials,
        zitadel_domain=settings.zitadel_domain,
        project_id=settings.zitadel_project_id,
    )
    if claims is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    # Platform API requires platform staff role
    if "platform:admin" not in claims.roles and "platform:operator" not in claims.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    return claims


PlatformAuthDep = Annotated[JWTClaims, Depends(require_platform_auth)]
