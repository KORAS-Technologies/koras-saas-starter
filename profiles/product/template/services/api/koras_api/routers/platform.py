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
on `koras_tenant.Provisioning`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Response, status
from koras_settings import SettingError, coerce
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import settings_store, tenant_store
from ..core.database import PlatformSession
from ..core.errors import ApiErrorCode, api_error
from ..core.platform_auth import PlatformMachineDep
from ..core.settings import settings
from ..settings_catalogue import catalogue

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
    # The identifier a tenant is resolved by. Every customer request carries
    # the ZITADEL organization in its token and row-level security scopes on
    # this column; a tenant created without it can be recorded and listed
    # and never reached. Optional in the schema because the Control Plane
    # sent none until 2026-09-09 (R-105) and a repeat call fills it in.
    zitadel_org_id: str | None = None


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
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ApiErrorCode.ENVIRONMENT_MISMATCH,
            f"This service serves the {settings.environment.value!r} environment; "
            f"the request names {body.environment!r}",
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
            zitadel_org_id=body.organization.zitadel_org_id,
        )
    except tenant_store.SlugTaken as exc:
        # Not the retry case, which is answered above with 200. This is a
        # second organization asking for a name the first one holds, and it
        # needs a person to choose a different one.
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiErrorCode.SLUG_TAKEN,
            f"Another organization already holds the slug {exc.args[0]!r}",
        ) from exc

    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _response(tenant)


class PlanEntitlement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    enabled: bool = False
    limit_value: int | None = None


class PlanSnapshot(BaseModel):
    """The plan as the platform resolved it for this tenant's organization.

    The same fields the portal's entitlement answer carries, so a product
    stores what a signed-in customer would have been told. A tenant whose
    organization holds no subscription arrives with no plan and no
    entitlements: that is a real answer, and it is stored.
    """

    model_config = ConfigDict(extra="ignore")

    plan_code: str | None = None
    status: str | None = None
    entitlements: list[PlanEntitlement] = []
    trial_ends_at: datetime | None = None
    current_period_end: datetime | None = None


@router.put("/tenants/{tenant_id}/plan", status_code=status.HTTP_204_NO_CONTENT)
async def sync_plan(
    tenant_id: str,
    body: PlanSnapshot,
    _principal: PlatformMachineDep,
    session: PlatformSession,
) -> Response:
    """Replace what this product knows of the tenant's plan.

    Written by the Control Plane's hourly sync and read by the worker when
    it delivers a scheduled report -- the one reader with no customer token
    to resolve the plan live. Every page still resolves it live; this is
    what stands in where nobody is signed in.
    """
    recorded = await tenant_store.record_plan(
        session,
        tenant_id,
        plan_code=body.plan_code,
        status=body.status,
        entitlements={
            row.code: {"enabled": row.enabled, "limit": row.limit_value}
            for row in body.entitlements
        },
        trial_ends_at=body.trial_ends_at,
        period_ends_at=body.current_period_end,
    )
    if not recorded:
        raise api_error(status.HTTP_404_NOT_FOUND, ApiErrorCode.TENANT_NOT_FOUND, "No such tenant")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class StorageDefaults(BaseModel):
    """Where this product keeps files unless a customer's policy says otherwise.

    Read by the Control Plane when it provisions a customer and when it
    backfills the storage policies of customers provisioned before it asked.
    The values are this deployment's own settings, from Doppler: the bucket
    and region the product signs uploads against when a policy names none.
    Never a credential -- the key pair stays in Doppler and is not a
    reference the Control Plane holds.
    """

    provider: str
    bucket: str | None
    region: str | None


@router.get("/storage-defaults", response_model=StorageDefaults)
async def storage_defaults(_principal: PlatformMachineDep) -> StorageDefaults:
    return StorageDefaults(
        provider="supabase",
        bucket=settings.storage_bucket or None,
        region=settings.storage_region or None,
    )


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: str,
    _principal: PlatformMachineDep,
    session: PlatformSession,
) -> TenantResponse:
    tenant = await tenant_store.find_by_id(session, tenant_id)
    if tenant is None:
        raise api_error(status.HTTP_404_NOT_FOUND, ApiErrorCode.TENANT_NOT_FOUND, "No such tenant")
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
        raise api_error(status.HTTP_404_NOT_FOUND, ApiErrorCode.TENANT_NOT_FOUND, "No such tenant")
    return _response(tenant)


# ── Settings: what this product declares, and what the platform has set ──────
#
# Three routes, and the third is the first write the platform contract admits.
#
# The platform cannot learn a product's settings from its own database: a
# definition is code in the product, and the console manages several products
# that were not built alongside it. So the catalogue is published, and a console
# renders a form from metadata rather than from anything it knew in advance.


class SettingDefinitionView(BaseModel):
    """One setting's definition, for a console that has never seen this product.

    Metadata only, and no value at any scope. `label_key` is a key and never a
    sentence: the words live in this product's own catalogues, so a console
    shows the key when it has no translation of its own rather than inventing
    one.
    """

    key: str
    category: str
    data_type: str
    default: object
    scope: str
    label_key: str
    description_key: str
    options: list[str]
    minimum: float | None
    maximum: float | None
    ui: str
    order: int
    org_admin_visible: bool
    user_visible: bool


class GlobalSettings(BaseModel):
    """What the platform has set, and the version it is at.

    A key absent from `values` resolves to the definition's own default, which
    is the normal state of a new estate rather than a gap to fill. `version` is
    zero when nobody has changed anything.
    """

    values: dict[str, object]
    version: int


class GlobalSettingsWrite(BaseModel):
    """What the console is replacing.

    `values` and nothing else. There is deliberately no tenant here, and the
    route above it takes none: an organisation's settings are the snapshot that
    makes a customer independent of platform changes, and a console able to
    rewrite one would undo the point of taking it.
    """

    model_config = ConfigDict(extra="forbid")

    values: dict[str, object]


@router.get("/settings/definitions", response_model=list[SettingDefinitionView])
async def setting_definitions(_principal: PlatformMachineDep) -> list[SettingDefinitionView]:
    """Every setting this product declares, in display order.

    Unfiltered, unlike the customer-facing catalogue: the console is the
    platform, and a setting hidden from a customer -- one nothing honours yet,
    or one the platform sets on their behalf -- is exactly what an operator may
    need to see. Deprecated definitions are left out, because nothing should be
    set through a console that no surface offers.
    """
    return [
        SettingDefinitionView(
            key=definition.key,
            category=str(definition.category),
            data_type=str(definition.data_type),
            default=list(definition.default)
            if isinstance(definition.default, tuple)
            else definition.default,
            scope=str(definition.scope),
            label_key=definition.label_key,
            description_key=definition.description_key,
            options=list(definition.options),
            minimum=definition.minimum,
            maximum=definition.maximum,
            ui=str(definition.ui),
            order=definition.order,
            org_admin_visible=definition.org_admin_visible,
            user_visible=definition.user_visible,
        )
        for definition in catalogue.offered()
    ]


@router.get("/settings/global", response_model=GlobalSettings)
async def read_global_settings(
    _principal: PlatformMachineDep, session: PlatformSession
) -> GlobalSettings:
    return GlobalSettings(
        values=await settings_store.global_values(session),
        version=await settings_store.global_version(session),
    )


@router.put("/settings/global", response_model=GlobalSettings)
async def write_global_settings(
    body: GlobalSettingsWrite,
    _principal: PlatformMachineDep,
    session: PlatformSession,
) -> GlobalSettings:
    """Replace the platform defaults, at a new version.

    Every value is held to its own definition before anything is written, and
    the whole request is refused on the first one that fails. A half-applied set
    of defaults is the state hardest to account for afterwards: a tenant seeded
    in between would carry some of an operator's intent and not the rest, at a
    version that claims to name all of it.

    A key nobody declared is refused rather than stored. A console renders from
    this product's published catalogue, so a key that is not in it came from a
    console built against a different version -- which is worth an error rather
    than a row nothing will ever read.
    """
    accepted: dict[str, object] = {}
    for key, raw in body.values.items():
        definition = catalogue.get(key)
        if definition is None:
            raise api_error(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.SETTING_NOT_FOUND,
                f"this product declares no setting called {key!r}",
            )
        try:
            value = coerce(definition, raw)
        except SettingError as invalid:
            raise api_error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                ApiErrorCode.SETTING_VALUE_INVALID,
                invalid.message,
            ) from invalid
        accepted[key] = list(value) if isinstance(value, tuple) else value

    version, _written = await settings_store.write_global_values(session, accepted)
    await session.commit()
    return GlobalSettings(values=await settings_store.global_values(session), version=version)
