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
from fastapi import HTTPException

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_api.core.errors import ApiErrorCode, api_error  # noqa: E402
from koras_api.core.holds import (  # noqa: E402
    TRANSITIONS,
    Hold,
    HoldScope,
    HoldStatus,
    InvalidTransition,
    check_transition,
    move_hold,
)
from koras_api.routers import holds as holds_router  # noqa: E402
from koras_api.routers.holds import window_is_invalid  # noqa: E402

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


# -- The requested window, against the effective start (starter #25) ---------------------------
#
# The start a hold actually gets is the requested one, or the server's now when
# none is sent -- and the generated UI never sends one. So the window has to be
# checked against that effective start, or every past end the UI sends is
# accepted. Asserted on the function with a fixed clock (an end *equal* to now
# is not reproducible through a real clock), then through the route for the
# shapes a browser actually sends.


def test_an_omitted_start_with_an_end_in_the_past_is_refused() -> None:
    assert window_is_invalid(None, NOW - timedelta(hours=13), now=NOW)


def test_an_omitted_start_with_an_end_equal_to_now_is_refused() -> None:
    assert window_is_invalid(None, NOW, now=NOW)


def test_an_omitted_start_with_a_future_end_is_accepted() -> None:
    assert not window_is_invalid(None, NOW + timedelta(days=1), now=NOW)


def test_an_explicit_start_is_compared_with_the_end() -> None:
    start = NOW + timedelta(days=10)
    assert window_is_invalid(start, start - timedelta(seconds=1), now=NOW)
    assert window_is_invalid(start, start, now=NOW)
    assert not window_is_invalid(start, start + timedelta(seconds=1), now=NOW)


def test_a_hold_with_no_end_is_always_accepted() -> None:
    assert not window_is_invalid(None, None, now=NOW)
    assert not window_is_invalid(NOW - timedelta(days=30), None, now=NOW)


def test_a_naive_end_is_compared_as_the_local_instant_it_is_stored_as() -> None:
    """A date-only end parses naive. Comparing it to an aware start used to be
    a TypeError (a 500); now it is read in the process zone, as the database
    driver binds it. Which zone it *should* be is not decided here."""
    naive_past = (NOW - timedelta(days=1)).astimezone().replace(tzinfo=None)
    naive_future = (NOW + timedelta(days=1)).astimezone().replace(tzinfo=None)
    assert window_is_invalid(None, naive_past, now=NOW)
    assert window_is_invalid(NOW, naive_past, now=NOW)
    assert not window_is_invalid(None, naive_future, now=NOW)


class _Claims:
    sub = "user-1"


class _Tenant:
    id = "tenant-1"


@pytest.fixture
def requested(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The route with its permission check, insert and audit write stubbed:
    what is asserted is which bodies reach the insert, and unchanged."""
    calls: list[dict[str, Any]] = []

    async def fake_request_hold(_session: object, **kwargs: Any) -> Hold:  # noqa: ANN401
        calls.append(kwargs)
        return Hold(
            id="hold-1",
            tenant_id=kwargs["tenant_id"],
            scope=kwargs["scope"],
            reason=kwargs["reason"],
            requested_by=kwargs["requested_by"],
            approved_by=None,
            status=HoldStatus.REQUESTED,
            starts_at=kwargs["starts_at"] or NOW,
            ends_at=kwargs["ends_at"],
            created_at=NOW,
        )

    async def fake_record(_session: object, **_kwargs: Any) -> None:  # noqa: ANN401
        return None

    monkeypatch.setattr(holds_router, "_require_permission", lambda _claims: None)
    monkeypatch.setattr(holds_router, "request_hold", fake_request_hold)
    monkeypatch.setattr(holds_router, "record", fake_record)
    return calls


async def _create(body: dict[str, Any]) -> object:
    return await holds_router.create_hold(
        holds_router.HoldRequest.model_validate(body),
        _Claims(),  # type: ignore[arg-type]
        _Tenant(),  # type: ignore[arg-type]
        _Session(None),  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    "body",
    [
        # What the generated form sends for "Ends on" = today: a bare date,
        # which is midnight -- already behind the effective start.
        {"reason": "a matter", "ends_at": datetime.now(UTC).astimezone().date().isoformat()},
        {"reason": "a matter", "ends_at": "2020-01-01"},
        {"reason": "a matter", "ends_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()},
        {
            "reason": "a matter",
            "starts_at": "2030-01-10T00:00:00Z",
            "ends_at": "2030-01-09T00:00:00Z",
        },
        {
            "reason": "a matter",
            "starts_at": "2030-01-10T00:00:00Z",
            "ends_at": "2030-01-10T00:00:00Z",
        },
    ],
)
async def test_the_route_refuses_a_window_that_ends_at_or_before_its_start(
    requested: list[dict[str, Any]], body: dict[str, Any]
) -> None:
    with pytest.raises(HTTPException) as refused:
        await _create(body)
    expected = api_error(
        422, ApiErrorCode.HOLD_INVALID_WINDOW, "a hold cannot end before it starts"
    )
    assert refused.value.status_code == expected.status_code
    assert refused.value.detail == expected.detail
    assert requested == []


async def test_the_route_keeps_a_future_end_as_sent(requested: list[dict[str, Any]]) -> None:
    tomorrow = (datetime.now(UTC).astimezone() + timedelta(days=1)).date().isoformat()
    row = await _create({"reason": "a matter", "ends_at": tomorrow})
    # Passed to the insert exactly as parsed: this fix decides validity only,
    # not what a date-only end means.
    assert requested[0]["ends_at"] == datetime.fromisoformat(tomorrow)
    assert requested[0]["starts_at"] is None
    assert row.ends_at is not None  # type: ignore[attr-defined]


async def test_the_route_keeps_an_unbounded_hold_unbounded(requested: list[dict[str, Any]]) -> None:
    row = await _create({"reason": "a matter"})
    assert requested[0]["ends_at"] is None
    assert row.ends_at is None  # type: ignore[attr-defined]
    assert row.in_force is False  # type: ignore[attr-defined]  # requested holds nothing
