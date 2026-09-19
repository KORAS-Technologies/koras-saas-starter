"""Telling a person something, inside the product.

Before this existed a generated product had two ways to reach a customer, both
of them email, both composed inline, neither recorded — an assistant action
awaiting approval, and a scheduled report. There was no bell, no feed and no
read state; `packages/notifications` was two lines saying to implement it as
needed.

**The one rule that shapes everything here.** A notification never fails the
thing that caused it. The row is written in the caller's own transaction
because it is tenant data and belongs with the change it describes — but
`notify` swallows its own failures and says how many it wrote, so a mail
server, a missing recipient or a malformed link cannot roll back an upload.
That asymmetry is deliberate and it is the whole reason this is a function and
not an `INSERT` at each call site.

**Kinds are code, not rows.** A kind is registered at import like an audit
action and a report key, refusing a duplicate before the process starts. The
database checks the *shape* of a kind; this checks that somebody declared it.
Both matter: the constraint stops a typo reaching a column, the registry stops
a kind nobody documented reaching a customer.

**This is not an event bus.** It has one subject and one verb. If a bus or an
outbox is built later — ADR 0008 says when that becomes worth doing — this
becomes its first subscriber and no caller changes.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: The same shape the database constraint enforces and an audit action uses.
_DOTTED = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

#: Root-relative and nothing else. A notification renders as something
#: clickable, and a clickable thing whose destination came from a caller is a
#: phishing vector wearing the product's own branding. Checked here and in the
#: column, because the column cannot be bypassed and this names the caller.
_PATH = re.compile(r"^/[^/]\S*$")

Severity = Literal["info", "success", "warning", "error"]

#: How many a feed returns at once. A notification list is read newest first
#: and nobody pages to the end of one.
PAGE = 50
MAX_PAGE = 200

#: Beyond this, a single `notify` call is a broadcast, and a broadcast wants a
#: different table — one row per recipient stops being the cheap answer. The
#: refusal is loud rather than silent so the day it happens is the day it is
#: designed for rather than the day a tenant's insert took a minute.
MAX_RECIPIENTS = 500


@dataclass(frozen=True)
class NotificationKind:
    """One kind of thing worth telling somebody about."""

    key: str
    summary: str
    default_severity: Severity = "info"

    def __post_init__(self) -> None:
        if not _DOTTED.match(self.key):
            raise ValueError(
                f"notification kind {self.key!r} must be dotted lower-case, "
                "like 'ai.approval_requested'"
            )
        if not self.summary.strip():
            raise ValueError(f"notification kind {self.key} needs a summary")


class NotificationKindRegistry:
    """Every kind this product can produce.

    The registry shape used by reports, audit actions, settings and file hooks:
    built at import, a duplicate key raises with a traceback rather than
    resolving silently, iteration is sorted, and an unknown key raises rather
    than defaulting.
    """

    def __init__(self) -> None:
        self._kinds: dict[str, NotificationKind] = {}

    def add(self, kind: NotificationKind) -> None:
        if kind.key in self._kinds:
            raise ValueError(
                f"notification kind {kind.key} is registered twice; one "
                "declaration would silently win over the other"
            )
        self._kinds[kind.key] = kind

    def extend(self, kinds: Iterable[NotificationKind]) -> None:
        for kind in kinds:
            self.add(kind)

    def require(self, key: str) -> NotificationKind:
        """The kind, or a refusal naming it.

        Raising beats defaulting for the same reason the audit registry raises
        on an unregistered action: a kind nobody declared is a message nobody
        wrote a translation for, and defaulting would put its raw key in front
        of a customer.
        """
        try:
            return self._kinds[key]
        except KeyError:
            raise KeyError(
                f"notification kind {key!r} was never registered; declare it "
                "where the feature that produces it lives"
            ) from None

    def __contains__(self, key: object) -> bool:
        return key in self._kinds

    def __iter__(self) -> Iterator[NotificationKind]:
        return iter(sorted(self._kinds.values(), key=lambda kind: kind.key))

    def __len__(self) -> int:
        return len(self._kinds)

    def clear(self) -> None:
        """Tests only."""
        self._kinds.clear()


#: The module-level registry, as `koras_audit.actions` is.
kinds = NotificationKindRegistry()


@dataclass(frozen=True)
class Notification:
    """One row, as a feed renders it."""

    id: str
    kind: str
    title: str
    body: str
    url: str
    severity: str
    created_at: datetime
    read_at: datetime | None


_INSERT = text(
    "insert into public.notifications "
    "(tenant_id, user_id, kind, title, body, url, severity) "
    "values (:tenant_id, :user_id, :kind, :title, :body, :url, :severity)"
)


async def notify(
    session: AsyncSession,
    *,
    tenant_id: str,
    recipients: Iterable[str],
    kind: str,
    title: str,
    body: str = "",
    url: str = "",
    severity: Severity | None = None,
) -> int:
    """Write one notification per recipient. Returns how many were written.

    **Never raises for a delivery reason, and always raises for a programming
    one.** An unregistered kind, a blank title or an absolute URL is a bug in
    the caller and fails loudly at the call site; a database error while
    writing is logged and swallowed, because the caller is in the middle of an
    upload and the upload is the thing the customer asked for.

    Duplicate recipients are collapsed. A caller resolving owners and permission
    holders separately will list the same person twice, and telling them twice
    is noise the caller should not have to think about.
    """
    declared = kinds.require(kind)
    if not title.strip():
        raise ValueError(f"notification {kind} needs a title")
    if url and not _PATH.match(url):
        raise ValueError(
            f"notification {kind} carries {url!r}; a notification links to a "
            "path in this product and never to an address a caller chose"
        )

    # Sorted so a test sees a stable order, and de-duplicated so one person
    # resolved by two rules is told once.
    unique = sorted({subject for subject in recipients if subject.strip()})
    if not unique:
        # Not an error. A rule that resolves to nobody is a question for the
        # caller, and one that logs is one somebody can find.
        logger.info("notification %s for tenant %s resolved no recipient", kind, tenant_id)
        return 0
    if len(unique) > MAX_RECIPIENTS:
        raise ValueError(
            f"notification {kind} names {len(unique)} recipients, over the "
            f"{MAX_RECIPIENTS} a per-recipient row is the cheap answer for"
        )

    written = 0
    for subject in unique:
        try:
            await session.execute(
                _INSERT,
                {
                    "tenant_id": tenant_id,
                    "user_id": subject,
                    "kind": kind,
                    "title": title[:200],
                    "body": body[:2000],
                    "url": url,
                    "severity": severity or declared.default_severity,
                },
            )
            written += 1
        except Exception:
            # One recipient's row failing must not cost the others theirs, and
            # must not cost the caller its transaction.
            logger.exception(
                "notification %s could not be written for one recipient", kind
            )
    return written


_SELECT = (
    "select id, kind, title, body, url, severity, created_at, read_at "
    "from public.notifications "
)


async def recent(
    session: AsyncSession, *, limit: int = PAGE, unread_only: bool = False
) -> list[Notification]:
    """This person's feed, newest first.

    Scoped by row-level security rather than by a predicate here: the policy
    admits `tenant_id = current_tenant_id() and user_id = current_user_id()`,
    so a query with no `where` clause returns exactly one person's feed. A
    hand-written predicate beside it would be a second place to get it wrong.
    """
    bounded = max(1, min(limit, MAX_PAGE))
    clause = "where read_at is null " if unread_only else ""
    result = await session.execute(
        text(f"{_SELECT}{clause}order by created_at desc limit :limit"),
        {"limit": bounded},
    )
    return [
        Notification(
            id=str(row.id),
            kind=row.kind,
            title=row.title,
            body=row.body,
            url=row.url,
            severity=row.severity,
            created_at=row.created_at,
            read_at=row.read_at,
        )
        for row in result
    ]


async def unread_count(session: AsyncSession) -> int:
    """How many this person has not read.

    The query this table serves most: the shell asks on every dashboard load.
    One index scan, because the recipient index leads with the tenant and the
    subject that row-level security has already restricted the query to.
    """
    result = await session.execute(
        text("select count(*) from public.notifications where read_at is null")
    )
    return int(result.scalar_one())


async def mark_read(session: AsyncSession, notification_id: str) -> bool:
    """Mark one read. False when there was nothing to mark.

    `read_at is null` in the predicate keeps the first timestamp: marking a
    notification read twice should not move the moment it was read, and a
    second call returning False is how the route answers 404 for a row that
    belongs to somebody else without ever looking at whose it is.
    """
    result = await session.execute(
        text(
            "update public.notifications set read_at = now() "
            "where id = :id and read_at is null returning id"
        ),
        {"id": notification_id},
    )
    # `returning` and a row count rather than `rowcount`, which lives on the
    # cursor result and not on the typed one -- the same reason the restore
    # sweep reaches for it through `getattr`. Counting what came back is
    # honest either way and needs no cast.
    return result.first() is not None


async def mark_all_read(session: AsyncSession) -> int:
    """Mark this person's unread notifications read. Returns how many."""
    result = await session.execute(
        text(
            "update public.notifications set read_at = now() "
            "where read_at is null returning id"
        )
    )
    return len(result.all())


async def dismiss(session: AsyncSession, notification_id: str) -> bool:
    """Remove one. False when there was nothing to remove."""
    result = await session.execute(
        text("delete from public.notifications where id = :id returning id"),
        {"id": notification_id},
    )
    return result.first() is not None
