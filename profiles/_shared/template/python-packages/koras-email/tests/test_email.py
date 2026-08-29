"""What the sender promises, including when it sends nothing.

The interesting assertions here are about the stand-in rather than the SMTP
path: a recording sender that lied about being simulated, or dropped the
messages it recorded, would let a service report success having contacted
nobody -- which is the failure this package is shaped to prevent.
"""

from __future__ import annotations

import pytest
from koras_email import (
    PermanentEmailError,
    RecordingEmailSender,
    SmtpEmailSender,
    TransientEmailError,
    sender_for,
)

# Applied per test rather than to the module: half of these are synchronous,
# and a module-wide asyncio mark on a plain function is a warning on every run.


@pytest.mark.asyncio
async def test_the_recording_sender_says_it_is_simulated() -> None:
    """The one property a caller must surface.

    A service that reports a message sent, having used this, has to be able to
    tell that it did. Everything else here is convenience; this is the contract.
    """
    sender = RecordingEmailSender()
    result = await sender.send(to="a@b.invalid", subject="s", body="b", tag="welcome")

    assert sender.simulated is True
    assert result.simulated is True


@pytest.mark.asyncio
async def test_the_recording_sender_keeps_what_it_would_have_sent() -> None:
    """Kept, not discarded.

    A sender that dropped these would let a caller writing to the wrong address
    pass its tests, which is most of what a test of a mail path is for.
    """
    sender = RecordingEmailSender()
    await sender.send(to="owner@acme.invalid", subject="Ready", body="Hello", tag="welcome")

    assert sender.sent == [
        {"to": "owner@acme.invalid", "subject": "Ready", "body": "Hello", "tag": "welcome"}
    ]


@pytest.mark.asyncio
async def test_message_ids_differ_between_recipients() -> None:
    """So a duplicate is recognisable as one.

    Two people receiving the same kind of message must not share an id, or a
    delivery question about one is a question about both.
    """
    sender = SmtpEmailSender(host="localhost", sender="no-reply@koras.invalid")
    first = sender._message_id(to="a@acme.invalid", tag="welcome", subject="s")
    second = sender._message_id(to="b@acme.invalid", tag="welcome", subject="s")

    assert first != second


def test_an_absent_host_selects_the_recording_sender() -> None:
    """Rather than raising.

    A service that refused to start because it cannot send mail is a service
    that cannot serve anything else either, and mail is rarely why it exists.
    """
    assert sender_for(host="").simulated is True


def test_a_configured_host_selects_the_real_one() -> None:
    assert sender_for(host="smtp.example.invalid", sender="a@b.invalid").simulated is False


def test_the_real_sender_refuses_an_empty_host() -> None:
    """Constructed directly, an empty host is a mistake rather than a default.

    `sender_for` is where the fallback decision lives. Letting the SMTP sender
    accept an empty host too would give two answers to one question, and the
    quiet one would win.
    """
    with pytest.raises(ValueError, match="needs a host"):
        SmtpEmailSender(host="", sender="a@b.invalid")


def test_the_two_error_classes_are_distinguishable() -> None:
    """A caller retries one and not the other.

    Collapsing them means either retrying a rejected address forever or giving
    up on a server having a bad minute.
    """
    assert not issubclass(TransientEmailError, PermanentEmailError)
    assert not issubclass(PermanentEmailError, TransientEmailError)
