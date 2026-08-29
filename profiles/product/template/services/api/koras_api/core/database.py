"""The database engine and the startup check, for a product.

Per profile rather than shared: the two profiles differ in exactly the part
that matters here, and a `_shared` template may not also exist in a profile.
The logic both need lives in `koras_database`; this file is the wiring.
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from koras_database import (
    set_provisioning_context,
    set_rls_context,
    verify_connection_enforces_rls,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .settings import settings
from .tenant import TenantDep

engine = create_async_engine(settings.database_url, pool_size=settings.database_pool_size)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db(tenant: TenantDep) -> AsyncGenerator[AsyncSession, None]:
    """A session with this request's tenant context set.

    The context is transaction-local, so it cannot outlive the request on a
    pooled connection and be inherited by whoever gets that connection next.
    """
    async with SessionLocal() as session:
        await set_rls_context(session, tenant_id=tenant.id)
        yield session


async def get_platform_session() -> AsyncGenerator[AsyncSession, None]:
    """A session for the private platform API, which has no tenant to scope to.

    Deliberately not `get_db` with a flag. `get_db` depends on `TenantDep`,
    which depends on a customer token and a resolved tenant -- neither of which
    exists on a call whose purpose is to create the tenant. Those dependencies
    are the point: a route that wanted both behaviours would have to make the
    tenant optional, and an optional tenant context is one that is missing on
    the path nobody tested.

    What this grants instead is stated in `set_provisioning_context`, and it is
    broad: within this transaction the connection reads and writes every tenant
    row. That is why it is reachable from exactly one router, which admits a
    machine identity alone.
    """
    async with SessionLocal() as session:
        await set_provisioning_context(session)
        yield session


# An alias rather than `Depends(...)` in each signature, because the contract
# test reads the router's handler signatures and a parenthesis inside one puts
# the whole route beyond its regex -- silently, as a route it stops checking
# rather than as a failure.
PlatformSession = Annotated[AsyncSession, Depends(get_platform_session)]


async def verify_rls_enforcement() -> None:
    """Called from the lifespan, before anything is served."""
    await verify_connection_enforces_rls(SessionLocal, required=settings.require_rls_enforcement)
