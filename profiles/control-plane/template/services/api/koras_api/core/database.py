"""The database engine and the startup check, for the Control Plane.

Per profile rather than shared: the two profiles differ in exactly the part
that matters here, and a `_shared` template may not also exist in a profile.
The logic both need lives in `koras_database`; this file is the wiring.
"""

from collections.abc import AsyncGenerator

from koras_database import verify_connection_enforces_rls
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .settings import settings

engine = create_async_engine(settings.database_url, pool_size=settings.database_pool_size)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """A session with no tenant context, because there is no tenant.

    The Control Plane scopes by platform role in the API, not by row in the
    database. There is no `.tenant` module here and no `current_tenant_id()` to
    set -- a shared version of this file importing one is why the API briefly
    stopped importing at all.
    """
    async with SessionLocal() as session:
        yield session



async def verify_rls_enforcement() -> None:
    """Called from the lifespan, before anything is served."""
    await verify_connection_enforces_rls(
        SessionLocal, required=settings.require_rls_enforcement
    )
