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

    Only where the schema's policies do the scoping. `settings.require_rls_
    enforcement` says whether that is this profile's arrangement, because the
    two profiles mean different things by "RLS is enabled".

    A product scopes rows by tenant, in policies, and therefore must not connect
    as a role that bypasses them -- `force` binds the table owner and does
    nothing to a superuser or a BYPASSRLS role, so a DATABASE_URL taken from a
    dashboard can produce correct policies, force everywhere, and no isolation.

    The Control Plane has no tenant model and no policies. Its tables carry RLS
    as a deny-by-default backstop and the service role is *meant* to bypass it.
    Asserting the product's rule there refuses to start a service that is
    working exactly as designed.
    """
    if not settings.require_rls_enforcement:
        return

    async with SessionLocal() as session:
        await assert_rls_enforced(session)
