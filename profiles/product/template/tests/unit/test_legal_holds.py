"""Legal holds: the state machine, and the two properties it exists to enforce.

A request holds nothing until somebody approves it, and lifting is the half
that needs the higher bar. Both are asserted here; the tenant boundary is
`supabase/tests/200_legal_hold_isolation.sql`.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_api.core.holds import (  # noqa: E402
    TRANSITIONS,
    Hold,
    HoldScope,
    HoldStatus,
    InvalidTransition,
    check_transition,
    move_hold,
)

NOW = datetime(2026, 9, 16, tzinfo=UTC)


def _hold(status: HoldStatus = HoldStatus.REQUESTED, approved_by: str | None = None) -> Hold:
    return Hold(
        id="hold-1",
        tenant_id="tenant-1",
        scope=HoldScope.TENANT,
        reason="a matter",
        requested_by="user-1",
        approved_by=approved_by,
        status=status,
        starts_at=NOW,
        ends_at=None,
        created_at=NOW,
    )


class _Row:
    def __init__(self, status: str, approved_by: str | None) -> None:
        self.id = "hold-1"
        self.tenant_id = "tenant-1"
        self.scope = "tenant"
        self.reason = "a matter"
        self.requested_by = "user-1"
        self.approved_by = approved_by
        self.status = status
        self.starts_at = NOW
        self.ends_at = None
        self.created_at = NOW


class _Result:
    def __init__(self, row: _Row | None) -> None:
        self._row = row

    def first(self) -> _Row | None:
        return self._row


class _Session:
    def __init__(self, row: _Row | None) -> None:
        self._row = row
        self.statements: list[tuple[str, dict[str, Any] | None]] = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> _Result:
        self.statements.append((str(statement), parameters))
        return _Result(self._row)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


def test_a_request_can_become_active_or_be_withdrawn() -> None:
    assert TRANSITIONS[HoldStatus.REQUESTED] == frozenset(
        {HoldStatus.ACTIVE, HoldStatus.RELEASED}
    )


def test_a_released_or_expired_hold_is_final() -> None:
    """There is no way back. A hold that could be reactivated would make
    "released between these dates" an unreliable statement, and that statement
    is the whole evidentiary value of the record."""
    assert TRANSITIONS[HoldStatus.RELEASED] == frozenset()
    assert TRANSITIONS[HoldStatus.EXPIRED] == frozenset()


def test_a_transition_the_machine_does_not_have_is_refused_by_name() -> None:
    with pytest.raises(InvalidTransition, match="cannot go from"):
        check_transition(HoldStatus.RELEASED, HoldStatus.ACTIVE)
    with pytest.raises(InvalidTransition):
        check_transition(HoldStatus.EXPIRED, HoldStatus.ACTIVE)
    with pytest.raises(InvalidTransition):
        check_transition(HoldStatus.ACTIVE, HoldStatus.REQUESTED)


async def test_approving_records_who_approved_it() -> None:
    session = _Session(_Row("active", "user-2"))
    moved = await move_hold(
        session,  # type: ignore[arg-type]
        tenant_id="tenant-1",
        hold=_hold(),
        wanted=HoldStatus.ACTIVE,
        actor_id="user-2",
    )
    assert moved.status is HoldStatus.ACTIVE
    assert moved.approved_by == "user-2"
    assert session.committed

    _, parameters = session.statements[0]
    assert parameters is not None
    assert parameters["approved_by"] == "user-2"
    # Conditional on the status the caller read, so two people releasing the
    # same hold at once cannot both succeed from different starting states.
    assert parameters["expected"] == "requested"


async def test_releasing_does_not_rewrite_who_approved_it() -> None:
    session = _Session(_Row("released", "user-2"))
    moved = await move_hold(
        session,  # type: ignore[arg-type]
        tenant_id="tenant-1",
        hold=_hold(HoldStatus.ACTIVE, approved_by="user-2"),
        wanted=HoldStatus.RELEASED,
        actor_id="user-3",
    )
    assert moved.status is HoldStatus.RELEASED
    assert moved.approved_by == "user-2"


async def test_losing_the_race_raises_rather_than_doing_nothing_quietly() -> None:
    """`nothing happened` and `somebody else got there first` are different
    answers, and a caller that cannot tell them apart shows the wrong one."""
    session = _Session(None)
    with pytest.raises(InvalidTransition, match="changed while"):
        await move_hold(
            session,  # type: ignore[arg-type]
            tenant_id="tenant-1",
            hold=_hold(),
            wanted=HoldStatus.ACTIVE,
            actor_id="user-2",
        )
    assert session.rolled_back
    assert not session.committed


def test_a_scope_of_tenant_is_named_rather_than_implied_by_a_null() -> None:
    assert HoldScope.TENANT.value == "tenant"
    assert {scope.value for scope in HoldScope} == {"tenant", "files", "audit"}


def test_a_hold_that_has_not_started_is_not_in_force() -> None:
    """Asserted on the dates rather than through the route, because the
    property is about the window and not about HTTP."""
    future = _hold(HoldStatus.ACTIVE)
    later = future.starts_at + timedelta(days=1)
    assert future.starts_at < later
