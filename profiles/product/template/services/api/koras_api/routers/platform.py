"""The private platform API the Control Plane calls.

This is the product side of a two-way contract; the Control Plane side lives in
koras-control-plane. Both halves are versioned in the path, and a breaking
change means /v2 running alongside /v1 until every product has migrated.

Two rules carry the weight, and both are easy to get wrong:

**A repeat is not a conflict.** The Control Plane derives the tenant key, so a
retried create names the same tenant. Answering with 409 would make a retryable
operation fail; answering 200 with the existing tenant is what lets the Control
Plane tell a first attempt from a retry.

**Machine identity only.** These endpoints are not part of any interactive flow.
A browser-obtained token reaching one is a mistake or an attack, so a human
token is refused even when the human is an administrator.

Tenants are persisted through `core.tenant_store`, on the provisioning session
from `core.database` -- which has no tenant context, because creating the tenant
is what these routes are for. What that grants, and why it is confined here, is
in `koras_database.set_provisioning_context`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import tenant_store
from ..core.database import PlatformSession
from ..core.platform_auth import PlatformMachineDep
from ..core.settings import settings

router = APIRouter(tags=["platform"])


class Organization(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # A uuid, and typed as one so a malformed value is a 422 naming the field
    # rather than a DataError out of the driver three layers down. The column it
    # lands in is `uuid` too: this is the Control Plane's own organization id,
    # which is what the product needs in order to ask what the customer may do
    # -- entitlements resolve per organization and product, not per tenant.
    id: UUID
    name: str
    slug: str


class Owner(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: str
    zitadel_user_id: str | None = None
    name: str | None = None


class TenantCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Supplied by the Control Plane and deterministic. Never generated here:
    # the caller has to be able to name the same tenant again after a timeout.
    tenant_key: str
    organization: Organization
    owner: Owner
    plan: str
    environment: str


class TenantResponse(BaseModel):
    tenant_id: str
    tenant_key: str
    status: str


def _response(tenant: tenant_store.TenantRow) -> TenantResponse:
    return TenantResponse(
        tenant_id=tenant.tenant_id,
        tenant_key=tenant.tenant_key,
        status=tenant.status,
    )


@router.post("/tenants", response_model=TenantResponse)
async def create_tenant(
    body: TenantCreateRequest,
    _principal: PlatformMachineDep,
    session: PlatformSession,
    response: Response,
) -> TenantResponse:
    """Create the tenant, or return the one this key already names.

    Returns 201 when this call created the tenant and 200 when it already
    existed. The Control Plane relies on that distinction; do not collapse it.
    """
    # This database belongs to one environment. A request naming another is a
    # misconfigured caller -- a dev Control Plane holding a prod address, or the
    # reverse -- and writing the row anyway would put a customer's prod tenant
    # in a dev database, which is the boundary the whole estate is arranged
    # around. 422 rather than a retryable code on purpose: the Control Plane's
    # retry policy fails a 4xx immediately, and this input will not become valid
    # by being sent again.
    if body.environment != settings.environment.value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"This service serves the {settings.environment.value!r} environment; "
                f"the request names {body.environment!r}"
            ),
        )

    try:
        tenant, created = await tenant_store.create(
            session,
            tenant_key=body.tenant_key,
            organization_id=str(body.organization.id),
            name=body.organization.name,
            slug=body.organization.slug,
            plan=body.plan,
            owner_email=body.owner.email,
            owner_zitadel_user_id=body.owner.zitadel_user_id,
        )
    except tenant_store.SlugTaken as exc:
        # Not the retry case, which is answered above with 200. This is a
        # second organization asking for a name the first one holds, and it
        # needs a person to choose a different one.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Another organization already holds the slug {exc.args[0]!r}",
        ) from exc

    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _response(tenant)


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: str,
    _principal: PlatformMachineDep,
    session: PlatformSession,
) -> TenantResponse:
    tenant = await tenant_store.find_by_id(session, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such tenant")
    return _response(tenant)


@router.post("/tenants/{tenant_id}/activate", response_model=TenantResponse)
async def activate_tenant(
    tenant_id: str,
    _principal: PlatformMachineDep,
    session: PlatformSession,
) -> TenantResponse:
    return await _set_status(session, tenant_id, "active")


@router.post("/tenants/{tenant_id}/suspend", response_model=TenantResponse)
async def suspend_tenant(
    tenant_id: str,
    _principal: PlatformMachineDep,
    session: PlatformSession,
) -> TenantResponse:
    """Suspend, never delete.

    The Control Plane calls this during rollback. The customer may already have
    data behind the tenant, and a failed provisioning run is not a reason to
    destroy it.
    """
    return await _set_status(session, tenant_id, "suspended")


async def _set_status(session: AsyncSession, tenant_id: str, new_status: str) -> TenantResponse:
    """Both status routes, which differ only in the word.

    Idempotent by being an assignment rather than a transition: activating an
    active tenant is the state the caller asked for, and refusing it would make
    a retry fail for having already worked.
    """
    tenant = await tenant_store.set_status(session, tenant_id, new_status)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such tenant")
    return _response(tenant)
