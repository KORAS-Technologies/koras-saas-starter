"""Sending transactional mail, and being honest about not sending it.

Mail is sent server-side. A product's Next.js applications do not send it and
neither does a browser: the address, the transport credential and the decision
to contact somebody all belong to the API. `packages/email` on the TypeScript
side is empty for that reason and points here.

Two implementations and one protocol, and the protocol exists for the second
implementation rather than for testing. A deployment without SMTP configured
must not silently drop mail, so the stand-in *records* what it would have sent
and declares itself simulated -- which the caller is expected to surface. A mock
that quietly stands in for a provider is the failure this platform keeps finding.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol


class EmailError(RuntimeError):
    """Base for the two failures a caller has to tell apart."""


class TransientEmailError(EmailError):
    """Worth retrying: a refused connection, greylisting, a bad minute."""


class PermanentEmailError(EmailError):
    """Not worth retrying: the server will refuse this message again.

    A rejected recipient is the common case. Retrying sends the identical
    message to the identical server, so a caller that retries this is only
    slowing down the report of a problem somebody has to fix.
    """


@dataclass(frozen=True)
class Sent:
    """A message handed to a transport, and the id to look it up by."""

    message_id: str
    simulated: bool


class EmailSender(Protocol):
    """Whatever actually delivers.

    Note what is absent: any notion of "was this already sent". Nothing can be
    asked that of a mail transport, so delivery here is at-least-once and a
    caller that must not repeat a message has to arrange that itself.
    """

    @property
    def simulated(self) -> bool:
        """Whether this drops mail instead of sending it.

        The caller is expected to record this wherever the outcome is recorded.
        A run that reports success having delivered nothing must not look
        identical to one that delivered.
        """
        ...

    async def send(self, *, to: str, subject: str, body: str, tag: str) -> Sent:
        """Deliver one plain-text message.

        `tag` names the kind of message -- "welcome", "invite" -- and goes into
        the Message-ID, so a duplicate in somebody's inbox is recognisable as a
        duplicate rather than looking like a second event.
        """
        ...


@dataclass
class RecordingEmailSender:
    """Keeps messages instead of sending them.

    For local development, where a stack must run with no outbound network, and
    for tests, which need to assert that the right person was written to. It
    keeps the messages rather than discarding them for that second reason: a
    sender that dropped them would let a caller addressing the wrong recipient
    pass its tests.
    """

    sent: list[dict[str, str]] = field(default_factory=list)

    @property
    def simulated(self) -> bool:
        return True

    async def send(self, *, to: str, subject: str, body: str, tag: str) -> Sent:
        self.sent.append({"to": to, "subject": subject, "body": body, "tag": tag})
        return Sent(message_id=f"recorded-{len(self.sent)}", simulated=True)


class SmtpEmailSender:
    """Real mail, over SMTP.

    `asyncio.to_thread` around the blocking call: one short exchange a handful
    of times per request-second, and keeping it off the event loop costs a
    thread rather than a dependency.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        sender: str,
        use_tls: bool = True,
        timeout_seconds: int = 15,
    ) -> None:
        if not host:
            raise ValueError(
                "SmtpEmailSender needs a host. Construct RecordingEmailSender "
                "deliberately if mail is not configured; do not pass an empty host "
                "and hope."
            )
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender
        self._use_tls = use_tls
        self._timeout = timeout_seconds

    @property
    def simulated(self) -> bool:
        return False

    async def send(self, *, to: str, subject: str, body: str, tag: str) -> Sent:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = subject

        message_id = self._message_id(to=to, tag=tag, subject=subject)
        message["Message-ID"] = message_id
        message.set_content(body)

        try:
            await asyncio.to_thread(self._deliver, message)
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPNotSupportedError) as error:
            raise PermanentEmailError(f"The mail server refused this: {error}") from error
        except (smtplib.SMTPException, OSError) as error:
            raise TransientEmailError(f"Could not reach the mail server: {error}") from error

        return Sent(message_id=message_id, simulated=False)

    def _message_id(self, *, to: str, tag: str, subject: str) -> str:
        """Ours, not the server's.

        smtplib does not return the server's, and a delivery question later
        needs something to look up. Derived from the recipient and the kind, so
        two people receiving the same kind of message do not share an id.
        """
        domain = self._sender.rpartition("@")[2] or "koras.invalid"
        return f"<{tag}.{abs(hash((to, tag, subject)))}@{domain}>"

    def _deliver(self, message: EmailMessage) -> None:
        """The blocking half.

        TLS defaults on and is turned off only for a local trap like Mailpit,
        which has no certificate. A session carrying a password must never run
        without it, which is why the default is the safe one and the local stack
        is the thing that has to ask.
        """
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as server:
            if self._use_tls:
                server.starttls(context=ssl.create_default_context())
            if self._username and self._password:
                server.login(self._username, self._password)
            server.send_message(message)


def sender_for(
    *,
    host: str,
    port: int = 587,
    username: str | None = None,
    password: str | None = None,
    sender: str = "",
    use_tls: bool = True,
) -> EmailSender:
    """The sender a configuration asks for, real or recording.

    One place decides, so "is mail configured" is answered identically wherever
    it is asked. An absent host selects the recording sender rather than raising:
    a service that refuses to start because it cannot send mail is a service that
    cannot serve anything else either, and mail is rarely why it exists.

    The caller still has to surface `simulated`. This function chooses the
    sender; it cannot make anybody honest about which one they got.
    """
    if not host:
        return RecordingEmailSender()
    return SmtpEmailSender(
        host=host,
        port=port,
        username=username,
        password=password,
        sender=sender,
        use_tls=use_tls,
    )


__all__ = [
    "EmailError",
    "EmailSender",
    "PermanentEmailError",
    "RecordingEmailSender",
    "Sent",
    "SmtpEmailSender",
    "TransientEmailError",
    "sender_for",
]
