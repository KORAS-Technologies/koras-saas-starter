"""A message that is owed, and what happened when it was tried.

CAT-01 Phase 3. Phase 2 gave notification one place to leave from and handed
the prepared mail back to the caller, which handed it to a FastAPI background
task. That is exactly the arrangement PLAT-F1 exists to replace: a background
task runs in the API process and is lost when it restarts, so a deploy during a
send loses the send and nothing anywhere records that it was ever owed.

**The row is written in the transaction that decided to send it.** If that
transaction rolls back there was no notification; if it commits, the message is
owed and the worker will keep trying. The same rule the feed row already
follows, applied to the half that leaves the building.

## Three things this deliberately does not do

**It does not re-render.** The subject and both bodies are stored, not the
arguments to build them from. A retry an hour later against state that has
changed would otherwise send a different message from the one that was decided,
and the person who decided it would have no way to know.

**It does not retry forever.** `MAX_ATTEMPTS` failures and the row is
`abandoned` with the reason on it — a terminal state that is *visible*, which
is the whole difference from the log line this replaces. PLAT-GAP-003.

**It has no dead-letter queue**, for the reason ADR 0008 gives: a destination
nothing reads is not evidence. `abandoned` rows are in the same table as
everything else, and the sweep reports how many it left there.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: How many times a message is tried before it is given up on.
#:
#: Five, spread by the backoff below over about half an hour. Long enough to
#: ride out the mail outage this phase exists for — the exit criterion is "a
#: mail server refusing connections for ten minutes loses no notification" —
#: and short enough that a permanently bad address is not retried for a week.
MAX_ATTEMPTS = 5

#: Minutes to wait before attempt *n*, indexed from the first failure.
#:
#: Written out rather than computed, because a formula invites somebody to tune
#: the base and change the ceiling without noticing. The last entry is what a
#: message that has failed four times waits before its final try.
BACKOFF_MINUTES: tuple[int, ...] = (1, 5, 15, 30)


@dataclass(frozen=True)
class Owed:
    """One message the worker has claimed and must now try to send."""

    id: str
    tenant_id: str
    kind: str
    recipient: str
    locale: str
    subject: str
    body_text: str
    body_html: str
    attempts: int


#: **No `returning`, and the id is generated here instead.**
#:
#: `insert ... returning` asks PostgreSQL to hand the new row back, and reading
#: a row under row-level security needs a policy that admits it. This table
#: deliberately has **no tenant select policy at all** -- it holds the rendered
#: body of every notification, including ones addressed to a colleague, so a
#: member who could read it could read what the product wrote to somebody else.
#:
#: Those two facts are incompatible, and for two days nothing noticed. The
#: insert was refused with "new row violates row-level security policy" on
#: every customer request, in every generated product, so the outbox could
#: never record a single message from the only producer that writes it.
#:
#: The suites were green because `300_notification_outbox_isolation.sql`
#: asserts the *absence* of the select policy -- the very thing that breaks
#: this statement -- and everything that exercised `enqueue` did so under a
#: provisioning context, whose policy is `for all` and therefore admits the
#: read. Found on 2026-09-22 by sending one notification through a running
#: product.
_INSERT = text(
    "insert into public.notification_outbox "
    "(id, tenant_id, kind, recipient, locale, subject, body_text, body_html) "
    "values (cast(:id as uuid), cast(:tenant_id as uuid), :kind, :recipient, "
    ":locale, :subject, :body_text, :body_html)"
)

#: What is owed, whose turn has come, oldest first.
#:
#: `for update skip locked` so two workers cannot claim the same message. That
#: is not hypothetical here: the sweep runs on a clock, and a slow send plus a
#: short interval is two of them at once — which without this sends the same
#: mail twice to the same person.
_CLAIM = text(
    "update public.notification_outbox set status = 'sending', attempts = attempts + 1 "
    "where id in ("
    "  select id from public.notification_outbox "
    "  where status in ('pending', 'sending') and next_attempt_at <= now() "
    "  order by next_attempt_at limit :limit for update skip locked"
    ") "
    "returning id, tenant_id, kind, recipient, locale, subject, body_text, body_html, attempts"
)

_SENT = text(
    "update public.notification_outbox "
    "set status = 'sent', sent_at = now(), message_id = :message_id, "
    "    simulated = :simulated, error = null "
    "where id = cast(:id as uuid)"
)

_FAILED = text(
    "update public.notification_outbox "
    "set status = :status, error = :error, last_failed_at = now(), "
    "    next_attempt_at = now() + make_interval(mins => :wait) "
    "where id = cast(:id as uuid)"
)


async def enqueue(
    session: AsyncSession,
    *,
    tenant_id: str,
    kind: str,
    recipient: str,
    locale: str,
    subject: str,
    body_text: str,
    body_html: str,
) -> str | None:
    """Owe one message. Returns its id, or nothing if it could not be recorded.

    **Never raises**, and since 2026-09-22 that is true of the transaction as
    well as of this function. The caller is in the middle of doing the thing
    the customer actually asked for, and a notification that could not be
    recorded must not undo an upload.

    Catching the exception was never enough to deliver that. PostgreSQL aborts
    the whole transaction on an error, so a swallowed failure here left the
    caller holding a transaction in which nothing further could be written and
    everything already written was lost -- including the in-app notifications
    `dispatch` had just made, which is how one channel's failure silently took
    the other one with it. The savepoint is what makes the promise the
    paragraph above has always made.
    """
    message_id = str(uuid4())
    try:
        # A savepoint, so a refusal rolls back to here rather than poisoning
        # the caller's transaction. `begin_nested` issues `SAVEPOINT` and its
        # context manager releases it on success and rolls back to it on an
        # exception; the outer transaction is untouched either way.
        async with session.begin_nested():
            await session.execute(
                _INSERT,
                {
                    "id": message_id,
                    "tenant_id": tenant_id,
                    "kind": kind,
                    "recipient": recipient,
                    "locale": locale,
                    "subject": subject,
                    "body_text": body_text,
                    "body_html": body_html,
                },
            )
    except Exception:
        logger.exception("a notification could not be added to the outbox")
        return None
    return message_id


async def claim(session: AsyncSession, *, limit: int = 50) -> list[Owed]:
    """Take up to `limit` messages whose turn has come, and mark them in flight.

    The attempt is counted **here**, on the claim, rather than after the send.
    A worker that died mid-send would otherwise leave a message that had been
    tried and did not know it, and a message that crashes its sender every time
    would be retried forever.
    """
    result = await session.execute(_CLAIM, {"limit": max(1, min(limit, 500))})
    return [
        Owed(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            kind=row.kind,
            recipient=row.recipient,
            locale=row.locale,
            subject=row.subject,
            body_text=row.body_text,
            body_html=row.body_html,
            attempts=row.attempts,
        )
        for row in result
    ]


async def delivered(
    session: AsyncSession, message: Owed, *, message_id: str, simulated: bool
) -> None:
    """Record what the transport called it, and that it is done.

    `message_id` is the only handle connecting this row to a line in a mail
    provider's own log, which is where the answer is when a customer says a
    message never arrived. `koras_email.Sent` has carried it since it was
    written and every call site discarded it. NOTIF-GAP-005.
    """
    await session.execute(
        _SENT, {"id": message.id, "message_id": message_id[:200], "simulated": simulated}
    )


async def failed(session: AsyncSession, message: Owed, reason: str) -> bool:
    """Record a failure and decide whether to try again. True when it will.

    A message that has used its attempts becomes `abandoned` — terminal, and
    *visible*, which is the whole difference from the log line this replaces.
    """
    give_up = message.attempts >= MAX_ATTEMPTS
    # Indexed from the first failure, and held at the last entry so the fifth
    # attempt does not read past the end of the tuple.
    wait = 0 if give_up else BACKOFF_MINUTES[min(message.attempts - 1, len(BACKOFF_MINUTES) - 1)]
    await session.execute(
        _FAILED,
        {
            "id": message.id,
            "status": "abandoned" if give_up else "pending",
            # A safe sentence, cut to something the column holds. Never a
            # provider body: a bounce can quote the recipient's own mail.
            "error": reason[:400],
            "wait": wait,
        },
    )
    return not give_up


def next_attempt(attempts: int, *, now: datetime | None = None) -> datetime:
    """When a message that has just failed `attempts` times may be tried again.

    Exported for the sweep's own reporting and for a test that would otherwise
    have to read the SQL to know what the backoff is.
    """
    at = now or datetime.now(UTC)
    if attempts >= MAX_ATTEMPTS:
        return at
    return at + timedelta(minutes=BACKOFF_MINUTES[min(attempts - 1, len(BACKOFF_MINUTES) - 1)])


def summarise(results: Sequence[tuple[str, bool]]) -> dict[str, Any]:
    """What one sweep did, for the log line and the task's return value."""
    sent = sum(1 for _, ok in results if ok)
    return {"claimed": len(results), "sent": sent, "failed": len(results) - sent}


__all__ = [
    "BACKOFF_MINUTES",
    "MAX_ATTEMPTS",
    "Owed",
    "claim",
    "delivered",
    "enqueue",
    "failed",
    "next_attempt",
    "summarise",
]
