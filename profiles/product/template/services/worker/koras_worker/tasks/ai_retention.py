"""Delete assistant conversations older than the retention period.

Messages hold what a customer said to the assistant and what it answered.
They are useful for as long as the conversation is, and a liability after:
content nobody will read again is content that can still leak. The sweep
removes conversations, and with them their messages and actions, once
nothing has touched them for `AI_RETENTION_DAYS`. Usage rows stay: a call
that happened is a fact whatever became of the conversation.

It runs on the provisioning context, the one session that reaches every
tenant, which migration 00008 admits for exactly this delete and nothing
else on the AI tables. The 080 isolation test proves a tenant session cannot
do the same across tenants.

`purge_conversations` is the whole of the logic and takes the session, so
the test that proves the statement is the one written here does not need a
database; the task around it owns the connection.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic_settings import SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..settings import SweepSettings, settings


class RetentionSettings(SweepSettings):
    """The sweep's own two settings, read here rather than by every worker.

    A Control Plane worker has no assistant and must not read a setting
    its manifest never declares; this file is generated with the
    capability, so the settings travel with the sweep.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    #: Days an assistant conversation is kept after it was last touched before
    #: the nightly sweep removes it, messages and actions with it.
    ai_retention_days: int = 90

    #: Days an assistant audit row is kept. Longer than the conversations it
    #: describes: the record of what was decided outlives what was said.
    ai_audit_retention_days: int = 365


retention = RetentionSettings()

logger = logging.getLogger(__name__)

_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")

_PURGE = text("delete from public.ai_conversations where updated_at < :before returning id")

_PURGE_AUDIT = text("delete from public.ai_audit_events where created_at < :before returning id")


async def purge_conversations(session: AsyncSession, *, retention_days: int) -> int:
    """Remove every conversation not touched for `retention_days`; return how many."""
    if retention_days < 1:
        raise ValueError("AI_RETENTION_DAYS must be at least 1; retention of nothing is a wipe")
    before = datetime.now(UTC) - timedelta(days=retention_days)
    await session.execute(_PROVISIONING)
    removed = len((await session.execute(_PURGE, {"before": before})).all())
    await session.commit()
    return removed


async def purge_audit(session: AsyncSession, *, retention_days: int) -> int:
    """Remove audit rows older than `retention_days`; return how many."""
    if retention_days < 1:
        raise ValueError("AI_AUDIT_RETENTION_DAYS must be at least 1")
    before = datetime.now(UTC) - timedelta(days=retention_days)
    await session.execute(_PROVISIONING)
    removed = len((await session.execute(_PURGE_AUDIT, {"before": before})).all())
    await session.commit()
    return removed


async def purge_ai_history(ctx: dict[str, Any]) -> dict[str, Any]:
    """The nightly sweep. Skips, loudly, when the worker has no database."""
    if not settings.database_url:
        logger.warning("AI retention skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}
    engine = create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            removed = await purge_conversations(session, retention_days=retention.ai_retention_days)
            audit_removed = await purge_audit(
                session, retention_days=retention.ai_audit_retention_days
            )
    finally:
        await engine.dispose()
    logger.info(
        "AI retention removed %d conversation(s) older than %d days",
        removed,
        retention.ai_retention_days,
    )
    return {
        "status": "ok",
        "removed": removed,
        "audit_removed": audit_removed,
        "retention_days": retention.ai_retention_days,
    }
