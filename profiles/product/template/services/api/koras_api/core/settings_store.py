"""Reading and writing the three tables a setting's value can live in.

`koras_settings` knows what a setting is and which rung of the ladder wins;
this knows where the rungs are. Keeping the two apart is what lets the same
catalogue be resolved against a tenant's tables here and against the platform's
own in the Control Plane.

Separate from the router for the reason `tenant_store` is: a router is a
contract and persistence is not. Written as SQL text rather than ORM models,
because the product template defines none and one feature should not make the
next one inherit a mapper layer by default.

**Which session each function wants.** The three readers run on whatever
session the caller has -- a tenant request's, which row-level security scopes
to that tenant and that person, or the provisioning session, which sees
everything. `seed_tenant` runs on the provisioning session only; there is no
tenant context at provisioning time, and the policies in `00029` admit the
insert on `app.provisioning` alone.
"""

from __future__ import annotations

import json
from typing import Any

from koras_settings import SettingDefinition, SettingsRegistry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: Written into `tenants.settings_copied_by` by the provisioning path.
#:
#: A column rather than a constant in a query, so that a later repair run by a
#: person says so rather than claiming to have been provisioning.
PROVISIONING_ACTOR = "provisioning"


def as_json(value: Any) -> str:  # noqa: ANN401
    """A setting value as the string a `jsonb` parameter takes.

    `json.dumps` and not `str`: a Python `True` rendered by `str` is `True`,
    which is not JSON, and would be stored as the *text* `True` or rejected
    depending on how the driver felt about it. Tuples -- which is what a
    definition's `STRING_LIST` default is -- become arrays, which is what they
    have to be on the way back out.
    """
    return json.dumps(value)


async def global_values(session: AsyncSession) -> dict[str, Any]:
    """Every platform default this product holds.

    Readable on any session: `00029` gives the table a `using (true)` select
    policy, because a platform default belongs to nobody and a tenant that
    could not read one would silently resolve to the code default instead.
    """
    result = await session.execute(text("select key, value from public.global_settings"))
    return {key: value for key, value in result.all()}


async def global_version(session: AsyncSession) -> int:
    """The version a tenant seeded right now would be seeded from.

    Zero when no platform operator has changed anything, which is the normal
    state of a new estate and a real answer rather than a missing one.
    """
    result = await session.execute(
        text("select coalesce(max(version), 0) from public.global_settings")
    )
    return int(result.scalar_one())


async def tenant_values(session: AsyncSession, tenant_id: str) -> dict[str, Any]:
    """One tenant's own values.

    The `where` is belt as well as braces -- the session is already scoped by
    `00029`'s policy -- and it stays for the reason `routers/tenant.py:139-155`
    keeps its own: a policy is a backstop against a query that forgets, not a
    substitute for one that remembers, and a reader of this function should be
    able to see what it selects.
    """
    result = await session.execute(
        text(
            "select key, value from public.tenant_setting_values "
            "where tenant_id = cast(:tenant_id as uuid)"
        ),
        {"tenant_id": tenant_id},
    )
    return {key: value for key, value in result.all()}


async def member_values(session: AsyncSession, tenant_id: str, user_id: str) -> dict[str, Any]:
    """One person's own values, in one tenant.

    Both keys, always. On the person alone, somebody who belongs to two tenants
    of this product would read their value from the wrong one.
    """
    result = await session.execute(
        text(
            "select key, value from public.member_setting_values "
            "where tenant_id = cast(:tenant_id as uuid) and user_id = :user_id"
        ),
        {"tenant_id": tenant_id, "user_id": user_id},
    )
    return {key: value for key, value in result.all()}


async def seed_tenant(
    session: AsyncSession,
    tenant_id: str,
    catalogue: SettingsRegistry,
    *,
    copied_by: str = PROVISIONING_ACTOR,
) -> int:
    """Copy the platform's applicable defaults into a new tenant.

    **This is the feature.** After this runs, a platform operator changing a
    default does not change this tenant: their rows already say what they were
    given, and the resolver reads a row before it reads a platform value.

    Three properties, each of which is load-bearing.

    *Every applicable definition, not every platform row.* A key the platform
    has never set still gets a row here, holding the definition's own default.
    Copying only the rows that exist would leave a gap that the platform could
    later fill, and filling it would change a tenant that was provisioned
    before -- which is exactly what a snapshot is for preventing.

    *`on conflict do nothing`.* A retried provisioning must not overwrite a
    value somebody has since edited. `apply_ai_routing_template` in the Control
    Plane relies on the same property for the same reason, and without it a
    failed job re-run a week later would silently reset a customer's settings.

    *Platform-only settings are not copied.* A `GLOBAL_ONLY` key has no tenant
    value by definition; a row holding one would be a value nobody may change
    and every reader would have to learn to ignore.

    Returns the global version the copy was taken from, which the caller has
    already had written onto the tenant row.
    """
    version = await global_version(session)
    platform = await global_values(session)

    rows = [
        {
            "tenant_id": tenant_id,
            "key": definition.key,
            "value": as_json(_starting_value(definition, platform)),
        }
        for definition in catalogue
        if definition.scope.admits_organization
    ]

    if rows:
        await session.execute(
            text(
                "insert into public.tenant_setting_values (tenant_id, key, value) "
                "values (cast(:tenant_id as uuid), :key, cast(:value as jsonb)) "
                "on conflict (tenant_id, key) do nothing"
            ),
            rows,
        )

    # `where settings_copied_at is null` so a retry does not rewrite the
    # provenance of the first copy. The rows above are idempotent; this is the
    # record of when they were first written, and a retry a week later
    # overwriting it would make the version meaningless.
    await session.execute(
        text(
            "update public.tenants set "
            "  settings_global_version = :version, "
            "  settings_copied_at = now(), "
            "  settings_copied_by = :copied_by "
            "where id = cast(:tenant_id as uuid) and settings_copied_at is null"
        ),
        {"version": version, "copied_by": copied_by, "tenant_id": tenant_id},
    )
    return version


def _starting_value(definition: SettingDefinition, platform: dict[str, Any]) -> Any:  # noqa: ANN401
    """What this tenant starts with for one setting.

    The platform's value if it holds one, and the definition's own default
    otherwise. Not validated on the way in: a platform value was validated when
    it was written, and a definition's default was validated at import. A value
    that has since stopped satisfying a tightened bound is the resolver's
    problem, and it falls through rather than refusing to render.
    """
    if definition.key in platform and platform[definition.key] is not None:
        return platform[definition.key]
    default = definition.default
    # A tuple is what a `STRING_LIST` default is, and JSON has no tuples.
    return list(default) if isinstance(default, tuple) else default
