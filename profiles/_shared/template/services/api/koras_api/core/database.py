from collections.abc import AsyncGenerator

from koras_database import assert_rls_enforced, set_rls_context
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .settings import settings
from .tenant import TenantDep

engine = create_async_engine(settings.database_url, pool_size=settings.database_pool_size)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db(tenant: TenantDep) -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        await set_rls_context(session, tenant_id=tenant.id)
        yield session


async def verify_rls_enforcement() -> None:
    """Startup check: this connection must be one RLS can restrain.

    `force row level security` binds the table owner to its policies and does
    nothing to a superuser or a role holding BYPASSRLS. A managed Postgres
    usually offers a superuser as the default connection role, so a DATABASE_URL
    taken from a dashboard produces a service with correct policies, `force` set
    everywhere, a passing policy suite, and no row-level security at all.

    Raising here stops the service rather than letting it serve, because the
    failure it prevents is a cross-tenant read and the alternative is finding
    out from whoever saw the other tenant's data.
    """
    async with SessionLocal() as session:
        await assert_rls_enforced(session)
