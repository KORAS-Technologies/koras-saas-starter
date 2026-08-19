from typing import Annotated

from fastapi import Depends, HTTPException, status
from koras_tenant import TenantContext, resolve_tenant

from .auth import AuthDep


async def require_tenant(claims: AuthDep) -> TenantContext:
    tenant = await resolve_tenant(claims)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant not found")
    return tenant


TenantDep = Annotated[TenantContext, Depends(require_tenant)]
