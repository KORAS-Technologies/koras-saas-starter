"""The customer-facing tenant surface.

Three routes: what this customer has configured for themselves, and the two
writes a language choice needs once it is more than a cookie. The read was the
API's first route a browser reaches; the writes are its first that a member
makes about themselves rather than about a file or a report.

**Why one read and not two.** Branding, features and the default language live
in the same row, and the frontend needs all of them on the same page load — the
shell resolves navigation against the features, paints itself with the
branding, and decides which language to render in before either. Two endpoints
would be two round trips for one row, and they would be able to disagree with
each other about which version of that row a page was rendered from. The
caller's own preference rides along for the same reason: it is read on every
signed-in request, by the same code, to answer the same question.

**What it does not do.** It does not accept a tenant id, and the writes do not
accept a user id. There is nowhere to put either: the tenant comes from
`require_tenant`, which resolves it from a token this service verified against
ZITADEL, the subject comes from the same token, and the session it reads on is
scoped by row-level security to that tenant and — for the preference — to that
subject. A caller cannot ask for another customer's settings or write another
person's preference because there is no parameter in which to ask.

**What it does not validate.** The stored branding is returned as it is stored.
Deciding which of a customer's colours may reach a stylesheet is the browser
tier's job and is already done there — `parseTenantBranding` accepts hex only,
same-origin image paths only, and drops what it does not recognise. Doing it
twice, in two languages, would be two rules to keep in step; doing it only here
would put the check a long way from the `style` attribute it protects.

The locale is the exception, and it is validated twice on purpose. Here it is
held to the catalogues this product's frontend can speak, so a row can never
hold a value no page could render. There it is held again to the shorter list
the product *offers*, because a catalogue can exist without being switched on,
and `lang` on the document is where the value ends up.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from koras_auth.permissions import permissions_for
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..core.auth import AuthDep
from ..core.database import DbSession
from ..core.tenant import TenantDep

router = APIRouter(tags=["tenant"])

#: The languages a stored preference may name.
#:
#: The same list `packages/i18n` declares as `SUPPORTED_LOCALES` -- what the
#: frontend can speak, as distinct from what a product offers. Duplicated
#: rather than shared because the two runtimes cannot import each other, and
#: kept level by the generator's structural test, the same way the permission
#: catalogue is. Add a catalogue there and a code here in the same commit, or
#: the test says which side is behind.
SUPPORTED_LOCALES: tuple[str, ...] = ("en", "de", "es")


class TenantSettingsResponse(BaseModel):
    """What a signed-in customer may know about their own tenant.

    Six fields, and the two that are not obviously needed both are. `name` is
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
    # The language the organisation's members see before they choose one.
    # Null means the product decides, from the browser and its own default.
    locale: str | None = None
    # The language this caller chose for themselves, on any device. Null means
    # they have not, and the cookie or the tenant's default applies. Read under
    # a policy keyed to the caller's own subject, so it is theirs and only theirs.
    member_locale: str | None = None


class LocaleChoice(BaseModel):
    """A language, or none.

    Null clears the choice rather than deleting a row, so "I no longer want a
    preference" is the same statement as "I want German" with a different
    value, and the same policy admits both.
    """

    locale: str | None = Field(default=None, max_length=8)


def _require_supported(locale: str | None) -> str | None:
    """A stored language is one this product's frontend can render, or nothing.

    422, the same answer as a body of the wrong shape: a language this product
    has no catalogue for is not a permission problem or a commercial one, it is
    a value the request could not have got from the switcher.
    """
    if locale is None or locale in SUPPORTED_LOCALES:
        return locale
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"locale must be one of {', '.join(SUPPORTED_LOCALES)}",
    )


@router.get("/tenant/settings", response_model=TenantSettingsResponse)
async def tenant_settings(tenant: TenantDep, session: DbSession) -> TenantSettingsResponse:
    """This caller's own tenant settings, and their own preference beside it.

    A left join, because `tenant_settings` is written by whoever first saves
    something and not by provisioning: a tenant that has configured nothing has
    no row, and that is not an error to report. An inner join would answer 404
    for the commonest case in a new product. The preference joins the same
    way for the same reason -- most members never choose.

    The session is already scoped — `get_db` set `app.tenant_id` and
    `app.user_id` from the resolved tenant and the verified subject — so the
    `where` clause below is belt as well as braces. It stays because a policy
    is a backstop against a query that forgets, not a substitute for one that
    remembers, and because a reader of this function should be able to see
    what it selects without going to find the policy.
    """
    result = await session.execute(
        text(
            "select t.name, t.slug, "
            "coalesce(s.branding, '{}'::jsonb), coalesce(s.features, '{}'::jsonb), "
            "s.locale, p.locale "
            "from public.tenants t "
            "left join public.tenant_settings s on s.tenant_id = t.id "
            "left join public.member_preferences p "
            "  on p.tenant_id = t.id and p.user_id = :user_id "
            "where t.id = :tenant_id"
        ),
        {"tenant_id": tenant.id, "user_id": tenant.user_id},
    )
    row = result.first()

    if row is None:
        # Reachable only if the row vanished between resolving the tenant and
        # this query. The tenant's own name is the better answer than a 500:
        # the caller gets the product's default branding, which is what they
        # would have got from an empty settings row anyway.
        return TenantSettingsResponse(name=tenant.name, slug=tenant.slug)

    name, slug, branding, features, locale, member_locale = row
    return TenantSettingsResponse(
        name=name,
        slug=slug,
        branding=branding if isinstance(branding, dict) else {},
        features=features if isinstance(features, dict) else {},
        locale=locale if isinstance(locale, str) else None,
        member_locale=member_locale if isinstance(member_locale, str) else None,
    )


@router.put("/me/locale", status_code=status.HTTP_204_NO_CONTENT)
async def set_my_locale(
    body: LocaleChoice, tenant: TenantDep, session: DbSession
) -> Response:
    """Remember the language this caller chose, for every device they sign in on.

    Any member may: the choice is about themselves and changes nothing for
    anybody else, which is the same argument the cookie already rests on. The
    row is keyed on the tenant and the verified subject, both of which the
    statement takes from the resolved context rather than the body -- and the
    policy that admits the write checks both against what the session
    declared, so a statement that named somebody else would write nothing.

    An upsert, because most members have no row until they choose, and a
    choice made twice is a replacement rather than a conflict.
    """
    locale = _require_supported(body.locale)
    await session.execute(
        text(
            "insert into public.member_preferences (tenant_id, user_id, locale) "
            "values (cast(:tenant_id as uuid), :user_id, :locale) "
            "on conflict (tenant_id, user_id) do update set locale = excluded.locale"
        ),
        {"tenant_id": tenant.id, "user_id": tenant.user_id, "locale": locale},
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/tenant/settings/locale", status_code=status.HTTP_204_NO_CONTENT)
async def set_tenant_locale(
    body: LocaleChoice, claims: AuthDep, tenant: TenantDep, session: DbSession
) -> Response:
    """Set the language this organisation's members see before they choose.

    `settings.manage` -- owners and administrators -- because this is a choice
    about everybody in the tenant rather than about the caller. The permission
    is resolved from the roles the verified token carries, through the same
    catalogue the sidebar and the Files router use, so the page that hides the
    form and the route that refuses the write read one rule.

    403, not 404: the caller is a member and the settings exist; what they lack
    is the authority to change this one for other people.

    An upsert into `tenant_settings`, because the row is created by whoever
    first writes anything -- branding or this -- and a tenant that has never
    configured either has none.
    """
    if "settings.manage" not in permissions_for(claims.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an administrator may set the organisation's language",
        )
    locale = _require_supported(body.locale)
    await session.execute(
        text(
            "insert into public.tenant_settings (tenant_id, locale) "
            "values (cast(:tenant_id as uuid), :locale) "
            "on conflict (tenant_id) do update set locale = excluded.locale"
        ),
        {"tenant_id": tenant.id, "locale": locale},
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
