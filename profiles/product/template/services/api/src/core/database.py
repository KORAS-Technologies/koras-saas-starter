from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from koras_database import set_rls_context
from .settings import settings
from .tenant import TenantDep

engine = create_async_engine(settings.database_url, pool_size=settings.database_pool_size)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db(tenant: TenantDep) -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        await set_rls_context(session, tenant_id=tenant.id)
        yield session
