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
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict

from ..core.platform_auth import PlatformMachineDep

router = APIRouter(tags=["platform"])


class Organization(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
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


@router.post("/tenants", response_model=TenantResponse)
async def create_tenant(
    body: TenantCreateRequest,
    _principal: PlatformMachineDep,
    response: Response,
) -> TenantResponse:
    """Create the tenant, or return the one this key already names.

    Returns 201 when this call created the tenant and 200 when it already
    existed. The Control Plane relies on that distinction; do not collapse it.

    Replace the in-memory store below with the real tenant table. Keep the
    lookup by tenant_key first: it is what makes the call idempotent.
    """
    existing = _TENANTS.get(body.tenant_key)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return TenantResponse(**existing)

    tenant = {
        "tenant_id": f"TEN-{body.tenant_key}",
        "tenant_key": body.tenant_key,
        "status": "provisioning",
    }
    _TENANTS[body.tenant_key] = tenant
    response.status_code = status.HTTP_201_CREATED
    return TenantResponse(**tenant)


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: str, _principal: PlatformMachineDep) -> TenantResponse:
    for tenant in _TENANTS.values():
        if tenant["tenant_id"] == tenant_id:
            return TenantResponse(**tenant)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such tenant")


@router.post("/tenants/{tenant_id}/activate", response_model=TenantResponse)
async def activate_tenant(tenant_id: str, _principal: PlatformMachineDep) -> TenantResponse:
    return _set_status(tenant_id, "active")


@router.post("/tenants/{tenant_id}/suspend", response_model=TenantResponse)
async def suspend_tenant(tenant_id: str, _principal: PlatformMachineDep) -> TenantResponse:
    """Suspend, never delete.

    The Control Plane calls this during rollback. The customer may already have
    data behind the tenant, and a failed provisioning run is not a reason to
    destroy it.
    """
    return _set_status(tenant_id, "suspended")


def _set_status(tenant_id: str, new_status: str) -> TenantResponse:
    for tenant in _TENANTS.values():
        if tenant["tenant_id"] == tenant_id:
            tenant["status"] = new_status
            return TenantResponse(**tenant)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such tenant")


# Placeholder store. Replace with the tenant table; the contract, not the
# storage, is what this module is for.
_TENANTS: dict[str, dict[str, str]] = {}
