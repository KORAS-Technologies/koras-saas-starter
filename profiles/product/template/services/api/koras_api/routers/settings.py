"""The settings surface: what a setting is, what it resolves to, and who may change it.

Eight routes across three audiences, and the division between them is the whole
authorization model.

**`/settings/effective` needs no permission at all.** Every signed-in request
reads it — the shell resolves a customer's settings before it paints — and a
permission on it would mean a member without `settings.read` sees an
unstyled page rather than a refusal. What protects it is that it answers only
for the caller's own tenant and the caller's own subject, and there is no
parameter in which to ask for anybody else's.

**`settings.manage` guards the organisation's values**, because those decide for
other people. **A person's own values are guarded by nothing but the policy
keyed to their subject**, which is the same position `PUT /me/locale` already
takes: choosing your own theme is not an act that needs authority, and what
makes it safe is that the row cannot be written for somebody else.

**The catalogue is published rather than mirrored.** A definition is declared in
Python and registered at import; the browser reads its label key, type, bounds
and options from here and renders the control from that metadata. So a new
setting is a definition and three translations, and no page changes.

**What this router refuses, and with which code.** A value the definition will
not take is 422 `setting_value_invalid`, because the sender can fix it by
sending another. A scope that may not hold it is 403 `setting_scope_refused`,
because no value would satisfy it. A key nobody declared is 404
`setting_not_found` — refused rather than ignored, so a caller that misspelled
one is told, instead of being answered 200 by a request that changed nothing.
"""

from typing import Any

from fastapi import APIRouter, Response, status
from koras_auth import JWTClaims
from koras_auth.permissions import permissions_for
from koras_settings import (
    Resolved,
    Scope,
    ScopeRefused,
    SettingDefinition,
    SettingError,
    check_writable,
    coerce,
    resolve_all,
)
from koras_tenant import TenantContext
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit import record
from ..core.auth import AuthDep
from ..core.database import DbSession
from ..core.errors import ApiErrorCode, api_error
from ..core.settings_store import (
    Change,
    as_json,
    clear_member_value,
    global_values,
    member_values,
    reset_tenant_value,
    tenant_values,
    write_member_values,
    write_tenant_values,
)
from ..core.tenant import TenantDep, require_subject
from ..settings_catalogue import catalogue

router = APIRouter(tags=["settings"])

#: Reading the catalogue and the organisation's own values.
READ_PERMISSION = "settings.read"

#: Changing a value for everybody in the tenant. Owners and administrators.
MANAGE_PERMISSION = "settings.manage"


class DefinitionView(BaseModel):
    """One setting, as a surface needs it to draw a control.

    Everything here is metadata. No value, at any scope: a definition says what
    a setting *is*, and what it currently *is set to* is `/settings/effective`,
    which is a different question with a different cache lifetime and a
    different audience.
    """

    key: str
    category: str
    data_type: str
    default: Any
    scope: str
    label_key: str
    description_key: str
    options: list[str] = Field(default_factory=list)
    minimum: float | None = None
    maximum: float | None = None
    ui: str
    order: int
    #: Whether an administrator may change it for the organisation.
    org_admin_visible: bool
    #: Whether this caller may change it for themselves.
    user_visible: bool


class ResolvedView(BaseModel):
    """One setting's answer for this caller, and where it came from.

    `source` and the two fallback values are not decoration. A settings page has
    to say whether a value is the default or somebody's choice, and both reset
    controls have to name what they would restore *before* they are pressed. A
    surface deriving that by comparing against the default gets it wrong the
    moment somebody deliberately sets a value equal to it.
    """

    key: str
    value: Any
    source: str
    can_override: bool
    organization_value: Any
    global_value: Any


class EffectiveSettings(BaseModel):
    """Every setting, resolved, in one answer.

    One request rather than one per key, which is what the shell needs: it
    resolves the whole set once per navigation and hands it to a provider.

    `skipped` is the honest half. A bound tightened or an option withdrawn in a
    deploy leaves rows that were valid when written; the resolver falls through
    to the next level rather than refusing to render, and says here what it
    passed over — so an operator can find them without a customer reporting a
    page that will not load.
    """

    settings: dict[str, ResolvedView]
    skipped: list[str] = Field(default_factory=list)


class ValueMap(BaseModel):
    """A write: keys to values, several at once.

    Several, because a settings page saves a category rather than a field, and
    one transaction for the category means a partial save cannot happen. An
    unknown key refuses the whole request rather than the one entry — a
    half-applied write is the outcome hardest to explain afterwards.
    """

    values: dict[str, Any]


def _definition_view(definition: SettingDefinition) -> DefinitionView:
    return DefinitionView(
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


def _resolved_view(answer: Resolved) -> ResolvedView:
    return ResolvedView(
        key=answer.key,
        value=_plain(answer.value),
        source=str(answer.source),
        can_override=answer.can_override,
        organization_value=_plain(answer.organization_value),
        global_value=_plain(answer.global_value),
    )


def _plain(value: Any) -> Any:  # noqa: ANN401
    """A resolved value as JSON has it.

    Only tuples need it — a `STRING_LIST` default is one, and JSON has no
    tuples. Every other type survives unchanged.
    """
    return list(value) if isinstance(value, tuple) else value


def _require(claims: JWTClaims, permission: str, doing: str) -> None:
    """The guard, called as the first statement of a handler.

    The convention this API uses everywhere — an explicit call rather than a
    dependency or a decorator — so that reading a handler shows what it
    refuses without going to find a decorator's definition.
    """
    if permission not in permissions_for(claims.roles):
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.PERMISSION_MISSING,
            f"{doing} needs the {permission} permission",
        )


def _definition(key: str) -> SettingDefinition:
    definition = catalogue.get(key)
    if definition is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.SETTING_NOT_FOUND,
            f"no setting is called {key!r}",
        )
    return definition


def _coerce_all(values: dict[str, Any], scope: Scope) -> dict[str, Any]:
    """Every value the definition will take, or the first refusal.

    Refused as a whole rather than key by key. A write that applied three of
    four changes and reported an error would leave a page showing values the
    caller did not choose, and no way to tell which.

    The scope check runs before the value check on purpose: telling somebody
    their value is out of range, when the real answer is that they may not set
    this setting at all, sends them to fix the wrong thing.
    """
    accepted: dict[str, Any] = {}
    for key, raw in values.items():
        definition = _definition(key)
        try:
            check_writable(definition, scope)
        except ScopeRefused as refusal:
            raise api_error(
                status.HTTP_403_FORBIDDEN,
                ApiErrorCode.SETTING_SCOPE_REFUSED,
                refusal.message,
            ) from refusal
        try:
            accepted[key] = _plain(coerce(definition, raw))
        except SettingError as invalid:
            raise api_error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                ApiErrorCode.SETTING_VALUE_INVALID,
                invalid.message,
            ) from invalid
    return accepted


async def _audit(
    session: AsyncSession,
    tenant: TenantContext,
    claims: JWTClaims,
    action: str,
    changes: list[Change],
) -> None:
    """One event per key that actually moved.

    Per key rather than per request, because that is the granularity the
    question is asked at: "who changed the upload limit, and from what".

    A sensitive definition has its values replaced rather than omitted, so the
    record still says a change happened. `koras_audit` refuses a detail key that
    looks like a secret, and `00029` refuses a secret-shaped value, so this is
    the third of three independent guards and none of them is the only one.
    """
    for change in changes:
        definition = catalogue.require(change.key)
        redacted = definition.sensitive
        await record(
            session,
            tenant_id=tenant.id,
            actor_id=claims.sub,
            action=action,
            target_type="setting",
            target_id=change.key,
            outcome="ok",
            details={
                "before": "(hidden)" if redacted else _as_detail(change.before),
                "after": "(hidden)" if redacted else _as_detail(change.after),
            },
        )


def _as_detail(value: Any) -> str | int | bool:  # noqa: ANN401
    """A value as an audit detail takes it.

    `AuditEvent` accepts strings, integers and booleans; a list or an object
    becomes its JSON text rather than being dropped, because a detail that is
    silently absent reads as a change from nothing.
    """
    if value is None:
        return "(none)"
    if isinstance(value, (str, int, bool)):
        return value
    return as_json(value)


@router.get("/settings/definitions", response_model=list[DefinitionView])
async def definitions(_tenant: TenantDep) -> list[DefinitionView]:
    """The catalogue, in display order.

    **No permission, and it required `settings.read` until 2026-09-19.** That
    was a defect, and a total one: `ROLE_PERMISSIONS[MEMBER]` does not carry
    `settings.read`, this route is the only source of the metadata the
    preferences page renders a control from, and the page swallows the failure
    — so every plain member, which is most of every tenant, opened their own
    preferences and was told the settings were unavailable. Found by the
    independent review this framework had never had.

    The permission was reasoned about for `/settings/effective` and for the
    writes, and applied here by symmetry with a route it is not symmetric with.
    **This publishes build metadata**: the same list of names, types, bounds and
    i18n keys for every customer of this product, holding nobody's values.
    `settings.read` guards the organisation's *configuration*, which is
    `GET /tenant/settings/values`, and that route still requires it.

    `_tenant` is required and unused: the dependency is what makes this
    reachable only by somebody with a resolved tenant. Without it this would be
    the one authenticated route any verified token could read, which is a wider
    door than a list of setting names is worth — and it is the whole of the
    protection this route needs.

    Deprecated definitions are left out. Rows holding one still resolve — code
    that reads it keeps working — and no surface offers it again.

    System settings are left out too, whatever the caller is: they are the
    platform's own and a customer has no page for them.
    """
    return [_definition_view(setting) for setting in catalogue.offered() if not setting.system]


@router.get("/settings/effective", response_model=EffectiveSettings)
async def effective(tenant: TenantDep, session: DbSession) -> EffectiveSettings:
    """Every setting, resolved for this caller.

    **No permission.** The shell reads this on every signed-in request to decide
    how to render, and a member without `settings.read` must still get a page
    that looks right. It answers for one tenant and one subject and takes no
    parameter naming either, so there is nothing here to escalate with.

    Three queries, not one per setting: the caller's own rows, the tenant's, and
    the platform's. The catalogue supplies the keys and the defaults, so a key
    with no row anywhere still appears with `source` of `default`.
    """
    resolution = resolve_all(
        catalogue,
        global_values=await global_values(session),
        organization_values=await tenant_values(session, tenant.id),
        member_values=await member_values(session, tenant.id, require_subject(tenant)),
    )
    return EffectiveSettings(
        settings={key: _resolved_view(answer) for key, answer in resolution.settings.items()},
        skipped=[skipped.key for skipped in resolution.skipped],
    )


@router.get("/tenant/settings/values", response_model=dict[str, Any])
async def read_tenant_values(
    claims: AuthDep, tenant: TenantDep, session: DbSession
) -> dict[str, Any]:
    """The organisation's own rows, as stored.

    Distinct from `/settings/effective`, which is what a *person* sees. An
    administrator editing the organisation needs to know what the organisation
    holds, not what their own overrides do to it — otherwise they change a
    value, see no difference, and change it again.
    """
    _require(claims, READ_PERMISSION, "reading the organisation's settings")
    return await tenant_values(session, tenant.id)


@router.patch("/tenant/settings/values", response_model=dict[str, Any])
async def change_tenant_values(
    body: ValueMap, claims: AuthDep, tenant: TenantDep, session: DbSession
) -> dict[str, Any]:
    """Change settings for everybody in the organisation.

    `settings.manage`, because this decides for other people. A refusal is
    recorded as a security event before it is raised — a denied configuration
    change is a fact about the system, and the one an auditor asks about.
    """
    if MANAGE_PERMISSION not in permissions_for(claims.roles):
        await record(
            session,
            tenant_id=tenant.id,
            actor_id=claims.sub,
            action="settings.refused",
            target_type="setting",
            target_id=",".join(sorted(body.values)[:5]) or "-",
            outcome="denied",
            details={"scope": "tenant", "reason": "permission"},
        )
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.PERMISSION_MISSING,
            f"changing the organisation's settings needs the {MANAGE_PERMISSION} permission",
        )

    accepted = _coerce_all(body.values, Scope.GLOBAL_ORG)
    changes = await write_tenant_values(session, tenant.id, accepted)
    await _audit(session, tenant, claims, "settings.tenant_changed", changes)
    await session.commit()
    return await tenant_values(session, tenant.id)


@router.post("/tenant/settings/values/{key}/reset", response_model=dict[str, Any])
async def reset_tenant_setting(
    key: str, claims: AuthDep, tenant: TenantDep, session: DbSession
) -> dict[str, Any]:
    """Put the platform's current value back into one of the organisation's rows.

    **A copy, not a delete.** Removing the row would make every later read fall
    through to whatever the platform holds at that moment, and keep doing so as
    it changed — which is the dynamic inheritance the provisioning snapshot
    exists to prevent, reintroduced by the control that looks safest.

    So the answer says what the value now *is*, and a caller comparing it with
    the platform's own will find them equal today and possibly not tomorrow.
    That is correct.
    """
    _require(claims, MANAGE_PERMISSION, "resetting the organisation's settings")
    definition = _definition(key)
    if not definition.scope.admits_organization:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.SETTING_SCOPE_REFUSED,
            f"{key} is set by the platform and the organisation holds no value to reset",
        )

    change = await reset_tenant_value(session, tenant.id, definition)
    await _audit(session, tenant, claims, "settings.tenant_reset", [change])
    await session.commit()
    return await tenant_values(session, tenant.id)


@router.get("/me/settings", response_model=dict[str, Any])
async def read_my_settings(tenant: TenantDep, session: DbSession) -> dict[str, Any]:
    """This caller's own rows.

    No permission and no subject parameter. The policy behind it is keyed to
    the verified subject, so this answers for whoever asked and for nobody else.
    """
    return await member_values(session, tenant.id, require_subject(tenant))


@router.patch("/me/settings", response_model=dict[str, Any])
async def change_my_settings(
    body: ValueMap, claims: AuthDep, tenant: TenantDep, session: DbSession
) -> dict[str, Any]:
    """Override settings for yourself.

    Any member may. The choice is about themselves and changes nothing for
    anybody else, which is the argument `PUT /me/locale` already rests on.

    A key whose scope admits no personal override is 403 and is recorded: a
    person cannot reach one through the interface, so a request that tries is
    either a stale page or somebody exploring, and both are worth a row.
    """
    accepted = _coerce_all(body.values, Scope.GLOBAL_ORG_USER)
    changes = await write_member_values(session, tenant.id, require_subject(tenant), accepted)
    await _audit(session, tenant, claims, "settings.member_changed", changes)
    await session.commit()
    return await member_values(session, tenant.id, require_subject(tenant))


@router.delete("/me/settings/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_my_setting(
    key: str, claims: AuthDep, tenant: TenantDep, session: DbSession
) -> Response:
    """Stop deciding one setting for yourself; the organisation's applies again.

    **A delete, where the organisation's reset is a copy.** The asymmetry is the
    difference between the two statements. A person saying "I no longer want a
    preference" means exactly that their organisation's value should answer, now
    and as it changes; an organisation saying it means "give me what the
    platform has today", which is a value.

    204 whether or not a row was there. Clearing a preference nobody set is not
    an error — the caller wanted the organisation's value and has it — and it is
    not a change either, so nothing is recorded.
    """
    definition = _definition(key)
    if not definition.scope.admits_user:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.SETTING_SCOPE_REFUSED,
            f"{key} cannot be overridden by one person, so there is nothing to clear",
        )

    change = await clear_member_value(session, tenant.id, require_subject(tenant), key)
    if change is not None:
        await _audit(session, tenant, claims, "settings.member_reset", [change])
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
