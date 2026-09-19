"""The notification feed's retention sweep.

The audit sweep's shape, and here for the same reason: a table every feature
writes to is a table that grows forever unless something forgets. A feed is
the clearest case of it — the rows are worth reading for a week and worth
keeping for about as long as somebody might reasonably not have signed in.

**Two windows, not one.** A notification that was read has done its job and can
go sooner. One that was never read is the more interesting row: it is either
something nobody looked at, or somebody who has been away. So unread rows are
kept longer, and the difference is a setting rather than a constant because the
right answer depends on how often a customer's people sign in.

**Always on, like the audit sweep and unlike the storage ones.** The storage
sweeps are off until a setting asks, because they remove a customer's own
content. A notification is not content — it is a message the product generated
about content that still exists — so forgetting one costs nothing the customer
cannot see elsewhere, and keeping every one forever costs a table nobody can
query.

Legal holds are not consulted, deliberately. A hold preserves the record of
what happened, which is `audit_events`; a notification is a copy of a sentence
about it, addressed to a person. If a hold ever needs to reach this table, the
answer is the same `under_legal_hold` predicate the other two sweeps use, and
this comment is the record that it was considered rather than missed.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_settings import SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..settings import SweepSettings, settings


class NotificationSettings(SweepSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    #: Days a *read* notification is kept. Long enough that "what was I told
    #: last month" has an answer, short enough that the table is a feed rather
    #: than an archive.
    notification_retention_days: int = 90

    #: Days an *unread* notification is kept. Six months, because the row that
    #: nobody has read is the row most likely to belong to somebody who has
    #: been away, and deleting it is deleting the only copy they would see.
    notification_unread_retention_days: int = 180


notifications = NotificationSettings()

logger = logging.getLogger(__name__)

_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")

_PURGE_READ = text(
    "delete from public.notifications "
    "where read_at is not null "
    "  and created_at < now() - make_interval(days => :days) "
    "returning id"
)

_PURGE_UNREAD = text(
    "delete from public.notifications "
    "where read_at is null "
    "  and created_at < now() - make_interval(days => :days) "
    "returning id"
)


async def purge_notification_feed(
    session: AsyncSession, *, read_days: int, unread_days: int
) -> dict[str, int]:
    """Remove what each window allows. Returns what went, by state.

    One transaction for both deletes, so a sweep interrupted half way leaves
    the table consistent with itself rather than with one of two windows swept.
    """
    for name, days in (("read", read_days), ("unread", unread_days)):
        if days < 1:
            raise ValueError(
                f"notification retention for {name} rows must be at least 1 day; "
                "retention of nothing is a wipe"
            )
    if unread_days < read_days:
        # Not arithmetic pedantry: it would delete the rows nobody has seen
        # while keeping the ones everybody has, which is precisely backwards.
        raise ValueError(
            "unread notifications must be kept at least as long as read ones"
        )

    await session.execute(_PROVISIONING)
    read = await session.execute(_PURGE_READ, {"days": read_days})
    removed_read = len(read.all())
    unread = await session.execute(_PURGE_UNREAD, {"days": unread_days})
    removed_unread = len(unread.all())
    await session.commit()
    return {"read": removed_read, "unread": removed_unread}


def _engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )


async def purge_notifications(ctx: dict[str, Any]) -> dict[str, Any]:
    """The nightly sweep. Skips, loudly, when the worker has no database."""
    del ctx
    if not settings.database_url:
        logger.warning("notification retention skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}
    read_days = notifications.notification_retention_days
    unread_days = notifications.notification_unread_retention_days
    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            removed = await purge_notification_feed(
                session, read_days=read_days, unread_days=unread_days
            )
    finally:
        await engine.dispose()
    logger.info(
        "notification retention removed %d read and %d unread row(s)",
        removed["read"],
        removed["unread"],
    )
    return {
        "status": "ok",
        "removed": sum(removed.values()),
        "by_state": removed,
        "retention": {"read": read_days, "unread": unread_days},
    }
