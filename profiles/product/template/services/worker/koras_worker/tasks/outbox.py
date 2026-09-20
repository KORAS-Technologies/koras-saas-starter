"""Send what the API decided to send, and record what happened.

CAT-01 Phase 3. The API writes a row in the transaction that decided to send a
message; this is what actually sends it. Between those two facts sits the whole
point of the phase: **a mail server refusing connections for ten minutes loses
no notification**, because nothing was ever in flight in a process that could
be restarted — it was a row, and a row waits.

Three properties, each a line below.

**It runs as provisioning, not as a tenant.** Unlike the import dry run, which
is work one organisation asked for, this is a sweep across every organisation's
owed messages. The outbox has no tenant select policy at all — the table holds
the rendered body of every notification, including ones addressed to a
colleague — so this context is the only thing that can read it.

**It claims before it sends.** `for update skip locked` and an attempt counted
on the claim, so two overlapping runs cannot send one message twice and a
worker that dies mid-send leaves a message that knows it was tried.

**A failure is a row somebody can find.** Five attempts over about half an hour
and then `abandoned` with the reason on it. That is the difference from what
this replaces: `dispatch.send` swallowed every failure into a log line, which
is honest for a product with one producer and stops being honest the first time
somebody asks why a customer never got their notice.
"""

from __future__ import annotations

import logging
from typing import Any

from koras_email import EmailSender, sender_for
from pydantic_settings import SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from ..settings import SweepSettings, settings

logger = logging.getLogger(__name__)


class OutboxSettings(SweepSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    #: The same SMTP settings the scheduled reports use, and the same meaning
    #: when unset: a message is marked done with `simulated` true rather than
    #: left owed forever. A product with no mail provider still drains its
    #: outbox and still says, per row, that nothing left the building.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_from: str = ""
    smtp_secure: bool = True
    smtp_username: str = ""
    smtp_password: str = ""


mail = OutboxSettings()

#: How many messages one run takes. Small enough that a run is short and a
#: crash loses little, large enough that a backlog drains in minutes rather
#: than hours at the cron interval.
BATCH = 50

_AS_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")


def _engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )


def _sender() -> EmailSender:
    """The product's own sender: real with a host, recording without one.

    A product with no SMTP settings still runs this sweep and still marks each
    message done — with `simulated` true, which is why that column exists. A
    run that reported success having delivered nothing must not look identical
    to one that delivered.
    """
    return sender_for(
        host=mail.smtp_host,
        port=mail.smtp_port,
        username=mail.smtp_username or None,
        password=mail.smtp_password or None,
        sender=mail.smtp_from,
        use_tls=mail.smtp_secure,
    )


def _outbox() -> Any | None:  # noqa: ANN401 - a module, reached by name
    """The API's own outbox store, by name rather than by import.

    The worker does not depend on the API's distribution and the declared-
    dependency test rightly refuses a plain import of it. What the image
    carries is the two paths the Dockerfile copies, and `importlib` is how the
    scheduled-report task and the import dry run already reach theirs.
    """
    import importlib

    try:
        return importlib.import_module("koras_api.core.outbox")
    except ImportError:
        logger.error("the notification outbox is not on this worker's path")
        return None


async def send_owed_notifications(ctx: dict[str, Any]) -> dict[str, Any]:
    """One sweep: claim what is due, try each, record the outcome."""
    del ctx
    if not settings.database_url:
        logger.error("the notification outbox sweep skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}

    store = _outbox()
    if store is None:
        return {"status": "skipped", "reason": "no store"}

    sender = _sender()
    engine = _engine()
    sent = 0
    retrying = 0
    abandoned = 0
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(_AS_PROVISIONING)
            owed = await store.claim(session, limit=BATCH)
            # Committed before anything is sent. The claim is what stops a
            # second run taking the same message, and a claim that was still
            # in an open transaction would not stop anything.
            await session.commit()

            for message in owed:
                await session.execute(_AS_PROVISIONING)
                try:
                    outcome = await sender.send(
                        to=message.recipient,
                        subject=message.subject,
                        body=message.body_text,
                        html=message.body_html,
                        tag=message.kind,
                    )
                except Exception as error:  # noqa: BLE001 - every transport raises its own
                    logger.warning("a notification could not be sent: %s", error)
                    if await store.failed(session, message, _sentence(error)):
                        retrying += 1
                    else:
                        abandoned += 1
                else:
                    await store.delivered(
                        session,
                        message,
                        message_id=outcome.message_id,
                        simulated=outcome.simulated,
                    )
                    sent += 1
                await session.commit()
    finally:
        await engine.dispose()

    if abandoned:
        # The one outcome worth a line at this level: everything else is
        # working as intended, and this is a customer who will not be told.
        logger.error("%d notification(s) were given up on after every attempt", abandoned)
    logger.info(
        "notification outbox: %d sent, %d to retry, %d abandoned", sent, retrying, abandoned
    )
    return {"status": "ok", "sent": sent, "retrying": retrying, "abandoned": abandoned}


def _sentence(error: Exception) -> str:
    """A reason a person can act on, without the provider's own words.

    A bounce can quote the recipient's own mail back, which is theirs and not
    ours to store; and a stack trace in a column somebody reads in a console is
    a column nobody reads. The type and the first line, and no more.
    """
    first = str(error).splitlines()[0] if str(error).strip() else error.__class__.__name__
    return f"{error.__class__.__name__}: {first}"[:400]
