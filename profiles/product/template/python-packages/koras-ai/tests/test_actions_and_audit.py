"""The action state machine, the usage month, and what an audit event refuses."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from koras_ai import ActionStatus, AIError, ErrorCode, Operation, ProposedAction, month_start
from koras_audit import AuditEvent, LoggingAuditSink


def action(status: ActionStatus) -> ProposedAction:
    return ProposedAction(
        id="a1",
        tenant_id="t",
        conversation_id="c",
        message_id="m",
        tool_id="files.rename",
        tool_call_id="call",
        operation=Operation.WRITE,
        input={"file_id": "f"},
        status=status,
        proposed_by="u",
        created_at=datetime.now(UTC),
    )


def test_the_happy_paths_are_the_only_paths() -> None:
    waiting = action(ActionStatus.PROPOSED).transition(ActionStatus.AWAITING_APPROVAL)
    approved = waiting.transition(ActionStatus.APPROVED, decided_by="boss")
    done = approved.transition(ActionStatus.EXECUTING).transition(ActionStatus.COMPLETED)
    assert done.status is ActionStatus.COMPLETED and done.decided_by == "boss"
    read = action(ActionStatus.PROPOSED).transition(ActionStatus.EXECUTING)
    assert read.transition(ActionStatus.FAILED, error="x").error == "x"


@pytest.mark.parametrize(
    ("start", "to"),
    [
        (ActionStatus.PROPOSED, ActionStatus.COMPLETED),
        (ActionStatus.AWAITING_APPROVAL, ActionStatus.EXECUTING),
        (ActionStatus.REJECTED, ActionStatus.APPROVED),
        (ActionStatus.COMPLETED, ActionStatus.EXECUTING),
        (ActionStatus.APPROVED, ActionStatus.REJECTED),
    ],
)
def test_a_skipped_or_reversed_step_is_refused(start: ActionStatus, to: ActionStatus) -> None:
    with pytest.raises(AIError) as refused:
        action(start).transition(to)
    assert refused.value.code is ErrorCode.INVALID_STATE


def test_the_month_starts_on_the_first_in_utc() -> None:
    start = month_start(datetime(2026, 9, 13, 14, 30, tzinfo=UTC))
    assert start == datetime(2026, 9, 1, tzinfo=UTC)


def test_an_audit_event_refuses_a_detail_that_looks_like_a_secret() -> None:
    with pytest.raises(ValueError, match="secret"):
        AuditEvent(
            action="ai.tool.proposed",
            actor_id="u",
            tenant_id="t",
            target_type="tool",
            target_id="files.list",
            outcome="ok",
            details={"api_key": "sk-x"},
        )


def test_the_logging_sink_writes_one_structured_line(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="koras.audit")
    LoggingAuditSink().emit(
        AuditEvent(
            action="ai.action.approved",
            actor_id="u",
            tenant_id="t",
            target_type="action",
            target_id="a1",
            outcome="ok",
            details={"tool": "files.rename"},
        )
    )
    assert len(caplog.records) == 1
    assert '"action": "ai.action.approved"' in caplog.records[0].getMessage()
    assert '"tenant_id": "t"' in caplog.records[0].getMessage()
