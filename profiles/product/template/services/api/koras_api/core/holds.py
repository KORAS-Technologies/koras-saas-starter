"""Legal holds: the state machine, and who may move it.

A hold is a reason to stop retention. Everything here exists to make two
properties true:

**A request holds nothing.** A hold takes effect when somebody approves it, not
when somebody asks. A request that froze data on arrival would be a denial of
service with a legal-sounding name, available to anyone who could reach the
route.

**Lifting is the dangerous half, not placing.** Placing a hold keeps data and
the worst case is cost. Lifting makes a purge possible again and the worst case
is destroyed evidence. So lifting carries the higher bar, and both are recorded.

The same asymmetry the assistant applies to destructive tools, for the same
reason, and the approval rule is borrowed rather than reinvented: an approver
must be somebody who could have performed the action themselves.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class HoldScope(StrEnum):
    """What a hold reaches. Mirrors the check constraint on `legal_holds.scope`."""

    TENANT = "tenant"
    FILES = "files"
    AUDIT = "audit"


class HoldStatus(StrEnum):
    REQUESTED = "requested"
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


#: The only transitions that exist. Anything else is refused by name rather
#: than by an `if` somewhere in a route, so a new state cannot quietly acquire
#: an edge nobody decided on.
TRANSITIONS: dict[HoldStatus, frozenset[HoldStatus]] = {
    HoldStatus.REQUESTED: frozenset({HoldStatus.ACTIVE, HoldStatus.RELEASED}),
    HoldStatus.ACTIVE: frozenset({HoldStatus.RELEASED, HoldStatus.EXPIRED}),
    HoldStatus.RELEASED: frozenset(),
    HoldStatus.EXPIRED: frozenset(),
}


class InvalidTransition(Exception):
    """A move the state machine does not have. Never a 500: the route answers 409."""


def check_transition(current: HoldStatus, wanted: HoldStatus) -> None:
    if wanted not in TRANSITIONS[current]:
        raise InvalidTransition(f"a hold cannot go from {current} to {wanted}")


@dataclass(frozen=True)
class Hold:
    id: str
    tenant_id: str
    scope: HoldScope
    reason: str
    requested_by: str
    approved_by: str | None
    status: HoldStatus
    starts_at: datetime
    ends_at: datetime | None
    created_at: datetime


_INSERT = text(
    "insert into public.legal_holds "
    " (tenant_id, scope, reason, requested_by, starts_at, ends_at) "
    "values (cast(:tenant_id as uuid), :scope, :reason, :requested_by, "
    " coalesce(:starts_at, now()), :ends_at) "
    "returning id::text as id, tenant_id::text as tenant_id, scope, reason, requested_by, "
    " approved_by, status, starts_at, ends_at, created_at"
)

_SELECT = text(
    "select id::text as id, tenant_id::text as tenant_id, scope, reason, requested_by, "
    " approved_by, status, starts_at, ends_at, created_at "
    "from public.legal_holds where tenant_id = cast(:tenant_id as uuid) "
    "order by created_at desc limit :limit"
)

_ONE = text(
    "select id::text as id, tenant_id::text as tenant_id, scope, reason, requested_by, "
    " approved_by, status, starts_at, ends_at, created_at "
    "from public.legal_holds "
    "where id = cast(:id as uuid) and tenant_id = cast(:tenant_id as uuid)"
)

_TRANSITION = text(
    "update public.legal_holds set status = :status, approved_by = :approved_by "
    "where id = cast(:id as uuid) and tenant_id = cast(:tenant_id as uuid) and status = :expected "
    "returning id::text as id, tenant_id::text as tenant_id, scope, reason, requested_by, "
    " approved_by, status, starts_at, ends_at, created_at"
)


def _hold(row: object) -> Hold:
    return Hold(
        id=row.id,  # type: ignore[attr-defined]
        tenant_id=row.tenant_id,  # type: ignore[attr-defined]
        scope=HoldScope(row.scope),  # type: ignore[attr-defined]
        reason=row.reason,  # type: ignore[attr-defined]
        requested_by=row.requested_by,  # type: ignore[attr-defined]
        approved_by=row.approved_by,  # type: ignore[attr-defined]
        status=HoldStatus(row.status),  # type: ignore[attr-defined]
        starts_at=row.starts_at,  # type: ignore[attr-defined]
        ends_at=row.ends_at,  # type: ignore[attr-defined]
        created_at=row.created_at,  # type: ignore[attr-defined]
    )


async def request_hold(
    session: AsyncSession,
    *,
    tenant_id: str,
    scope: HoldScope,
    reason: str,
    requested_by: str,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> Hold:
    """Record a request. It holds nothing until it is approved."""
    result = await session.execute(
        _INSERT,
        {
            "tenant_id": tenant_id,
            "scope": str(scope),
            "reason": reason,
            "requested_by": requested_by,
            "starts_at": starts_at,
            "ends_at": ends_at,
        },
    )
    await session.commit()
    return _hold(result.one())


async def list_holds(session: AsyncSession, *, tenant_id: str, limit: int = 100) -> list[Hold]:
    result = await session.execute(_SELECT, {"tenant_id": tenant_id, "limit": limit})
    return [_hold(row) for row in result.all()]


async def get_hold(session: AsyncSession, *, tenant_id: str, hold_id: str) -> Hold | None:
    row = (await session.execute(_ONE, {"id": hold_id, "tenant_id": tenant_id})).first()
    return _hold(row) if row is not None else None


async def move_hold(
    session: AsyncSession,
    *,
    tenant_id: str,
    hold: Hold,
    wanted: HoldStatus,
    actor_id: str,
) -> Hold:
    """Move a hold, refusing a transition the machine does not have.

    The update is conditional on the status the caller read, so two people
    releasing the same hold at once do not both succeed against different
    starting states. A lost race raises `InvalidTransition` rather than
    silently doing nothing, because "nothing happened" and "somebody else got
    there first" are different answers.
    """
    check_transition(hold.status, wanted)
    approved_by = actor_id if wanted is HoldStatus.ACTIVE else hold.approved_by
    result = await session.execute(
        _TRANSITION,
        {
            "id": hold.id,
            "tenant_id": tenant_id,
            "status": str(wanted),
            "expected": str(hold.status),
            "approved_by": approved_by,
        },
    )
    row = result.first()
    if row is None:
        await session.rollback()
        raise InvalidTransition("the hold changed while this request was deciding")
    await session.commit()
    return _hold(row)
