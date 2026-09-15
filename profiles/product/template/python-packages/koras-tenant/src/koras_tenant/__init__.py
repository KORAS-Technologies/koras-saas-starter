"""Which tenant a verified caller is acting for.

The token names a ZITADEL organization. The database keys everything on a
tenant's own primary key. This module is the one place that crosses between
them, and it does it with a real query rather than by assuming the two
identifiers are the same value -- which is what the first version did, and which
would have made `current_tenant_id()` try to cast a numeric organization id to a
uuid the moment any route actually used it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from koras_database import declare
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class TenantContext:
    """A resolved tenant. `id` is the primary key row-level security scopes on.

    `user_id` is the verified subject the request acts for, filled in by the
    API's tenant dependency after the lookup. The lookup itself knows only the
    organization, which is why the field is optional here and set once the
    caller is known -- a context resolved for a job that acts for nobody in
    particular carries none, and the policies keyed to a person then admit
    nothing.
    """

    id: str
    slug: str
    name: str
    organization_id: str
    user_id: str | None = None


# ── What a transaction may be for, in this profile's vocabulary ──────────────
#
# `koras_database` carries the guard, the event and the refusal; it deliberately
# carries no setting names. These are the product's. The Control Plane's are its
# own and mean nothing here.
#
# Every one is transaction-local -- the `true` third argument to `set_config`.
# A session-scoped setting would outlive the work and reach whichever client is
# handed that server connection next, which is a cross-tenant leak created by
# pooling rather than prevented by it.


@dataclass(frozen=True)
class Tenant:
    """One tenant's rows, and nothing else. What a customer request runs as.

    `user_id` names the person the request acts for, where there is one. It is
    what `current_user_id()` reads, and the only rows that consult it are the
    ones a person may write about themselves and nobody else may read --
    their language preference, first (migration 00017). A task with no person
    behind it -- a scheduled job, the platform's collector -- declares none,
    and those policies then admit nothing, which is the fail-closed answer.
    """

    tenant_id: str
    user_id: str | None = None

    def settings(self) -> Mapping[str, str]:
        # `app.provisioning` is cleared as well as `app.tenant_id` being set.
        # It is transaction-local too, so on any path reachable from here it is
        # already empty -- but "already empty" is a property of how the sessions
        # happen to be opened today. A tenant request that ran with the
        # provisioning flag still set would read every tenant's rows, and the
        # cost of not relying on that is one entry in a dictionary.
        #
        # `app.user_id` is set to the empty string rather than left alone when
        # there is no person, for the same reason: `current_user_id()` turns
        # the empty string into null, and a value inherited from an earlier
        # transaction on this connection is exactly what a transaction-local
        # setting is meant to make impossible.
        return {
            "app.tenant_id": self.tenant_id,
            "app.user_id": self.user_id or "",
            "app.provisioning": "off",
        }


@dataclass(frozen=True)
class Provisioning:
    """The platform creating a tenant, before there is a tenant to scope to.

    Creating the tenant is the point, so the policies keyed to
    `current_tenant_id()` match no row and an insert against them is refused
    rather than merely returning nothing. The schema therefore carries a second,
    narrow set of policies gated on this flag, and this is the only declaration
    that sets it.

    What it grants is real and worth stating plainly: within such a transaction
    the connection reads and writes every tenant row. Three properties are what
    make that safe rather than an escape hatch -- it is transaction-local, it is
    derived from no request input so a caller cannot ask for it, and the one
    dependency that uses it serves the private platform router, which admits a
    machine identity alone.
    """

    def settings(self) -> Mapping[str, str]:
        return {"app.provisioning": "on"}


@dataclass(frozen=True)
class OrganizationLookup:
    """Resolving which tenant an organization owns, before either is known.

    The declaration that a guard makes necessary and a pair of helpers did not.
    `resolve_tenant` runs on a session with no tenant context -- finding the
    tenant is what it is for -- so under `install_rls` it must still say what it
    is, or the transaction refuses to open.

    That is the mechanism working rather than a wrinkle in it: the lookup reads
    a table scoped by organization, and naming the organization is exactly what
    scopes it.
    """

    organization_id: str

    def settings(self) -> Mapping[str, str]:
        return {"app.zitadel_org_id": self.organization_id}


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

    declare(OrganizationLookup(organization_id=organization_id))
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
