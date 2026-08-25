"""The database engine and the startup check, for a product.

Per profile rather than shared: the two profiles differ in exactly the part
that matters here, and a `_shared` template may not also exist in a profile.
The logic both need lives in `koras_database`; this file is the wiring.
"""

from collections.abc import AsyncGenerator

from koras_database import set_rls_context, verify_connection_enforces_rls
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



async def verify_rls_enforcement() -> None:
    """Called from the lifespan, before anything is served."""
    await verify_connection_enforces_rls(
        SessionLocal, required=settings.require_rls_enforcement
    )
