"""The audit table's retention sweep.

The AI sweep's shape exactly, and foundation rather than reporting's, because
the table it sweeps is foundation. `AUDIT_RETENTION_DAYS` is its own setting,
read here rather than by every module that records, so one number governs one
table.

On the provisioning context, which is the only context that reaches every
tenant, and transaction-local, so a pooled connection cannot inherit it. The
pure function takes the session, so the age arithmetic and the refusal are
testable without a database.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..settings import settings


class AuditSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    #: Days an audit row is kept. A year: long enough to answer a question
    #: about last quarter, short enough to stop growing forever.
    audit_retention_days: int = 365


audit = AuditSettings()

logger = logging.getLogger(__name__)

_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")
_PURGE_AUDIT = text("delete from public.audit_events where created_at < :before returning id")


async def purge_audit_events(session: AsyncSession, *, retention_days: int) -> int:
    """Remove audit rows older than `retention_days`; return how many."""
    if retention_days < 1:
        raise ValueError("AUDIT_RETENTION_DAYS must be at least 1; retention of nothing is a wipe")
    before = datetime.now(UTC) - timedelta(days=retention_days)
    await session.execute(_PROVISIONING)
    removed = len((await session.execute(_PURGE_AUDIT, {"before": before})).all())
    await session.commit()
    return removed


def _engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )


async def purge_audit_history(ctx: dict[str, Any]) -> dict[str, Any]:
    """The nightly sweep. Skips, loudly, when the worker has no database."""
    if not settings.database_url:
        logger.warning("audit retention skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}
    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            removed = await purge_audit_events(session, retention_days=audit.audit_retention_days)
    finally:
        await engine.dispose()
    logger.info(
        "audit retention removed %d row(s) older than %d days",
        removed,
        audit.audit_retention_days,
    )
    return {"status": "ok", "removed": removed, "retention_days": audit.audit_retention_days}
