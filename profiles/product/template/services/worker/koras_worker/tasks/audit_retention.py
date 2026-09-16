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
    #: about last quarter, short enough to stop growing forever. This is the
    #: floor for the `audit` and `administrative` classes.
    audit_retention_days: int = 365

    #: Activity -- a file opened, a report viewed. Interesting for a month,
    #: rarely for a year, and the bulk of the rows.
    audit_activity_retention_days: int = 90

    #: Security -- refusals, authorization decisions, holds. Kept longest,
    #: because the question asked about one is usually asked late.
    audit_security_retention_days: int = 1095


audit = AuditSettings()

logger = logging.getLogger(__name__)

_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")
_PURGE_AUDIT = text(
    "delete from public.audit_events "
    "where classification = :classification and created_at < :before returning id"
)


def retention_by_class(settings: AuditSettings) -> dict[str, int]:
    """How long each class is kept, in days.

    One number governed the whole table until 2026-09-16, which was too long
    for an opened file and too short for a refusal. `administrative` shares
    the default: a configuration change is as durable a fact as an access.
    """
    return {
        "activity": settings.audit_activity_retention_days,
        "audit": settings.audit_retention_days,
        "administrative": settings.audit_retention_days,
        "security": settings.audit_security_retention_days,
    }


async def purge_audit_events(session: AsyncSession, *, retention: dict[str, int]) -> dict[str, int]:
    """Remove rows of each class older than that class allows.

    One transaction and one provisioning setting for all four deletes, so a
    sweep interrupted half way leaves the table consistent with itself rather
    than with two of four classes swept.
    """
    for name, days in sorted(retention.items()):
        if days < 1:
            raise ValueError(
                f"audit retention for {name!r} must be at least 1 day; "
                "retention of nothing is a wipe"
            )
    now = datetime.now(UTC)
    await session.execute(_PROVISIONING)
    removed: dict[str, int] = {}
    for name, days in sorted(retention.items()):
        rows = await session.execute(
            _PURGE_AUDIT, {"classification": name, "before": now - timedelta(days=days)}
        )
        removed[name] = len(rows.all())
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
    retention = retention_by_class(audit)
    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            removed = await purge_audit_events(session, retention=retention)
    finally:
        await engine.dispose()
    total = sum(removed.values())
    logger.info(
        "audit retention removed %d row(s): %s",
        total,
        ", ".join(f"{name} {count}" for name, count in sorted(removed.items())),
    )
    return {"status": "ok", "removed": total, "by_class": removed, "retention": retention}
