"""The customer-facing tenant surface.

One route, and the API's first one that a browser reaches. It answers the
question the frontend has been unable to ask since `tenant_settings` was
created: what has this customer configured for themselves.

**Why one route and not two.** Branding and features live in the same row, and
the frontend needs both on the same page load — the shell resolves navigation
against the features and paints itself with the branding. Two endpoints would be
two round trips for one row, and they would be able to disagree with each other
about which version of that row a page was rendered from.

**What it does not do.** It does not accept a tenant id. There is nowhere to put
one: the tenant comes from `require_tenant`, which resolves it from a token this
service verified against ZITADEL, and the session it reads on is scoped by
row-level security to that tenant. A caller cannot ask for another customer's
settings because there is no parameter in which to ask.

**What it does not validate.** The stored values are returned as they are
stored. Deciding which of a customer's colours may reach a stylesheet is the
browser tier's job and is already done there — `parseTenantBranding` accepts hex
only, same-origin image paths only, and drops what it does not recognise. Doing
it twice, in two languages, would be two rules to keep in step; doing it only
here would put the check a long way from the `style` attribute it protects.
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..core.database import DbSession
from ..core.tenant import TenantDep

router = APIRouter(tags=["tenant"])


class TenantSettingsResponse(BaseModel):
    """What a signed-in customer may know about their own tenant.

    Four fields, and the two that are not obviously needed both are. `name` is
    what the product shell shows beside its own logo — the session carries a
    ZITADEL organization id, which is a uuid, and a uuid where a name belongs
    reads as a bug. `slug` is what a product uses to build its own
    tenant-scoped links.

    Nothing here is a credential, an internal column or a platform identifier.
    `tenant_key`, `organization_id` and `owner_email` are all on the row and all
    absent from this model: they are the Control Plane's references, and a
    response model is a published contract.
    """

    name: str
    slug: str
    # The customer's own branding, exactly as stored. Empty is the normal state
    # and means "use the product's own", which is a finished answer rather than
    # a missing one.
    branding: dict[str, Any] = Field(default_factory=dict)
    # Optional features this customer has switched on. Absent means off.
    features: dict[str, Any] = Field(default_factory=dict)


@router.get("/tenant/settings", response_model=TenantSettingsResponse)
async def tenant_settings(tenant: TenantDep, session: DbSession) -> TenantSettingsResponse:
    """This caller's own tenant settings.

    A left join, because `tenant_settings` is written by whoever first saves
    branding and not by provisioning: a tenant that has configured nothing has
    no row, and that is not an error to report. An inner join would answer 404
    for the commonest case in a new product.

    The session is already scoped — `get_db` set `app.tenant_id` from the
    resolved tenant — so the `where` clause below is belt as well as braces. It
    stays because a policy is a backstop against a query that forgets, not a
    substitute for one that remembers, and because a reader of this function
    should be able to see what it selects without going to find the policy.
    """
    result = await session.execute(
        text(
            "select t.name, t.slug, "
            "coalesce(s.branding, '{}'::jsonb), coalesce(s.features, '{}'::jsonb) "
            "from public.tenants t "
            "left join public.tenant_settings s on s.tenant_id = t.id "
            "where t.id = :tenant_id"
        ),
        {"tenant_id": tenant.id},
    )
    row = result.first()

    if row is None:
        # Reachable only if the row vanished between resolving the tenant and
        # this query. The tenant's own name is the better answer than a 500:
        # the caller gets the product's default branding, which is what they
        # would have got from an empty settings row anyway.
        return TenantSettingsResponse(name=tenant.name, slug=tenant.slug)

    name, slug, branding, features = row
    return TenantSettingsResponse(
        name=name,
        slug=slug,
        branding=branding if isinstance(branding, dict) else {},
        features=features if isinstance(features, dict) else {},
    )
