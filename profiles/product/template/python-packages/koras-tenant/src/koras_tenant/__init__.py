"""Which tenant a verified caller is acting for.

The token names a ZITADEL organization. The database keys everything on a
tenant's own primary key. This module is the one place that crosses between
them, and it does it with a real query rather than by assuming the two
identifiers are the same value -- which is what the first version did, and which
would have made `current_tenant_id()` try to cast a numeric organization id to a
uuid the moment any route actually used it.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class TenantContext:
    """A resolved tenant. `id` is the primary key row-level security scopes on."""

    id: str
    slug: str
    name: str
    organization_id: str


async def set_organization_context(session: AsyncSession, organization_id: str) -> None:
    """Name the caller's organization for the lookup that follows.

    Transaction-local, exactly as `set_rls_context` is, so it cannot outlive the
    request on a pooled connection and be inherited by whoever gets that
    connection next.

    `set_config` rather than `SET LOCAL`, for the same reason the tenant context
    uses it: `SET` takes no bind parameters, so the value would have to be
    interpolated into the statement -- turning a token claim into an injection
    vector in the one function the tenant boundary is about to depend on.
    """
    await session.execute(
        text("select set_config('app.zitadel_org_id', :organization_id, true)"),
        {"organization_id": organization_id},
    )


async def resolve_tenant(
    session: AsyncSession, organization_id: str | None
) -> TenantContext | None:
    """The tenant this organization owns, or nothing.

    Runs under the organization-keyed select policy added in migration 00004,
    so this is not a privileged read: the caller sees the row their own verified
    token selects, and no other. The session handed in must be one nothing else
    is using -- setting the organization context on a session that later serves
    tenant queries would leave two keys live at once.

    A suspended tenant resolves to nothing. It is not the same as a missing one
    to whoever runs the platform, and it is the same to the caller: both mean
    this account cannot act here. Distinguishing them in the answer would tell
    somebody probing that an organization exists and has been turned off.

    Two rows cannot happen -- `zitadel_org_id` is unique -- and if the
    constraint were ever dropped this takes none rather than the first. Picking
    one would silently scope a session to whichever the planner returned.
    """
    if not organization_id:
        return None

    await set_organization_context(session, organization_id)
    result = await session.execute(
        text(
            "select id::text, slug, name from public.tenants "
            "where zitadel_org_id = :organization_id and status = 'active'"
        ),
        {"organization_id": organization_id},
    )
    rows = result.fetchall()
    if len(rows) != 1:
        return None

    tenant_id, slug, name = rows[0]
    return TenantContext(
        id=tenant_id, slug=slug, name=name, organization_id=organization_id
    )
