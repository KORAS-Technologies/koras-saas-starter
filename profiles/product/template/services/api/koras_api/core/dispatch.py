"""One place a notification leaves from, and the channels it leaves by.

ADR 0008 rule 2: notification gets **one in-process dispatch point**, and audit
stays a direct call. There is no event bus, deliberately — a bus is a thing to
debug, and one function that fans out to two channels is not.

Before this the starter's only producer wrote its own feed row, resolved its own
audience twice, composed its own HTML and sent its own mail, all inside
`core/notify.py`. A second producer would have copied all four. NOTIF-GAP-002
and NOTIF-GAP-004.

## What a producer says now

```python
await dispatch(
    session,
    Event(
        kind=APPROVAL_REQUESTED.key,
        tenant_id=tenant.id,
        audience=Audience(permission="ai.approve", include_owner=True),
        render=lambda locale: approval_notice(locale, ...),
    ),
)
```

It names *what happened*, *who should know* and *how to say it in a language*.
It does not name a channel, a table, a template file or an address.

## The rule every channel follows

**A channel decides per recipient, and a refusal is not a failure.** A person
who has switched email off is not an error; a channel that cannot reach its
provider is not one either. `dispatch` returns what each channel did and never
raises, because a producer is in the middle of doing the thing the customer
actually asked for.

**The feed is written on the caller's session; mail is not sent on it.**
ADR 0008 rule 2 again: the row belongs with the transaction that produced it,
so a rollback takes the notification with it. A mail cannot be rolled back, so
it goes out after the commit, from a background task — which is why `dispatch`
returns the mail as *pending work* rather than sending it itself.

## What is deliberately not here

No outbox, no delivery log, no retry, no digest. Those are Phase 3 and Phase 4,
and each needs a table. A notification that fails to send today is a log line,
which is honest for a product whose only producer is an approval notice, and
would not be for one that sends invoices.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from koras_email import DEFAULT_LOCALE, EmailSender, Locale
from koras_settings import resolve as resolve_setting
from sqlalchemy.ext.asyncio import AsyncSession

from ..settings_catalogue import catalogue
from .notifications import Severity, kinds, notify
from .recipients import Audience, Recipient
from .recipients import resolve as resolve_audience
from .settings_store import global_values, member_values, tenant_values

logger = logging.getLogger(__name__)

#: What the settings catalogue calls the two switches this honours.
IN_APP_SETTING = "notifications.inAppEnabled"
EMAIL_SETTING = "notifications.emailEnabled"


@dataclass(frozen=True)
class Rendered:
    """One notification, in one language.

    `title` and `body` are what the feed shows; `subject`, `text` and `html`
    are what a mail carries. A template that has no mail form returns `None`
    for `html`, and the email channel skips it rather than sending a blank —
    which is what makes "this kind is in-app only" a property of the template
    rather than a flag somewhere else.
    """

    title: str
    body: str = ""
    url: str = ""
    severity: Severity | None = None
    subject: str = ""
    text: str = ""
    html: str | None = None


#: A template: a language in, a rendering out. Synchronous on purpose — a
#: template that needed the database would be a template deciding what to say
#: from state the producer has already read.
Template = Callable[[Locale], Rendered]


@dataclass(frozen=True)
class Event:
    """Something that happened, and who should hear about it."""

    kind: str
    tenant_id: str
    audience: Audience
    render: Template
    #: The organisation's language, used for anybody whose own is unknown.
    fallback_locale: Locale = DEFAULT_LOCALE
    #: Only needed to reach the platform's member list for addresses.
    organization_id: str = ""
    token: str = ""


@dataclass(frozen=True)
class Mail:
    """One message, ready to send once the caller's transaction has committed."""

    to: str
    subject: str
    text: str
    html: str
    #: The notification kind, dotted, which goes into the Message-ID.
    tag: str = "notification"


@dataclass(frozen=True)
class Dispatched:
    """What each channel did. Returned rather than logged so a test can assert."""

    recipients: int = 0
    in_app: int = 0
    #: Not sent — *prepared*. The caller sends these after its commit.
    mail: tuple[Mail, ...] = field(default_factory=tuple)
    #: People a channel deliberately skipped, by reason. A preference is a
    #: reason; so is having no address.
    skipped: tuple[str, ...] = field(default_factory=tuple)


async def _enabled(
    session: AsyncSession,
    *,
    key: str,
    tenant_id: str,
    subject: str | None,
) -> bool:
    """Whether this person wants this channel, resolved the way the page shows it.

    Through `koras_settings.resolve` rather than by reading a row, so the answer
    the send uses and the answer the settings page displays are produced by the
    same code. That is the property the settings framework exists for, and the
    reason `notifications.emailEnabled` could be switched off while mail kept
    arriving is that nothing here consulted it at all.

    A recipient with no subject — an address the platform gave — has no member
    preference to read, so the organisation's value decides. Recorded in
    `recipients.py` as the cost of an address that cannot be matched to a
    person.

    Never raises: an unreadable settings table must not stop a notification. It
    fails **open**, which is the right direction for this particular switch —
    the alternative is silently telling nobody anything.
    """
    try:
        definition = catalogue.require(key)
        resolved, _ = resolve_setting(
            definition,
            global_values=await global_values(session),
            organization_values=await tenant_values(session, tenant_id),
            member_values=(
                await member_values(session, tenant_id, subject) if subject else {}
            ),
        )
    except Exception:
        logger.exception("the %s preference could not be resolved; assuming on", key)
        return True
    return bool(resolved.value)


async def dispatch(session: AsyncSession, event: Event) -> Dispatched:
    """Tell everyone the rule names, by every channel they have not refused.

    Never raises. Every failure is a log line and a count, because the producer
    is in the middle of doing the thing the customer actually asked for.
    """
    try:
        kinds.require(event.kind)
    except KeyError:
        # A programming error, and the only one worth raising for: a kind
        # nobody registered means nothing can classify, retain or translate it.
        raise

    try:
        people = await resolve_audience(
            session,
            tenant_id=event.tenant_id,
            audience=event.audience,
            organization_id=event.organization_id,
            token=event.token,
            fallback_locale=event.fallback_locale,
        )
    except Exception:
        logger.exception("the audience for %s could not be resolved", event.kind)
        return Dispatched()

    if not people:
        return Dispatched()

    skipped: list[str] = []
    in_app = await _to_feed(session, event, people, skipped)
    mail = await _to_mail(session, event, people, skipped)
    return Dispatched(
        recipients=len(people),
        in_app=in_app,
        mail=tuple(mail),
        skipped=tuple(skipped),
    )


async def _to_feed(
    session: AsyncSession,
    event: Event,
    people: Sequence[Recipient],
    skipped: list[str],
) -> int:
    """The in-app half: one row per member who wants one.

    Grouped by language so a rendering is done once per language rather than
    once per person, and so two people who share a language provably see the
    same words.
    """
    wanted: dict[Locale, list[str]] = {}
    for person in people:
        if person.subject is None:
            continue
        if not await _enabled(
            session, key=IN_APP_SETTING, tenant_id=event.tenant_id, subject=person.subject
        ):
            skipped.append(f"{person.subject}:in_app_off")
            continue
        wanted.setdefault(person.locale, []).append(person.subject)

    written = 0
    for locale, subjects in sorted(wanted.items()):
        try:
            rendered = event.render(locale)
        except Exception:
            logger.exception("notification %s could not be rendered in %s", event.kind, locale)
            continue
        written += await notify(
            session,
            tenant_id=event.tenant_id,
            recipients=subjects,
            kind=event.kind,
            title=rendered.title,
            body=rendered.body,
            url=rendered.url,
            severity=rendered.severity,
        )
    return written


async def _to_mail(
    session: AsyncSession,
    event: Event,
    people: Sequence[Recipient],
    skipped: list[str],
) -> list[Mail]:
    """The inbox half: a message per address that wants one, ready to send.

    Prepared here and sent by the caller after its commit, because a mail
    cannot be rolled back and a feed row can. A template with no mail form
    contributes nothing, which is how a kind becomes in-app only.
    """
    prepared: list[Mail] = []
    for person in people:
        if not person.email:
            # A member with no address. Their feed row is the notification;
            # this is not a failure and is counted so a test can see it.
            skipped.append(f"{person.subject or '?'}:no_address")
            continue
        if not await _enabled(
            session, key=EMAIL_SETTING, tenant_id=event.tenant_id, subject=person.subject
        ):
            skipped.append(f"{person.email}:email_off")
            continue
        try:
            rendered = event.render(person.locale)
        except Exception:
            logger.exception(
                "notification %s could not be rendered in %s", event.kind, person.locale
            )
            continue
        if rendered.html is None or not rendered.subject.strip():
            skipped.append(f"{person.email}:no_mail_form")
            continue
        prepared.append(
            Mail(
                to=person.email,
                subject=rendered.subject,
                text=rendered.text,
                html=rendered.html,
                tag=event.kind,
            )
        )
    return prepared


async def send(sender: EmailSender, mail: Sequence[Mail]) -> int:
    """Send what `dispatch` prepared. Returns how many left.

    Called after the caller's commit, from a background task. Every failure is
    swallowed and logged: the thing the customer asked for has already
    happened, and a send that fails must not undo it. Phase 3 gives this an
    outbox so a failure is a row somebody can retry rather than a log line.
    """
    sent = 0
    for message in mail:
        try:
            await sender.send(
                to=message.to,
                subject=message.subject,
                body=message.text,
                html=message.html,
                # Names the kind of message, so a duplicate in an inbox is
                # recognisable as a duplicate rather than a second event.
                tag=message.tag,
            )
            sent += 1
        except Exception:
            logger.exception("a notification mail could not be sent")
    return sent


__all__ = [
    "EMAIL_SETTING",
    "IN_APP_SETTING",
    "Dispatched",
    "Event",
    "Mail",
    "Rendered",
    "Template",
    "dispatch",
    "send",
]
