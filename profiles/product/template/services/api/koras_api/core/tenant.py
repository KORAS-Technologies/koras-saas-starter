"""Which tenant this request acts for.

The first query of every customer request, and the only one that cannot be
scoped by the tenant context — because finding the tenant is what establishes
it. Migration 00004 explains at length why that is a policy on the caller's
verified organization rather than a `security definer` function.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from koras_tenant import TenantContext, resolve_tenant

from .auth import AuthDep
from .engine import SessionLocal


async def require_tenant(claims: AuthDep) -> TenantContext:
    """Resolve the caller's tenant, or refuse.

    A session of its own, opened and closed before the request's own session
    exists. That is deliberate rather than wasteful: this transaction runs with
    `app.zitadel_org_id` set and no tenant id, and the request's runs with a
    tenant id and no organization. Sharing one connection would leave both keys
    live for the whole request, so every later query would be admitted by two
    policies instead of one — and the second would not narrow with the first.

    403, not 404. The caller is authenticated; what they lack is a tenant here.
    A 404 would be a small lie that reads as "wrong URL" and sends people to
    check their address instead of their access.
    """
    async with SessionLocal() as session:
        tenant = await resolve_tenant(session, claims.organization_id)

    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            # Says nothing about whether the organization exists, is suspended,
            # or was never provisioned here. Those need different fixes and the
            # difference belongs in the service log, not in an answer to
            # somebody who may be guessing.
            detail="No active tenant for this account",
        )
    return tenant


TenantDep = Annotated[TenantContext, Depends(require_tenant)]
