"""Reporting's two sweeps: the audit table's retention, and the place a
scheduled delivery will run from.

The retention sweep is the AI one's shape exactly: on the provisioning
context, which migration 00013 admits for this delete and nothing else,
with the pure statement taking the session so a test needs no database.
`AUDIT_RETENTION_DAYS` is its own setting, read here rather than by every
worker, and a year unless set.

`deliver_scheduled_reports` is scaffolding and says so. There is no table of
schedules yet; when a product needs one, this is the task that reads it,
renders through the same resolver the page uses and mails the CSV through
`koras_email`. Until then it runs, logs that nothing is scheduled, and
returns -- so the worker's cron list already names the seam.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..settings import settings


class ReportingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    #: Days an audit row is kept. A year: long enough to answer a question
    #: about last quarter, short enough to stop growing forever.
    audit_retention_days: int = 365


reporting = ReportingSettings()

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


async def purge_audit_history(ctx: dict[str, Any]) -> dict[str, Any]:
    """The nightly sweep. Skips, loudly, when the worker has no database."""
    if not settings.database_url:
        logger.warning("audit retention skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}
    engine = create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            removed = await purge_audit_events(
                session, retention_days=reporting.audit_retention_days
            )
    finally:
        await engine.dispose()
    logger.info(
        "audit retention removed %d row(s) older than %d days",
        removed,
        reporting.audit_retention_days,
    )
    return {"status": "ok", "removed": removed, "retention_days": reporting.audit_retention_days}


async def deliver_scheduled_reports(ctx: dict[str, Any]) -> dict[str, Any]:
    """Scaffolding: nothing is scheduled yet, and this says so rather than
    pretending. See `docs/REPORTING_ARCHITECTURE.md`, scheduled reporting."""
    logger.info("scheduled reports: no schedules exist in this product; nothing delivered")
    return {"status": "ok", "delivered": 0}
