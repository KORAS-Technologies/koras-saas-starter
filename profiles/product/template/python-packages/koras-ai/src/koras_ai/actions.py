"""A proposed action and its life.

    proposed -> awaiting_approval -> approved -> executing -> completed
                                  -> rejected                -> failed
    proposed -> executing -> completed | failed          (a read, no approval)

Every transition is checked. A state machine that accepts any move is a
column that says nothing, and the point of this row is that it says, later,
exactly what happened to a model's proposal: who agreed, when, and what came
of it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from .errors import invalid_state
from .tools import Operation


class ActionStatus(StrEnum):
    PROPOSED = "proposed"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


_TRANSITIONS: dict[ActionStatus, frozenset[ActionStatus]] = {
    ActionStatus.PROPOSED: frozenset({ActionStatus.AWAITING_APPROVAL, ActionStatus.EXECUTING}),
    ActionStatus.AWAITING_APPROVAL: frozenset({ActionStatus.APPROVED, ActionStatus.REJECTED}),
    ActionStatus.APPROVED: frozenset({ActionStatus.EXECUTING}),
    ActionStatus.EXECUTING: frozenset({ActionStatus.COMPLETED, ActionStatus.FAILED}),
    ActionStatus.REJECTED: frozenset(),
    ActionStatus.COMPLETED: frozenset(),
    ActionStatus.FAILED: frozenset(),
}

#: The states a person can still act on.
OPEN = frozenset({ActionStatus.AWAITING_APPROVAL})


@dataclass(frozen=True)
class ProposedAction:
    id: str
    tenant_id: str
    conversation_id: str
    #: The assistant message that carried the proposal.
    message_id: str | None
    tool_id: str
    #: The model's call id, so the result can be handed back as a tool message.
    tool_call_id: str
    operation: Operation
    input: Mapping[str, Any]
    status: ActionStatus
    proposed_by: str
    created_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    executed_at: datetime | None = None
    result: Mapping[str, Any] | None = None
    #: A safe sentence. Never a stack, never a provider body.
    error: str | None = None

    def transition(
        self,
        to: ActionStatus,
        *,
        decided_by: str | None = None,
        decided_at: datetime | None = None,
        executed_at: datetime | None = None,
        result: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> ProposedAction:
        """The same row, one step on. Fields not named keep their value."""
        if to not in _TRANSITIONS[self.status]:
            raise invalid_state(f"an action that is {self.status.value} cannot become {to.value}")
        return replace(
            self,
            status=to,
            decided_by=decided_by if decided_by is not None else self.decided_by,
            decided_at=decided_at if decided_at is not None else self.decided_at,
            executed_at=executed_at if executed_at is not None else self.executed_at,
            result=result if result is not None else self.result,
            error=error if error is not None else self.error,
        )
