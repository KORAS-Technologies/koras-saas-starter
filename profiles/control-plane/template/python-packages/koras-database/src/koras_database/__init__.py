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
