"""Which tenant this request acts for.

The first query of every customer request, and the only one that cannot be
scoped by the tenant context — because finding the tenant is what establishes
it. Migration 00004 explains at length why that is a policy on the caller's
verified organization rather than a `security definer` function.
"""

from dataclasses import replace
from typing import Annotated

from fastapi import Depends, status
from koras_tenant import TenantContext, resolve_tenant

from .auth import AuthDep
from .engine import SessionLocal
from .errors import ApiErrorCode, api_error


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

    The subject travels with the tenant from here. The request's session
    declares both, so a policy keyed to `current_user_id()` sees the person the
    token names -- and nothing else in the request can put a different one
    there, because nothing else sets it.
    """
    async with SessionLocal() as session:
        tenant = await resolve_tenant(session, claims.organization_id)

    if tenant is None:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.TENANT_INACTIVE,
            # Says nothing about whether the organization exists, is suspended,
            # or was never provisioned here. Those need different fixes and the
            # difference belongs in the service log, not in an answer to
            # somebody who may be guessing.
            "No active tenant for this account",
        )
    return replace(tenant, user_id=claims.sub)


TenantDep = Annotated[TenantContext, Depends(require_tenant)]


def require_subject(tenant: TenantContext) -> str:
    """The verified subject, for a route that writes something personal.

    `TenantContext.user_id` is optional because the type serves the worker and
    the platform's own calls as well as a customer's request, and neither of
    those is anybody. A customer request always carries one -- `require_tenant`
    puts the token's `sub` on the context -- so this raises rather than
    returning null.

    **Fail closed rather than silently.** Without it a personal write with no
    subject would build a statement the policy matches nothing for: no row
    written, no error raised, 200 answered, and the value the caller just set
    is gone on the next read. A refusal naming the reason is a better day for
    everybody than a preference that does not stick.
    """
    if not tenant.user_id:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.ROLE_REQUIRED,
            "this request carries no verified subject, so it cannot act for a person",
        )
    return tenant.user_id
