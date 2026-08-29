"""Reading and writing tenants for the private platform API.

Separate from the router so the router stays what the contract test reads it
as: the four routes, their status codes, and the identity they require. What
persistence looks like is allowed to change; the contract is not.

Everything here runs on the provisioning session from `core.database`, which
carries no tenant context. See `koras_database.set_provisioning_context` for
what that grants and why it is confined to this path.

Written as SQL text rather than ORM models on purpose. The product template
defines no models, and introducing a mapper layer for a handful of statements
would make the first real feature inherit it by default rather than by choice.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Provisioning creates the first administrator, not a member. The value matches
# `packages/permissions`' ORGANIZATION_ROLES on the TypeScript side -- the two
# runtimes cannot import each other, so this is one of the places that drift
# would be silent.
OWNER_ROLE = "organization_owner"

# Where a tenant starts. The Control Plane's run has further steps after this
# one, and a tenant nobody has finished setting up must not read as a working
# one.
INITIAL_STATUS = "provisioning"


@dataclass(frozen=True)
class TenantRow:
    tenant_id: str
    tenant_key: str
    status: str


class SlugTaken(Exception):
    """Another organization already holds this slug in this product.

    Distinct from a repeated `tenant_key`, which is a retry and must succeed.
    This is two different organizations asking for one name, which nothing here
    can resolve -- and resolving it by mangling the slug would hand somebody a
    tenant at an address they did not ask for.
    """


async def find_by_key(session: AsyncSession, tenant_key: str) -> TenantRow | None:
    result = await session.execute(
        text(
            "select id::text, tenant_key, status from public.tenants where tenant_key = :tenant_key"
        ),
        {"tenant_key": tenant_key},
    )
    row = result.first()
    return TenantRow(*row) if row is not None else None


async def find_by_id(session: AsyncSession, tenant_id: str) -> TenantRow | None:
    """Look up by the id this API previously returned.

    The cast is on the column rather than the parameter because `tenant_id`
    arrives from a URL and need not be a uuid at all. Casting the parameter
    would make a malformed one a 500 out of the driver; comparing as text makes
    it the 404 it is.
    """
    result = await session.execute(
        text("select id::text, tenant_key, status from public.tenants where id::text = :tenant_id"),
        {"tenant_id": tenant_id},
    )
    row = result.first()
    return TenantRow(*row) if row is not None else None


async def create(
    session: AsyncSession,
    *,
    tenant_key: str,
    organization_id: str,
    name: str,
    slug: str,
    plan: str,
    owner_email: str,
    owner_zitadel_user_id: str | None,
) -> tuple[TenantRow, bool]:
    """Create the tenant, or adopt the one this key already names.

    Returns the row and whether this call created it -- which is the whole 201
    versus 200 distinction the Control Plane uses to tell a first attempt from a
    retry.

    `on conflict do nothing` rather than select-then-insert. The two calls this
    has to survive are concurrent retries of the same job, and between a select
    that finds nothing and an insert there is a window in which the other
    attempt commits. Letting the unique index decide closes it: exactly one
    insert returns a row, and the other finds the committed one.
    """
    try:
        inserted = await session.execute(
            text(
                "insert into public.tenants "
                "  (tenant_key, organization_id, name, slug, plan, status, owner_email) "
                "values "
                "  (:tenant_key, cast(:organization_id as uuid), :name, :slug, "
                "   :plan, :status, :owner_email) "
                "on conflict (tenant_key) do nothing "
                "returning id::text, tenant_key, status"
            ),
            {
                "tenant_key": tenant_key,
                "organization_id": organization_id,
                "name": name,
                "slug": slug,
                "plan": plan,
                "status": INITIAL_STATUS,
                "owner_email": owner_email,
            },
        )
    except IntegrityError as exc:
        # `on conflict` absorbs a repeated tenant_key and nothing else, so what
        # reaches here is a different constraint -- in practice the slug, which
        # is unique per product and derived from the organization's own.
        await session.rollback()
        raise SlugTaken(slug) from exc

    row = inserted.first()

    if row is None:
        # The key was taken, so this is a retry. The existing row is the answer;
        # nothing about it is overwritten, because the Control Plane's later
        # steps own what happens to a tenant after it exists.
        existing = await find_by_key(session, tenant_key)
        if existing is None:  # pragma: no cover - the conflict names a row by definition
            raise RuntimeError("the tenant_key conflicted with a row that cannot be read")
        await session.commit()
        return existing, False

    created = TenantRow(*row)

    if owner_zitadel_user_id:
        # Only when the identity exists. The Control Plane creates the ZITADEL
        # user in its own step, and a create arriving before it carries an email
        # and no subject -- which `tenant_members.user_id` cannot hold, since it
        # is the subject that a later sign-in will present.
        await session.execute(
            text(
                "insert into public.tenant_members (tenant_id, user_id, role) "
                "values (cast(:tenant_id as uuid), :user_id, :role) "
                "on conflict (tenant_id, user_id) do nothing"
            ),
            {
                "tenant_id": created.tenant_id,
                "user_id": owner_zitadel_user_id,
                "role": OWNER_ROLE,
            },
        )

    await session.commit()
    return created, True


async def set_status(session: AsyncSession, tenant_id: str, new_status: str) -> TenantRow | None:
    result = await session.execute(
        text(
            "update public.tenants set status = :status where id::text = :tenant_id "
            "returning id::text, tenant_key, status"
        ),
        {"status": new_status, "tenant_id": tenant_id},
    )
    row = result.first()
    if row is None:
        return None
    await session.commit()
    return TenantRow(*row)
