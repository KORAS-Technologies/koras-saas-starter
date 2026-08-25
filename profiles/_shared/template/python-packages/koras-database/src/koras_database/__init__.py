from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


async def set_rls_context(session: AsyncSession, tenant_id: str) -> None:
    """Set the tenant context that row-level security policies filter on.

    Uses ``set_config`` rather than ``SET LOCAL`` because ``SET`` does not accept
    bind parameters. Without them the value has to be interpolated into the
    statement, which turns a caller-supplied tenant id into an injection vector
    in the one function the whole tenant boundary depends on. The third argument
    scopes the setting to the current transaction, matching what ``LOCAL`` would
    have given, so nothing leaks to the next request on a pooled connection.
    """
    await session.execute(
        text("select set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )


class RlsNotEnforced(RuntimeError):
    """The connection bypasses row-level security, so policies do nothing."""


async def assert_rls_enforced(session: AsyncSession) -> None:
    """Refuse to serve on a connection that row-level security cannot restrain.

    `alter table ... force row level security` subjects the table's *owner* to
    its policies. It does not subject a **superuser**, and it does not subject a
    role holding BYPASSRLS -- those bypass RLS unconditionally, forced or not.

    That distinction is invisible until it is measured, and measuring it was the
    only way it was found. Against a real database:

        connecting role        force   rows visible
        superuser              ON      2   <- bypassed
        non-superuser owner    ON      1   <- isolated
        non-superuser owner    OFF     2   <- bypassed

    A managed Postgres commonly hands out a superuser as the default connection
    role, and a DATABASE_URL copied from a dashboard is usually that role. Such
    a deployment has correct policies, `force` set on every table, a passing
    policy test suite, and no row-level security whatsoever.

    So the check is made at startup, once, where it is loud. The alternative is
    discovering it from a customer who has seen another tenant's data.
    """
    result = await session.execute(
        text(
            "select current_user, "
            "coalesce(rolsuper, false), coalesce(rolbypassrls, false) "
            "from pg_roles where rolname = current_user"
        )
    )
    row = result.first()
    if row is None:  # pragma: no cover - current_user always has a pg_roles row
        return

    user, is_superuser, bypasses_rls = row
    if is_superuser or bypasses_rls:
        reason = "a superuser" if is_superuser else "granted BYPASSRLS"
        raise RlsNotEnforced(
            f"The database connection uses {user!r}, which is {reason}. "
            "Row-level security is bypassed on this connection, so every tenant "
            "policy is inert and queries can return other tenants' rows. "
            "Connect as a role that is neither, and grant it only the table "
            "privileges the service needs."
        )
