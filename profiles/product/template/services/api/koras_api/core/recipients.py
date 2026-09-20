"""Who a notification is for, expressed as a rule rather than a query.

Before this, the one producer in the starter resolved its own audience twice —
`approver_subjects` for the feed and `approvers` for the inbox — with the
permission `ai.approve` written into both. A second producer would have copied
both. NOTIF-GAP-004.

**A rule, not a list.** A caller says *members who may approve*, or *these
three people*, or *the owner*; this turns that into recipients. What it will
not take is a list of email addresses, because an address is not a person and
the product cannot decide what language to write to an address in, whether it
has switched notifications off, or whether it belongs to somebody who can open
the link.

## The two halves that do not join, and why that is said out loud

A notification has two destinations and the product knows its people
differently in each.

- **The feed** goes to a *subject* — a row in `tenant_members`, somebody who
  can open the product. No platform call, works when the Control Plane is
  unreachable, and cannot address somebody with no way to read it.
- **A mail** goes to an *address* — `tenants.owner_email`, plus whatever the
  platform's member list holds. That list carries an email and a role and
  **not** the ZITADEL subject, so an address cannot be matched back to a
  member.

So a recipient may have a subject, or an address, or both, and the honest shape
is one that says which. The consequence is recorded rather than hidden: a
member whose address comes only from the platform has no resolvable language
and no resolvable preference, so the email channel writes to them in the
organisation's language and cannot honour a preference they have set. Closing
that needs the platform to answer the subject beside the address, which is a
contract change and is F26 in `docs/FOLLOW_UPS.md`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from koras_auth.permissions import permissions_for
from koras_email import DEFAULT_LOCALE, SUPPORTED_LOCALES, Locale
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .settings_store import member_values

logger = logging.getLogger(__name__)


def _platform() -> Any:  # noqa: ANN401 - the platform client module
    """The platform client, imported at the point of use rather than at import.

    **Deliberate, and the reason is the worker.** `core.platform` reads the
    API's own `Settings()` at import, which is built at import too -- so a plain
    import here would mean anything importing this module needs the API's whole
    environment. The import commit dispatches from the worker, and a worker that
    had to satisfy the API's settings to announce a finished import would be a
    worker with the API's configuration surface, which is the boundary the
    worker image is built to keep.

    Reached only on the branch that needs it: an audience resolved by permission
    in a request that carried a token. A background send never gets there.
    """
    from . import platform

    return platform

_MEMBERS = text(
    "select user_id, role from public.tenant_members where tenant_id = :tenant_id"
)
_OWNER_EMAIL = text("select owner_email from public.tenants where id = :tenant_id")


@dataclass(frozen=True)
class Recipient:
    """One person to tell, and everything needed to tell them."""

    #: The person as this product knows them. `None` for an address the
    #: platform gave that cannot be matched to a member.
    subject: str | None
    #: Where a mail goes. `None` for a member whose address the product does
    #: not hold — which is every member when the platform is unreachable.
    email: str | None
    #: What language to write in. The member's own where the product holds it;
    #: otherwise whatever the caller passed as the organisation's.
    locale: Locale = DEFAULT_LOCALE
    #: True when `locale` is this person's own choice rather than a fallback.
    #: The email channel logs the difference rather than pretending.
    locale_is_theirs: bool = False

    def key(self) -> str:
        """What makes two recipients the same person, for de-duplication."""
        return self.subject or (self.email or "")


@dataclass(frozen=True)
class Audience:
    """A rule saying who to tell. Composable; each part adds people.

    Deliberately not a callable. A rule that is data can be logged, compared in
    a test and declared beside a template; a rule that is a lambda can only be
    run.
    """

    #: Members whose role carries this permission. The common case, and the one
    #: that used to be a hardcoded string in the only producer.
    permission: str | None = None
    #: Named people, by subject. For a notification about a person's own thing.
    subjects: tuple[str, ...] = field(default_factory=tuple)
    #: The organisation's owner, whose address the tenant row holds. Their
    #: subject is not on that row, so this contributes an address and may
    #: contribute no subject at all.
    include_owner: bool = False

    def __post_init__(self) -> None:
        if not (self.permission or self.subjects or self.include_owner):
            raise ValueError(
                "an audience with no permission, no subjects and no owner is a "
                "notification nobody receives; say who it is for"
            )


#: How one member's stored values are read. Injected so a caller that is
#: already reading them — `dispatch.Preferences` is — reads each person's row
#: **once** rather than once for their language and again for each channel.
#: Ten approvers cost twenty reads of ten rows before this, which is DISP-01.
MemberReader = Callable[[str], Awaitable[Mapping[str, Any]]]


def _reader(session: AsyncSession, tenant_id: str) -> MemberReader:
    """The default, for a caller with nothing to share."""

    async def read(subject: str) -> Mapping[str, Any]:
        return await member_values(session, tenant_id, subject)

    return read


async def _locale_of(read: MemberReader, subject: str) -> tuple[Locale, bool]:
    """A member's own language, and whether it is really theirs.

    Read from the member's stored settings rather than from the request, which
    is NOTIF-DEF-003. The assistant's approval notice went out in the language
    of the person who *asked*, which is the one person it is never sent to.

    `auto` means "infer it from context" — ADR 0007's rule — and there is no
    context in a background send, so it falls back like an absent value.
    """
    try:
        values = await read(subject)
    except Exception:
        logger.exception("a recipient's language could not be read; using the default")
        return DEFAULT_LOCALE, False
    chosen = values.get("general.language")
    # Checked against the languages this product actually has a catalogue for,
    # which does two jobs at once. A stored value that is not one of them is a
    # value the product cannot write in. And `auto` -- ADR 0007's rule that an
    # inference must be a value rather than an absence -- is not a language, so
    # it falls through here exactly as an absent setting does. There is no
    # context to infer from in a background send.
    if isinstance(chosen, str) and chosen in SUPPORTED_LOCALES:
        return chosen, True
    return DEFAULT_LOCALE, False


async def resolve(
    session: AsyncSession,
    *,
    tenant_id: str,
    audience: Audience,
    organization_id: str = "",
    token: str = "",
    fallback_locale: Locale = DEFAULT_LOCALE,
    read_member: MemberReader | None = None,
) -> list[Recipient]:
    """Everyone the rule names, each once, with their language where known.

    Never raises. A rule that resolves to nobody returns an empty list and logs
    it — which is a question for the caller, not a failure of the send.

    One settings read per member, and **one** rather than two since 2026-09-20:
    `read_member` lets a caller that is already reading those rows share its
    cache. That is still a read per member, which is fine for an audience of
    approvers and would not be for every member of a large organisation; when a
    producer needs the second shape, this is the function that grows a bulk
    read rather than each caller growing a cache.
    """
    read = read_member or _reader(session, tenant_id)
    by_key: dict[str, Recipient] = {}

    def add(candidate: Recipient) -> None:
        key = candidate.key()
        if not key:
            return
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = candidate
            return
        # Merge rather than replace: the same person resolved by two parts of
        # the rule may carry a subject from one and an address from the other.
        by_key[key] = Recipient(
            subject=existing.subject or candidate.subject,
            email=existing.email or candidate.email,
            locale=existing.locale if existing.locale_is_theirs else candidate.locale,
            locale_is_theirs=existing.locale_is_theirs or candidate.locale_is_theirs,
        )

    wanted: set[str] = set(audience.subjects)
    if audience.permission:
        try:
            rows = (await session.execute(_MEMBERS, {"tenant_id": tenant_id})).all()
        except Exception:
            logger.exception("the members of %s could not be read", tenant_id)
            rows = []
        for row in rows:
            role = row.role if isinstance(row.role, str) else ""
            if role and audience.permission in permissions_for([role]):
                wanted.add(str(row.user_id))

    for subject in sorted(wanted):
        locale, theirs = await _locale_of(read, subject)
        add(
            Recipient(
                subject=subject,
                email=None,
                locale=locale if theirs else fallback_locale,
                locale_is_theirs=theirs,
            )
        )

    if audience.include_owner:
        try:
            owner = (
                await session.execute(_OWNER_EMAIL, {"tenant_id": tenant_id})
            ).scalar_one_or_none()
        except Exception:
            logger.exception("the owner of %s could not be read", tenant_id)
            owner = None
        if isinstance(owner, str) and owner.strip():
            # No subject: the tenant row holds the address and not the person.
            add(Recipient(subject=None, email=owner.strip().lower(), locale=fallback_locale))

    if audience.permission and token and organization_id and _platform().configured():
        for address in await _platform_addresses(
            organization_id=organization_id, token=token, permission=audience.permission
        ):
            add(Recipient(subject=None, email=address, locale=fallback_locale))

    people = sorted(by_key.values(), key=lambda person: person.key())
    if not people:
        logger.info("an audience for tenant %s resolved nobody", tenant_id)
    return people


async def _platform_addresses(
    *, organization_id: str, token: str, permission: str
) -> list[str]:
    """Member addresses the platform holds, for roles carrying the permission.

    With the caller's own token, so a product learns its own members and no
    other organisation's. A platform that cannot be reached contributes
    nothing, which leaves the feed and the owner — the design point of having
    both halves.
    """
    try:
        answer = await _platform().read_portal(
            "/api/portal/v1/members", organization_id=organization_id, token=token
        )
    except Exception:
        logger.exception("the platform's member list could not be read")
        return []
    return addresses_from_members(answer.body if answer is not None else None, permission)


def addresses_from_members(members: Any, permission: str) -> list[str]:  # noqa: ANN401
    """Active members whose role carries the permission, as addresses.

    Pure, and separately tested, because the shape the platform answers is not
    this product's to guarantee: anything that is not the expected shape is
    skipped rather than raising, so one malformed member does not cost the
    other nine their notice.
    """
    if not isinstance(members, list):
        return []
    found: list[str] = []
    for member in members:
        if not isinstance(member, dict):
            continue
        email = member.get("email")
        role = member.get("role")
        if not (isinstance(email, str) and email.strip() and isinstance(role, str)):
            continue
        if member.get("status", "active") != "active":
            continue
        if permission in permissions_for([role]):
            found.append(email.strip().lower())
    return found


def subjects_of(people: Sequence[Recipient]) -> list[str]:
    """The people who can open the product. What the feed is written for."""
    return [person.subject for person in people if person.subject]


__all__ = [
    "Audience",
    "MemberReader",
    "Recipient",
    "addresses_from_members",
    "resolve",
    "subjects_of",
]
