"""Tell the people who can approve that the assistant is waiting for them.

An action that is not a read waits for a person. Until now it waited in the
assistant drawer and nowhere else, so an approver who was not looking at the
page did not know, and an action could sit for hours. This sends the notice.

Who is told: the organization's owner, whose address the tenant row has held
since provisioning, and every active member the platform lists whose role
carries `ai.approve` -- owners and administrators. The platform is asked
with the caller's own token, so a product learns its own members and no
other organization's; without a platform the owner alone is told.

What is sent: which tool, proposed by whom, and where to go. Never the
proposal's input and never a message: the mail crosses a boundary the
conversation does not, and a file name in an inbox is a leak nobody meant.

How it is sent: through `koras_email`, over SMTP to whichever provider the
environment's SMTP_* settings name, and recorded rather than sent when no
host is set -- so a product without a provider still runs and the log says
what it would have sent.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from koras_ai import ActionStatus, ProposedAction
from koras_auth.permissions import permissions_for
from koras_email import EmailSender, sender_for
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import platform
from .settings import settings

logger = logging.getLogger(__name__)

_OWNER_EMAIL = text("select owner_email from public.tenants where id = :tenant_id")


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


def compose(actions: Sequence[ProposedAction], *, product: str, app_url: str) -> tuple[str, str]:
    """Subject and body. Tool ids and who proposed; nothing the model wrote."""
    count = len(actions)
    subject = (
        f"[{product}] The assistant is waiting for approval"
        if count == 1
        else f"[{product}] The assistant is waiting for {count} approvals"
    )
    where = f"{app_url.rstrip('/')}/dashboard/assistant" if app_url else "the assistant page"
    lines = [
        "The assistant proposed an action that runs only after somebody approves it."
        if count == 1
        else f"The assistant proposed {count} actions that run only after somebody approves them.",
        "",
    ]
    for action in actions:
        lines.append(
            f"- {action.tool_id} ({action.operation.value}), proposed by {action.proposed_by}"
        )
    lines += ["", f"Approve or reject it at {where}.", "", "Nothing runs until you decide."]
    return subject, "\n".join(lines)


async def notify_awaiting_approval(
    *,
    recipients: Sequence[str],
    actions: Sequence[ProposedAction],
    product: str,
    app_url: str,
    sender: EmailSender | None = None,
) -> int:
    """Send one notice per recipient. Returns how many were sent or recorded."""
    waiting = awaiting(actions)
    if not waiting or not recipients:
        return 0
    subject, body = compose(waiting, product=product, app_url=app_url)
    mailer = sender or mail_sender()
    sent = 0
    for address in recipients:
        try:
            outcome = await mailer.send(
                to=address, subject=subject, body=body, tag=f"ai-approval:{waiting[0].id}"
            )
        except Exception:
            logger.exception("approval notice to one approver could not be sent")
            continue
        sent += 1
        if outcome.simulated:
            logger.info(
                "approval notice recorded, not sent (no mail host): %d action(s) waiting",
                len(waiting),
            )
    return sent
