"""What the outbox promises, and the ways it could quietly stop keeping it.

CAT-01 Phase 3. The exit criterion is one sentence — *a mail server refusing
connections for ten minutes loses no notification, and the delivery log says
what happened to each* — and the properties below are what make it true.

**A message is owed, not in flight.** Nothing is held in a process that can be
restarted: `dispatch` writes the row on the caller's session, so it commits or
rolls back with the thing that caused it.

**An attempt is counted on the claim.** A worker that dies mid-send must leave a
message that knows it was tried, or one that crashes its sender every time is
retried forever.

**Giving up is visible.** Five attempts and the row is `abandoned` with the
reason on it. The whole difference from the log line this replaces is that
somebody can find it afterwards.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_api.core import outbox  # noqa: E402

pytestmark = pytest.mark.asyncio


def _owed(**changes: Any) -> outbox.Owed:  # noqa: ANN401
    base: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "22222222-2222-2222-2222-222222222222",
        "kind": "ai.approval_requested",
        "recipient": "approver@example.test",
        "locale": "en",
        "subject": "Something is waiting",
        "body_text": "text",
        "body_html": "<p>html</p>",
        "attempts": 1,
    }
    base.update(changes)
    return outbox.Owed(**base)


class _Row:
    def __init__(self, **values: Any) -> None:  # noqa: ANN401
        for key, value in {**_owed().__dict__, **values}.items():
            setattr(self, key, value)


class _Result:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = rows or []

    def first(self) -> Any | None:  # noqa: ANN401 - a driver row
        return self._rows[0] if self._rows else None

    def __iter__(self) -> Iterator[Any]:
        return iter(self._rows)


class _Session:
    def __init__(self, answers: list[_Result] | None = None) -> None:
        self.statements: list[str] = []
        self.parameters: list[dict[str, Any]] = []
        self._answers = answers or []

    async def execute(self, statement: Any, parameters: Any = None) -> _Result:  # noqa: ANN401
        self.statements.append(str(statement))
        self.parameters.append(dict(parameters or {}))
        return self._answers.pop(0) if self._answers else _Result()


def _sql(session: _Session) -> str:
    return " ".join(session.statements).lower()


# ── owing a message ──────────────────────────────────────────────────────────


async def test_a_message_is_recorded_with_the_words_it_was_decided_with() -> None:
    """Stored, not re-rendered. A retry an hour later against state that has
    changed would otherwise send a different message from the one decided, and
    whoever decided it would have no way to know."""
    session = _Session([_Result([_Row()])])
    found = await outbox.enqueue(
        session,  # type: ignore[arg-type]
        tenant_id="t",
        kind="ai.approval_requested",
        recipient="a@example.test",
        locale="de",
        subject="Betreff",
        body_text="text",
        body_html="<p>html</p>",
    )
    assert found is not None
    written = session.parameters[0]
    assert written["subject"] == "Betreff"
    assert written["body_html"] == "<p>html</p>"
    assert written["locale"] == "de"


async def test_a_message_that_cannot_be_recorded_does_not_raise() -> None:
    """The caller is in the middle of the thing the customer asked for. A
    notification that could not be written down must not undo an upload."""

    class _Broken(_Session):
        async def execute(self, statement: Any, parameters: Any = None) -> _Result:  # noqa: ANN401
            raise RuntimeError("the outbox is unreachable")

    assert (
        await outbox.enqueue(
            _Broken(),  # type: ignore[arg-type]
            tenant_id="t",
            kind="ai.approval_requested",
            recipient="a@example.test",
            locale="en",
            subject="s",
            body_text="t",
            body_html="<p>h</p>",
        )
        is None
    )


# ── claiming ─────────────────────────────────────────────────────────────────


async def test_two_workers_cannot_claim_one_message() -> None:
    """`skip locked`, and it is not hypothetical: the sweep runs every minute,
    so a send that overruns its minute is two runs at once -- which without
    this sends the same mail twice to the same person."""
    session = _Session([_Result([_Row()])])
    await outbox.claim(session)  # type: ignore[arg-type]
    assert "for update skip locked" in _sql(session)


async def test_the_attempt_is_counted_on_the_claim_not_after_the_send() -> None:
    session = _Session([_Result([_Row()])])
    [claimed] = await outbox.claim(session)  # type: ignore[arg-type]
    assert "attempts = attempts + 1" in _sql(session)
    assert claimed.subject == "Something is waiting"


async def test_only_what_is_due_is_claimed() -> None:
    session = _Session([_Result([])])
    assert await outbox.claim(session) == []  # type: ignore[arg-type]
    assert "next_attempt_at <= now()" in _sql(session)


# ── recording the outcome ────────────────────────────────────────────────────


async def test_a_delivered_message_keeps_the_providers_own_id() -> None:
    """The only handle connecting this row to a line in a mail provider's log,
    which is where the answer is when a customer says nothing arrived."""
    session = _Session()
    await outbox.delivered(
        session,  # type: ignore[arg-type]
        _owed(),
        message_id="<abc@provider>",
        simulated=False,
    )
    assert session.parameters[0]["message_id"] == "<abc@provider>"
    assert "status = 'sent'" in _sql(session)


async def test_a_recorded_send_is_not_reported_as_a_delivered_one() -> None:
    """A run that reports success having delivered nothing must not look
    identical to one that delivered."""
    session = _Session()
    await outbox.delivered(session, _owed(), message_id="local", simulated=True)  # type: ignore[arg-type]
    assert session.parameters[0]["simulated"] is True


@pytest.mark.parametrize("attempt", [1, 2, 3, 4])
async def test_a_failure_backs_off_and_will_be_tried_again(attempt: int) -> None:
    session = _Session()
    again = await outbox.failed(
        session,  # type: ignore[arg-type]
        _owed(attempts=attempt),
        "SMTPConnectError: refused",
    )
    assert again is True
    written = session.parameters[0]
    assert written["status"] == "pending"
    assert written["wait"] == outbox.BACKOFF_MINUTES[min(attempt - 1, 3)]


async def test_a_message_that_has_used_its_attempts_is_abandoned_with_a_reason() -> None:
    """Terminal and **visible**, which is the whole difference from the log
    line this replaces."""
    session = _Session()
    again = await outbox.failed(
        session,  # type: ignore[arg-type]
        _owed(attempts=outbox.MAX_ATTEMPTS),
        "SMTPRecipientsRefused: no such mailbox",
    )
    assert again is False
    assert session.parameters[0]["status"] == "abandoned"
    assert session.parameters[0]["error"]


async def test_a_failure_reason_is_cut_to_something_the_column_holds() -> None:
    session = _Session()
    await outbox.failed(session, _owed(), "x" * 900)  # type: ignore[arg-type]
    assert len(session.parameters[0]["error"]) == 400


# ── the backoff, as arithmetic ───────────────────────────────────────────────


def test_the_backoff_rides_out_the_outage_this_phase_exists_for() -> None:
    """The exit criterion names ten minutes of a mail server refusing
    connections. The waits between attempts have to clear that."""
    assert sum(outbox.BACKOFF_MINUTES) >= 10
    # One try, then one wait per remaining attempt.
    assert outbox.MAX_ATTEMPTS == len(outbox.BACKOFF_MINUTES) + 1


def test_a_message_out_of_attempts_is_not_scheduled_forward() -> None:
    now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    assert outbox.next_attempt(outbox.MAX_ATTEMPTS, now=now) == now
    assert outbox.next_attempt(1, now=now) > now


def test_a_sweep_says_what_it_did() -> None:
    assert outbox.summarise([("a", True), ("b", False), ("c", True)]) == {
        "claimed": 3,
        "sent": 2,
        "failed": 1,
    }
