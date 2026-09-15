"""Tell the people who can approve that the assistant is waiting for them.

An action that is not a read waits for a person. Until now it waited in the
assistant drawer and nowhere else, so an approver who was not looking at the
page did not know, and an action could sit for hours. This sends the notice.

Who is told: the organization's owner, whose address the tenant row has held
since provisioning, and every active member the platform lists whose role
carries `ai.approve` -- owners and administrators. The platform is asked
with the caller's own token, so a product learns its own members and no
other organization's; without a platform the owner alone is told.

What is sent: who asked, in their own words, and what the assistant proposed
to do about it, in plain words -- "Delete the file AI_FOUNDATION_PLAN.md
(16 KB)", not a tool id and an argument map -- with a button to the place
where it is decided. The approver is in the same organization as the person
who asked, so the request and the file's name are theirs to see; what the
model said in between is not sent, because an inbox is not the
conversation.

How it is sent: through `koras_email`, as HTML with a plain-text twin, over
SMTP to whichever provider the environment's SMTP_* settings name, and
recorded rather than sent when no host is set -- so a product without a
provider still runs and the log says what it would have sent.

In which language: the one the request was made in, which the API learns
from `Accept-Language` (`core/locale.py`). The approvers are other people,
and what *they* read is not known to a product yet -- a member's stored
preference and a tenant default are F20's other half -- so the requester's
language stands in for the organization's until it is. What is translated
is the notice's own sentences; the description of each action ("Delete the
file X") is composed by `summarize` in English, because a per-tool catalogue
is the assistant's to grow (FOLLOW_UPS F24).
"""

from __future__ import annotations

import html
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from koras_ai import ActionStatus, ProposedAction
from koras_auth.permissions import permissions_for
from koras_email import DEFAULT_LOCALE, EmailSender, Locale, sender_for, translate
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import platform
from .settings import settings

logger = logging.getLogger(__name__)

_OWNER_EMAIL = text("select owner_email from public.tenants where id = :tenant_id")

_FILE_BY_ID = text(
    "select name, size_bytes, ready_at from public.files "
    "where id = cast(:id as uuid) and tenant_id = :tenant_id and status = 'ready'"
)

#: How a timestamp reads in each language: English month names are English.
_WHEN_FORMAT: dict[str, str] = {
    "en": "%d %b %Y, %H:%M UTC",
    "de": "%d.%m.%Y, %H:%M UTC",
    "es": "%d/%m/%Y, %H:%M UTC",
}

#: How an operation class reads to a person.
_OPERATION_WORDS = {
    "read": "reads",
    "write": "changes something",
    "destructive": "deletes something",
    "external": "sends something outside",
}


@dataclass(frozen=True)
class Requester:
    """Who asked, as the token said: the name if it carried one, else the address."""

    id: str
    name: str | None = None
    email: str | None = None

    def display(self) -> str:
        if self.name and self.email:
            return f"{self.name} ({self.email})"
        return self.name or self.email or "a member of the organization"


@dataclass(frozen=True)
class ActionSummary:
    """One proposed action, in the words an approver needs."""

    tool_id: str
    operation: str
    title: str
    detail: str


def mail_sender() -> EmailSender:
    """The product's sender: real with a host, recording without one."""
    return sender_for(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username or None,
        password=settings.smtp_password or None,
        sender=settings.smtp_from,
        use_tls=settings.smtp_secure,
    )


def awaiting(actions: Sequence[ProposedAction]) -> list[ProposedAction]:
    return [a for a in actions if a.status is ActionStatus.AWAITING_APPROVAL]


def approvers_from_members(members: object) -> list[str]:
    """Active members whose role may approve, from the platform's member list."""
    if not isinstance(members, list):
        return []
    found: list[str] = []
    for member in members:
        if not isinstance(member, dict):
            continue
        email = member.get("email")
        role = member.get("role")
        status = member.get("status", "active")
        if not (isinstance(email, str) and email and isinstance(role, str)):
            continue
        if status != "active":
            continue
        if "ai.approve" in permissions_for([role]):
            found.append(email.strip().lower())
    return found


async def approvers(
    session: AsyncSession | None, *, tenant_id: str, organization_id: str, token: str
) -> list[str]:
    """Every address to tell, the owner first, each once."""
    addresses: list[str] = []
    if session is not None:
        owner = (await session.execute(_OWNER_EMAIL, {"tenant_id": tenant_id})).scalar_one_or_none()
        if isinstance(owner, str) and owner.strip():
            addresses.append(owner.strip().lower())
    if platform.configured() and token:
        answer = await platform.read_portal(
            "/api/portal/v1/members", organization_id=organization_id, token=token
        )
        body: Any = answer.body if answer is not None else None
        addresses.extend(approvers_from_members(body))
    seen: set[str] = set()
    unique: list[str] = []
    for address in addresses:
        if address not in seen:
            seen.add(address)
            unique.append(address)
    return unique


def _size(size_bytes: object) -> str:
    if not isinstance(size_bytes, int):
        return ""
    if size_bytes >= 1_000_000:
        return f"{size_bytes / 1_000_000:.1f} MB"
    if size_bytes >= 1_000:
        return f"{size_bytes / 1_000:.0f} KB"
    return f"{size_bytes} bytes"


async def summarize(
    session: AsyncSession | None, *, tenant_id: str, actions: Sequence[ProposedAction]
) -> list[ActionSummary]:
    """Each action as a sentence, looking up what its arguments point at.

    A file id becomes the file's name and size; anything else is the tool's
    id with its arguments shown as plain `key: value` pairs, strings only,
    so an approver of a tool this module does not know still sees what was
    asked for.
    """
    summaries: list[ActionSummary] = []
    for action in actions:
        title, detail = await _describe(session, tenant_id, action)
        summaries.append(
            ActionSummary(
                tool_id=action.tool_id,
                operation=action.operation.value,
                title=title,
                detail=detail,
            )
        )
    return summaries


async def _describe(
    session: AsyncSession | None, tenant_id: str, action: ProposedAction
) -> tuple[str, str]:
    arguments: Mapping[str, Any] = action.input
    if action.tool_id == "files.delete":
        file_id = str(arguments.get("file_id") or "")
        if session is not None and file_id:
            try:
                row = (
                    await session.execute(_FILE_BY_ID, {"id": file_id, "tenant_id": tenant_id})
                ).first()
            except Exception:
                logger.info("the file behind an approval notice could not be read")
                row = None
            if row is not None:
                when = row.ready_at.strftime("%d %b %Y") if row.ready_at else ""
                detail = f"{_size(row.size_bytes)}, uploaded {when}".strip(", ")
                return f"Delete the file {row.name}", detail
        return "Delete a file", f"file id {file_id or 'unknown'}"
    pairs = ", ".join(
        f"{key}: {value}" for key, value in arguments.items() if isinstance(value, str | int)
    )
    verb = _OPERATION_WORDS.get(action.operation.value, action.operation.value)
    return f"Run {action.tool_id}, which {verb}", pairs[:300]


def compose(
    summaries: Sequence[ActionSummary],
    *,
    product: str,
    app_url: str,
    requester: Requester,
    request_text: str,
    requested_at: datetime,
    locale: Locale = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    """Subject, plain text, and HTML. The same words in both bodies, in one language."""
    first = summaries[0].title if summaries else "an action"
    subject = (
        translate(locale, "approval_subject_one", product=product, first=first)
        if len(summaries) == 1
        else translate(locale, "approval_subject_many", product=product, count=len(summaries))
    )
    where = f"{app_url.rstrip('/')}/dashboard/assistant" if app_url else ""
    who = requester.display()
    when = requested_at.astimezone(UTC).strftime(_WHEN_FORMAT.get(locale, _WHEN_FORMAT["en"]))
    asked = request_text.strip()[:300]
    no_message = translate(locale, "approval_no_message")
    proposed = translate(
        locale, "approval_proposed_many" if len(summaries) > 1 else "approval_proposed_one"
    )
    not_run = translate(locale, "approval_not_run")

    lines = [
        translate(locale, "approval_asked", who=who, product=product),
        f'  "{asked}"' if asked else f"  {no_message}",
        "",
        proposed,
    ]
    for summary in summaries:
        lines.append(f"  - {summary.title}" + (f" ({summary.detail})" if summary.detail else ""))
    lines += [
        "",
        not_run,
        translate(locale, "approval_review_at", where=where)
        if where
        else translate(locale, "approval_review_on_page"),
        "",
        translate(locale, "approval_requested_at", when=when),
    ]
    text_body = "\n".join(lines)

    e = html.escape
    items = "".join(
        f'<li style="margin:0 0 8px 0;"><strong>{e(s.title)}</strong>'
        + (f'<br><span style="color:#5b6470;">{e(s.detail)}</span>' if s.detail else "")
        + "</li>"
        for s in summaries
    )
    button = (
        f'<a href="{e(where)}" style="display:inline-block;background:#3b5bdb;color:#ffffff;'
        'text-decoration:none;padding:12px 20px;border-radius:6px;font-weight:600;">'
        f"{e(translate(locale, 'approval_button'))}</a>"
        if where
        else f"<strong>{e(translate(locale, 'approval_review_on_page'))}</strong>"
    )
    html_body = _html_document(
        product=product,
        who=who,
        asked=asked,
        items=items,
        button=button,
        when=when,
        locale=locale,
    )
    return subject, text_body, html_body


_FONT = "-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif"
_MUTED = "color:#5b6470;"
_CELL = "padding:18px 28px 0 28px;font-size:15px;line-height:1.5;"


def _html_document(
    *,
    product: str,
    who: str,
    asked: str,
    items: str,
    button: str,
    when: str,
    locale: Locale = DEFAULT_LOCALE,
) -> str:
    """The notice as a small table-based page every mail client renders alike."""
    e = html.escape
    # `approval_asked` is one sentence with the name inside it; the name is the
    # bold part, so the sentence is split around the placeholder here.
    asked_sentence = e(translate(locale, "approval_asked", who="\x00", product=product)).replace(
        "\x00", f"<strong>{e(who)}</strong>"
    )
    quote = (
        "margin:10px 0 0 0;padding:10px 14px;background:#f4f5f7;"
        "border-left:3px solid #3b5bdb;border-radius:4px;font-style:italic;"
    )
    card = (
        "max-width:560px;width:100%;background:#ffffff;border-radius:8px;border:1px solid #e3e6ea;"
    )
    rows = [
        f'<tr><td style="padding:20px 28px 0 28px;font-size:13px;{_MUTED}'
        'letter-spacing:.04em;text-transform:uppercase;">'
        f"{e(product)} &middot; {e(translate(locale, 'approval_eyebrow'))}</td></tr>",
        '<tr><td style="padding:8px 28px 0 28px;font-size:22px;font-weight:700;">'
        f"{e(translate(locale, 'approval_heading'))}</td></tr>",
        f'<tr><td style="{_CELL}">{asked_sentence}'
        f'<blockquote style="{quote}">'
        f"{e(asked) if asked else e(translate(locale, 'approval_no_message'))}</blockquote>"
        "</td></tr>",
        f'<tr><td style="{_CELL}">{e(translate(locale, "approval_proposed_one"))}'
        f'<ul style="margin:8px 0 0 0;padding-left:20px;">{items}</ul></td></tr>',
        f'<tr><td style="{_CELL}font-size:14px;{_MUTED}">'
        f"{e(translate(locale, 'approval_not_run'))}</td></tr>",
        f'<tr><td style="padding:22px 28px 0 28px;">{button}</td></tr>',
        '<tr><td style="padding:22px 28px 24px 28px;font-size:12px;color:#8a929c;'
        'border-top:1px solid #e3e6ea;">'
        f"{e(translate(locale, 'approval_footer', when=when))}</td></tr>",
    ]
    return (
        "<!doctype html>\n"
        f'<html><body style="margin:0;padding:0;background:#f4f5f7;font-family:{_FONT};'
        'color:#1f2933;">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'style="background:#f4f5f7;padding:24px 0;"><tr><td align="center">'
        f'<table role="presentation" width="560" cellspacing="0" cellpadding="0" style="{card}">'
        + "".join(rows)
        + "</table></td></tr></table></body></html>"
    )


async def notify_awaiting_approval(
    *,
    recipients: Sequence[str],
    summaries: Sequence[ActionSummary],
    product: str,
    app_url: str,
    requester: Requester,
    request_text: str,
    requested_at: datetime | None = None,
    tag: str = "ai-approval",
    sender: EmailSender | None = None,
    locale: Locale = DEFAULT_LOCALE,
) -> int:
    """Send one notice per recipient, in `locale`. Returns how many were sent or recorded."""
    if not summaries or not recipients:
        return 0
    subject, body, html_body = compose(
        summaries,
        product=product,
        app_url=app_url,
        requester=requester,
        request_text=request_text,
        requested_at=requested_at or datetime.now(UTC),
        locale=locale,
    )
    mailer = sender or mail_sender()
    sent = 0
    for address in recipients:
        try:
            outcome = await mailer.send(
                to=address, subject=subject, body=body, tag=tag, html=html_body
            )
        except Exception:
            logger.exception("approval notice to one approver could not be sent")
            continue
        sent += 1
        if outcome.simulated:
            logger.info(
                "approval notice recorded, not sent (no mail host): %d action(s) waiting",
                len(summaries),
            )
    return sent
