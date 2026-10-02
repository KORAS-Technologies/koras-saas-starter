"""Legal holds: request, approve, release, list.

Four routes and one asymmetry worth reading before changing any of them.

**Requesting needs `audit.legal_hold`, which a security administrator holds.
Approving and releasing need an owner or an administrator as well.** Placing a
hold keeps data, and its worst case is cost. Lifting one makes a purge possible
again, and its worst case is destroyed evidence. The bar is set by the worse
outcome, not by which verb sounds more serious.

**An approver may not be the requester, and neither may a releaser.** Borrowed
from the assistant's approval rule rather than invented here: a person who can
propose and approve alone is a person with no second pair of eyes, and the
whole point of an approval step is the second pair of eyes. Lifting carries the
same rule rather than a stricter one, because a rule needing a third distinct
person is unsatisfiable in a tenant with two administrators.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, status
from koras_auth.permissions import permissions_for
from koras_platform import OrganizationRole
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..core.audit import record
from ..core.auth import AuthDep
from ..core.database import DbSession
from ..core.errors import ApiErrorCode, api_error
from ..core.holds import (
    Hold,
    HoldScope,
    HoldStatus,
    InvalidTransition,
    get_hold,
    list_holds,
    move_hold,
    request_hold,
)
from ..core.tenant import TenantDep

router = APIRouter(tags=["holds"])

#: Approving and releasing. The same two roles the Files module trusts with
#: deletion, for the same reason: both decide whether data survives.
_MANAGERS = (OrganizationRole.OWNER, OrganizationRole.ADMIN)

PERMISSION = "audit.legal_hold"

#: The longest retention a tenant may set, in days. Ten years.
#:
#: There was no ceiling until 2026-09-16, and the consequence was worse than an
#: over-long retention: the resolved number is fed to `make_interval`, so one
#: tenant setting a few hundred thousand years made `now() - interval` overflow
#: the timestamp range, and both nightly sweeps run every class in one
#: transaction -- so that tenant would have aborted retention for every tenant
#: in the product, indefinitely, with a worker traceback as the only signal.
#: A review found it. The bound is also the storage-limitation answer: a
#: retention nobody can justify is not one a processor should offer.
MAX_RETENTION_DAYS = 3650


class HoldRequest(BaseModel):
    scope: HoldScope = HoldScope.TENANT
    reason: str = Field(min_length=1, max_length=2000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class HoldRow(BaseModel):
    id: str
    scope: str
    reason: str
    requested_by: str
    approved_by: str | None
    status: str
    starts_at: datetime
    ends_at: datetime | None
    created_at: datetime
    #: Whether this hold is actually stopping anything right now. A hold in
    #: `requested` holds nothing, and one whose window has passed holds nothing
    #: either -- neither is obvious from the status alone.
    in_force: bool


class HoldList(BaseModel):
    holds: list[HoldRow]


def _instant(moment: datetime) -> datetime:
    """A naive datetime read the way it is stored: in this process's zone.

    A date-only end ("2026-10-02") arrives naive, and the database driver binds
    a naive value as local wall time in the API process. Comparing it in that
    same zone keeps the check below about the instant that is actually stored.
    What a date-only end *should* mean -- which zone, inclusive or not -- is a
    product decision this function deliberately does not make.
    """
    return moment if moment.tzinfo is not None else moment.astimezone()


def window_is_invalid(
    starts_at: datetime | None, ends_at: datetime | None, *, now: datetime
) -> bool:
    """Whether a requested hold would end at or before it starts.

    The start is the requested `starts_at`, or `now` when it is omitted --
    the same `coalesce(:starts_at, now())` the insert uses. Comparing against
    the *effective* start rather than only a supplied one matters, because the
    generated UI never sends `starts_at`: checking only a supplied start
    accepted every past end the UI could send (starter #25). A hold with no
    end is always valid.
    """
    if ends_at is None:
        return False
    start = starts_at if starts_at is not None else now
    return _instant(ends_at) <= _instant(start)


def _row(hold: Hold, *, now: datetime | None = None) -> HoldRow:
    moment = now or datetime.now(hold.starts_at.tzinfo)
    in_force = (
        hold.status is HoldStatus.ACTIVE
        and hold.starts_at <= moment
        and (hold.ends_at is None or hold.ends_at > moment)
    )
    return HoldRow(
        id=hold.id,
        scope=str(hold.scope),
        reason=hold.reason,
        requested_by=hold.requested_by,
        approved_by=hold.approved_by,
        status=str(hold.status),
        starts_at=hold.starts_at,
        ends_at=hold.ends_at,
        created_at=hold.created_at,
        in_force=in_force,
    )


def _require_permission(claims: AuthDep) -> None:
    if PERMISSION not in permissions_for(claims.roles):
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.PERMISSION_MISSING,
            "placing or lifting a legal hold needs the audit hold permission",
        )


async def _require_manager(
    session: DbSession, claims: AuthDep, tenant_id: str, hold_id: str, attempted: str
) -> None:
    """Approving and releasing need a manager, and a refusal is recorded.

    Recorded because a refused lift is somebody trying to make a purge possible
    again, which is exactly the kind of attempt that is interesting months
    later.
    """
    if claims.has_role(*_MANAGERS):
        return
    await record(
        session,
        tenant_id=tenant_id,
        actor_id=claims.sub,
        action="hold.refused",
        target_type="hold",
        target_id=hold_id,
        outcome="denied",
        details={"attempted": attempted, "reason": "role"},
    )
    raise api_error(
        status.HTTP_403_FORBIDDEN,
        ApiErrorCode.ROLE_REQUIRED,
        f"{attempted} a legal hold needs an owner or administrator",
    )


@router.get("/holds", response_model=HoldList)
async def list_tenant_holds(
    claims: AuthDep, tenant: TenantDep, session: DbSession
) -> HoldList:
    _require_permission(claims)
    holds = await list_holds(session, tenant_id=tenant.id)
    return HoldList(holds=[_row(hold) for hold in holds])


@router.post("/holds", response_model=HoldRow, status_code=status.HTTP_201_CREATED)
async def create_hold(
    body: HoldRequest, claims: AuthDep, tenant: TenantDep, session: DbSession
) -> HoldRow:
    """Record a request. **It holds nothing until somebody approves it.**"""
    _require_permission(claims)
    if window_is_invalid(body.starts_at, body.ends_at, now=datetime.now(UTC)):
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ApiErrorCode.HOLD_INVALID_WINDOW,
            "a hold cannot end before it starts",
        )
    hold = await request_hold(
        session,
        tenant_id=tenant.id,
        scope=body.scope,
        reason=body.reason,
        requested_by=claims.sub,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
    )
    await record(
        session,
        tenant_id=tenant.id,
        actor_id=claims.sub,
        action="hold.requested",
        target_type="hold",
        target_id=hold.id,
        outcome="ok",
        # The scope and the window, never the reason: a reason names a matter,
        # and an audit row is read by more people than a hold request is.
        details={"scope": str(hold.scope), "bounded": hold.ends_at is not None},
    )
    return _row(hold)


@router.post("/holds/{hold_id}/approve", response_model=HoldRow)
async def approve_hold(
    hold_id: str, claims: AuthDep, tenant: TenantDep, session: DbSession
) -> HoldRow:
    _require_permission(claims)
    await _require_manager(session, claims, tenant.id, hold_id, "approving")
    hold = await _found(session, tenant.id, hold_id)

    if hold.requested_by == claims.sub:
        await record(
            session,
            tenant_id=tenant.id,
            actor_id=claims.sub,
            action="hold.refused",
            target_type="hold",
            target_id=hold_id,
            outcome="denied",
            details={"attempted": "approving", "reason": "self"},
        )
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.ROLE_REQUIRED,
            "a legal hold is approved by someone other than the person who requested it",
        )

    moved = await _move(session, tenant.id, hold, HoldStatus.ACTIVE, claims.sub)
    await record(
        session,
        tenant_id=tenant.id,
        actor_id=claims.sub,
        action="hold.approved",
        target_type="hold",
        target_id=hold_id,
        outcome="ok",
        details={"scope": str(moved.scope), "requested_by": moved.requested_by},
    )
    return _row(moved)


@router.post("/holds/{hold_id}/release", response_model=HoldRow)
async def release_hold(
    hold_id: str, claims: AuthDep, tenant: TenantDep, session: DbSession
) -> HoldRow:
    """Lift a hold. The dangerous half: what it covered may expire again.

    Two people, the same rule approving takes: whoever asked for the hold is
    not whoever lifts it. It is deliberately the *same* bar and not a higher
    one -- a rule needing a third distinct person would be unliftable in a
    tenant with two administrators, and a control that cannot be satisfied is
    one somebody eventually routes around at the database. The docstring here
    claimed a higher bar than any code enforced until a review looked.
    """
    _require_permission(claims)
    await _require_manager(session, claims, tenant.id, hold_id, "releasing")
    hold = await _found(session, tenant.id, hold_id)

    if hold.requested_by == claims.sub:
        await record(
            session,
            tenant_id=tenant.id,
            actor_id=claims.sub,
            action="hold.refused",
            target_type="hold",
            target_id=hold_id,
            outcome="denied",
            details={"attempted": "releasing", "reason": "self"},
        )
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.ROLE_REQUIRED,
            "a legal hold is lifted by someone other than the person who requested it",
        )

    moved = await _move(session, tenant.id, hold, HoldStatus.RELEASED, claims.sub)
    await record(
        session,
        tenant_id=tenant.id,
        actor_id=claims.sub,
        action="hold.released",
        target_type="hold",
        target_id=hold_id,
        outcome="ok",
        details={"scope": str(moved.scope), "was": str(hold.status)},
    )
    return _row(moved)


async def _found(session: DbSession, tenant_id: str, hold_id: str) -> Hold:
    hold = await get_hold(session, tenant_id=tenant_id, hold_id=hold_id)
    if hold is None:
        # 404 rather than 403 for a hold belonging to another tenant, so that
        # list and URL agree and a status code does not confirm existence.
        raise api_error(status.HTTP_404_NOT_FOUND, ApiErrorCode.HOLD_NOT_FOUND, "no such hold")
    return hold


async def _move(
    session: DbSession, tenant_id: str, hold: Hold, wanted: HoldStatus, actor_id: str
) -> Hold:
    try:
        return await move_hold(
            session, tenant_id=tenant_id, hold=hold, wanted=wanted, actor_id=actor_id
        )
    except InvalidTransition as problem:
        raise api_error(
            status.HTTP_409_CONFLICT, ApiErrorCode.HOLD_NOT_TRANSITIONABLE, str(problem)
        ) from problem


HoldsRouter = Annotated[APIRouter, router]


# -- retention overrides -------------------------------------------------------


class RetentionOverrides(BaseModel):
    """What this tenant keeps, where it wants longer than the platform floor.

    Days, by kind. A kind absent from the map takes the floor. A value shorter
    than the floor is accepted into the row and loses at resolution, because
    `retention_days_for` takes whichever is greater -- so a customer cannot
    shorten retention by writing a smaller number, and does not get an error
    for trying something the platform simply overrides.
    """

    audit_activity: int | None = Field(default=None, ge=1, le=MAX_RETENTION_DAYS)
    audit: int | None = Field(default=None, ge=1, le=MAX_RETENTION_DAYS)
    audit_security: int | None = Field(default=None, ge=1, le=MAX_RETENTION_DAYS)
    storage_standard: int | None = Field(default=None, ge=1, le=MAX_RETENTION_DAYS)
    storage_sensitive: int | None = Field(default=None, ge=1, le=MAX_RETENTION_DAYS)
    storage_restricted: int | None = Field(default=None, ge=1, le=MAX_RETENTION_DAYS)


_READ_RETENTION = text(
    "select coalesce(retention_overrides, cast('{}' as jsonb)) as overrides "
    "from public.tenant_settings where tenant_id = cast(:tenant_id as uuid)"
)

_WRITE_RETENTION = text(
    "insert into public.tenant_settings (tenant_id, retention_overrides) "
    "values (cast(:tenant_id as uuid), cast(:overrides as jsonb)) "
    "on conflict (tenant_id) do update set retention_overrides = cast(:overrides as jsonb)"
)


@router.get("/settings/retention", response_model=RetentionOverrides)
async def read_retention(
    claims: AuthDep, tenant: TenantDep, session: DbSession
) -> RetentionOverrides:
    _require_permission(claims)
    row = (await session.execute(_READ_RETENTION, {"tenant_id": tenant.id})).first()
    stored = dict(row.overrides) if row is not None and row.overrides else {}
    return RetentionOverrides(**stored)


@router.put("/settings/retention", response_model=RetentionOverrides)
async def write_retention(
    body: RetentionOverrides, claims: AuthDep, tenant: TenantDep, session: DbSession
) -> RetentionOverrides:
    """Change this tenant's retention. Only the kinds the caller names.

    Changing what a customer keeps is an administrative act, so it needs the
    same authority as placing a hold and is recorded as an administrative
    event. The numbers go into the record; a retention policy is not a secret
    and the point of the record is to be able to say when it changed.

    **A kind the caller did not mention keeps its value.** This replaced the
    whole map until a security review found it on 2026-09-16: a caller sending
    `{"audit": 400}` cleared a tenant's `audit_security` of 2555 back to the
    platform floor of 1095, and everything that class covered became deletable
    on the next sweep. Nothing in the request said so and nothing in the record
    showed it, because the audit row carried only the new map -- a shortening
    from seven years to the floor was indistinguishable from setting that value
    for the first time.

    Removing one is still possible and is now explicit: send the kind as null.
    `model_fields_set` is what separates "not mentioned" from "set to nothing",
    which `model_dump()` alone cannot.
    """
    _require_permission(claims)
    await _require_manager(session, claims, tenant.id, "-", "changing retention for")

    row = (await session.execute(_READ_RETENTION, {"tenant_id": tenant.id})).first()
    # Read the same way `read_retention` above reads it, so the two cannot
    # disagree about what an empty map looks like.
    before: dict[str, int] = dict(row.overrides) if row is not None and row.overrides else {}
    overrides: dict[str, int] = dict(before)

    named = body.model_dump()
    for key in body.model_fields_set:
        value = named.get(key)
        if value is None:
            overrides.pop(key, None)
        else:
            overrides[key] = int(value)

    await session.execute(
        _WRITE_RETENTION, {"tenant_id": tenant.id, "overrides": json.dumps(overrides)}
    )
    await session.commit()

    await record(
        session,
        tenant_id=tenant.id,
        actor_id=claims.sub,
        action="retention.changed",
        target_type="tenant",
        target_id=tenant.id,
        outcome="ok",
        # Both maps. A shortening is only visible as a change if the record
        # says what it changed from, and this is the one event in the product
        # whose whole purpose is to make a retention change legible later.
        details={
            **{f"now_{key}": int(value) for key, value in overrides.items()},
            **{f"was_{key}": int(value) for key, value in before.items()},
        },
    )
    return RetentionOverrides(**overrides)
