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

**Both halves are written on the caller's session.** ADR 0008 rule 2: a
notification belongs with the transaction that produced it, so a rollback takes
it with it. The feed row is that notification; the mail is a *row saying a mail
is owed*, which can be rolled back even though a mail cannot.

That is the change Phase 3 made, on 2026-09-20. Until then `dispatch` handed
prepared mail back and the caller handed it to a FastAPI background task — the
arrangement PLAT-F1 was built to replace, because such a task runs in the API
process and is lost when it restarts. A deploy during a send lost the send, and
a mail server refusing connections for ten minutes lost every notification
raised in those ten minutes with nothing anywhere saying so.

## What is deliberately not here

No digest, which is Phase 4 and needs the outbox this now writes to. No
escalation — a rule that widens the audience when a critical notification goes
unacknowledged — because nothing in the product yet has an acknowledgement.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from koras_email import DEFAULT_LOCALE, Locale
from koras_settings import resolve as resolve_setting
from sqlalchemy.ext.asyncio import AsyncSession

from ..settings_catalogue import catalogue
from . import outbox
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
    #: Which language it was rendered in. Stored with it, because a retry must
    #: send the message that was decided rather than re-render it.
    locale: Locale = DEFAULT_LOCALE


@dataclass(frozen=True)
class Dispatched:
    """What each channel did. Returned rather than logged so a test can assert."""

    recipients: int = 0
    in_app: int = 0
    #: Owed. One outbox row per message, written on the caller's session and
    #: sent by the worker after the caller's transaction commits. The caller
    #: does not send them and has nothing to do with them.
    mail: tuple[Mail, ...] = field(default_factory=tuple)
    #: Messages that could not even be written down. Counted rather than
    #: raised, because a notification must not undo the thing that caused it.
    unrecorded: int = 0
    #: People a channel deliberately skipped, by reason. A preference is a
    #: reason; so is having no address.
    skipped: tuple[str, ...] = field(default_factory=tuple)


class Preferences:
    """Everyone's answers to the channel switches, read once per dispatch.

    **This was a function, and it read all three scopes on every call.** It is
    called once per person per channel, so the platform's defaults and the
    organisation's values — two row sets that cannot change during one dispatch
    — were re-read once per person per channel, and each member's own row twice.
    Ten approvers cost fifty-four statements where a dozen would do, on the
    request path, while somebody waited for an assistant to answer. DISP-01 in
    `docs/features/notifications/review.md`.

    It would have passed review by behaviour forever: every test asserted what
    was decided and none asked what it cost.

    What is *not* cached is the resolution itself. That still goes through
    `koras_settings.resolve`, because it is the property worth keeping — the
    answer the send uses and the answer the settings page shows are produced by
    the same code, and the reason `notifications.emailEnabled` could be switched
    off while mail kept arriving is that nothing consulted it at all.
    """

    def __init__(self, session: AsyncSession, tenant_id: str) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._global: dict[str, Any] | None = None
        self._organization: dict[str, Any] | None = None
        self._members: dict[str, dict[str, Any]] = {}
        #: True once any read has failed. The callers use it to decide which way
        #: to fail, and it is remembered rather than re-attempted: a settings
        #: table that would not answer once will not answer nine more times in
        #: the same request, and trying is nine more waits.
        self.unreadable = False

    async def _shared(self) -> tuple[dict[str, Any], dict[str, Any]]:
        if self._global is None or self._organization is None:
            try:
                self._global = await global_values(self._session)
                self._organization = await tenant_values(self._session, self._tenant_id)
            except Exception:
                logger.exception("the settings for %s could not be read", self._tenant_id)
                self.unreadable = True
                self._global = self._global or {}
                self._organization = self._organization or {}
        return self._global, self._organization

    async def member_values(self, subject: str) -> dict[str, Any]:
        """One member's own values, for a caller that needs them too.

        `recipients.resolve` reads a member's language, and it used to do so
        through its own path — so every person's row was read once for their
        language and again for each channel. Sharing this cache is what makes
        that one read. DISP-01.
        """
        return await self._member(subject)

    async def _member(self, subject: str | None) -> dict[str, Any]:
        """One person's own values. An address the platform gave has none.

        Recorded in `recipients.py` as the cost of an address that cannot be
        matched to a person: the organisation's value decides for them.
        """
        if not subject:
            return {}
        if subject not in self._members:
            try:
                self._members[subject] = await member_values(
                    self._session, self._tenant_id, subject
                )
            except Exception:
                logger.exception("a recipient's preferences could not be read")
                self.unreadable = True
                self._members[subject] = {}
        return self._members[subject]

    async def wants(self, key: str, subject: str | None, *, when_unknown: bool) -> bool:
        """Whether this person wants this channel.

        `when_unknown` is the caller's decision about which way to fail, and the
        two channels answer it differently on purpose. DISP-03.
        """
        shared, organization = await self._shared()
        mine = await self._member(subject)
        try:
            resolved, _ = resolve_setting(
                catalogue.require(key),
                global_values=shared,
                organization_values=organization,
                member_values=mine,
            )
        except Exception:
            logger.exception("the %s preference could not be resolved", key)
            self.unreadable = True
            return when_unknown
        if self.unreadable:
            # A value resolved from rows that could not be read is the
            # definition's default wearing a customer's clothes. Say so.
            return when_unknown
        return bool(resolved.value)


async def dispatch(session: AsyncSession, event: Event) -> Dispatched:
    """Tell everyone the rule names, by every channel they have not refused.

    Never raises. Every failure is a log line and a count, because the producer
    is in the middle of doing the thing the customer actually asked for.
    """
    # Raises, and it is the only thing here that does: a kind nobody registered
    # means nothing can classify, retain or translate it, which is a mistake at
    # the call site rather than a delivery failure.
    kinds.require(event.kind)

    # Built before the audience is resolved, so the language read and the two
    # channel reads share one cache per person rather than three.
    wants = Preferences(session, event.tenant_id)

    try:
        people = await resolve_audience(
            session,
            tenant_id=event.tenant_id,
            audience=event.audience,
            organization_id=event.organization_id,
            token=event.token,
            fallback_locale=event.fallback_locale,
            read_member=wants.member_values,
        )
    except Exception:
        logger.exception("the audience for %s could not be resolved", event.kind)
        return Dispatched()

    if not people:
        return Dispatched()

    skipped: list[str] = []
    # One rendering cache for the whole dispatch, so neither channel re-renders
    # a language the other already did.
    say = _renderer(event)
    in_app = await _to_feed(session, event, people, skipped, wants, say)
    mail = await _to_mail(event, people, skipped, wants, say)

    # Written here, on the caller's session, so a message is owed exactly when
    # the thing that caused it happened. The worker sends them.
    unrecorded = 0
    for message in mail:
        recorded = await outbox.enqueue(
            session,
            tenant_id=event.tenant_id,
            kind=event.kind,
            recipient=message.to,
            locale=message.locale,
            subject=message.subject,
            body_text=message.text,
            body_html=message.html,
        )
        if recorded is None:
            unrecorded += 1

    return Dispatched(
        recipients=len(people),
        in_app=in_app,
        mail=tuple(mail),
        skipped=tuple(skipped),
        unrecorded=unrecorded,
    )


def _renderer(event: Event) -> Callable[[Locale], Rendered | None]:
    """The template, called at most once per language.

    Both channels share one of these. The feed grouped by language and the
    inbox did not, so a template doing real work did it once per recipient in
    the inbox half — and the test that asserted "once per language" used a case
    with no addresses in it, so it could not see. DISP-02.

    `None` for a language the template refused to render, so a failure costs
    that language and not the dispatch.
    """
    done: dict[Locale, Rendered | None] = {}

    def render(locale: Locale) -> Rendered | None:
        if locale not in done:
            try:
                done[locale] = event.render(locale)
            except Exception:
                logger.exception(
                    "notification %s could not be rendered in %s", event.kind, locale
                )
                done[locale] = None
        return done[locale]

    return render


async def _to_feed(
    session: AsyncSession,
    event: Event,
    people: Sequence[Recipient],
    skipped: list[str],
    wants: Preferences,
    say: Callable[[Locale], Rendered | None],
) -> int:
    """The in-app half: one row per member who wants one.

    Grouped by language so two people who share a language provably see the
    same words.

    **Fails open.** A settings table that cannot be read leaves the feed row
    written, because the worst case is a notification somebody did not want in
    a list they can clear — against a notification nobody got at all.
    """
    wanted: dict[Locale, list[str]] = {}
    for person in people:
        if person.subject is None:
            continue
        if not await wants.wants(IN_APP_SETTING, person.subject, when_unknown=True):
            skipped.append(f"{person.subject}:in_app_off")
            continue
        wanted.setdefault(person.locale, []).append(person.subject)

    written = 0
    for locale, subjects in sorted(wanted.items()):
        rendered = say(locale)
        if rendered is None:
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
    event: Event,
    people: Sequence[Recipient],
    skipped: list[str],
    wants: Preferences,
    say: Callable[[Locale], Rendered | None],
) -> list[Mail]:
    """The inbox half: a message per address that wants one, ready to send.

    Prepared here and sent by the caller after its commit, because a mail
    cannot be rolled back and a feed row can. A template with no mail form
    contributes nothing, which is how a kind becomes in-app only.

    **Fails closed**, unlike the feed, and the asymmetry is the decision. A mail
    sent to somebody who switched mail off cannot be recalled; a mail withheld
    because a preference could not be read costs them nothing they have not
    already got, **because the feed row exists either way**. Holding it loses
    the second copy of a notification, not the notification. DISP-03.
    """
    prepared: list[Mail] = []
    for person in people:
        if not person.email:
            # A member with no address. Their feed row is the notification;
            # this is not a failure and is counted so a test can see it.
            skipped.append(f"{person.subject or '?'}:no_address")
            continue
        if not await wants.wants(EMAIL_SETTING, person.subject, when_unknown=False):
            # Distinguishable on purpose: a dispatch that held mail because it
            # could not read a preference is a different event from one that
            # held it because somebody opted out, and only the first is worth
            # anybody's attention.
            skipped.append(
                f"{person.email}:{'email_unknown' if wants.unreadable else 'email_off'}"
            )
            continue
        rendered = say(person.locale)
        if rendered is None:
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
                locale=person.locale,
            )
        )
    return prepared


__all__ = [
    "EMAIL_SETTING",
    "IN_APP_SETTING",
    "Dispatched",
    "Preferences",
    "Event",
    "Mail",
    "Rendered",
    "Template",
    "dispatch",
]
