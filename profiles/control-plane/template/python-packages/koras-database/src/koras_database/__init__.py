from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


async def set_rls_context(session: AsyncSession, tenant_id: str) -> None:
    await session.execute(
        # Sets the RLS context variable so Postgres policies can filter by tenant
        f"SET LOCAL app.tenant_id = '{tenant_id}'"  # noqa: S608
    )
