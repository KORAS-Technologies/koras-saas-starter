"""Restore: ask, approve, watch. Four routes and three asymmetries.

**Asking is not restoring.** A request restores nothing. It enters an approval
flow, and the list shows its state — which is the rule the design promised and
the reason a customer portal can offer a button without offering a deletion.

**`files.manage`, and no entitlement.** Audit export set the precedent and the
argument is stronger here: gating data recovery behind a plan tier means a
customer whose plan lapsed cannot get their data back, which is a worse position
to defend than not selling it. ADR 0006 question 3 is answered that way as of
2026-09-16, and adding `storage.restore` later to something that works is easy
in a way that removing a gate from something that refuses is not.

**The plan is not consulted, so an outage cannot block a recovery.** That
reverses ADR 0006 decision 7, which said restore refuses while the plan is
unresolved. The asymmetry it drew was between upload and restore, on the
grounds that an outage must not let unverified data move — but the verification
that matters here is the digest, which this checks itself and which a
platform outage cannot affect. An unreachable Control Plane stopping a customer
from recovering a deleted file is the failure mode that reasoning was trying to
avoid, pointed the other way.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, status
from koras_auth.permissions import permissions_for
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..core.audit import record
from ..core.auth import AuthDep
from ..core.database import DbSession
from ..core.errors import ApiErrorCode, api_error
from ..core.restore import (
    InvalidTransition,
    RestoreRequest,
    RestoreStatus,
    available_backup,
    get_restore,
    list_restores,
    move_restore,
    request_restore,
)
from ..core.tenant import TenantDep

router = APIRouter(tags=["restore"])

#: Managing files is the authority. Reading them is not: a member who may
#: download an object should not be able to ask for a deleted one back.
PERMISSION = "files.manage"


class RestoreAsk(BaseModel):
    file_id: str
    reason: str = Field(min_length=3, max_length=2000)
    #: False writes a new object and destroys nothing. True replaces the object
    #: that is there, and has to be confirmed again by the approver.
    overwrite: bool = False


class Approval(BaseModel):
    #: Must match the request. An approver who did not notice the flag has not
    #: approved a deletion, so they retype it rather than inherit it.
    overwrite: bool = False


class BackupRow(BaseModel):
    """One catalogue entry, as somebody choosing what to bring back sees it."""

    file_id: str
    #: The name the object had. Read from the catalogue's source key rather
    #: than from `files`, because the row this exists to restore has usually
    #: been deleted -- which is the whole point of the catalogue outliving it.
    name: str
    status: str
    size_bytes: int | None
    copied_at: datetime
    #: Whether the object is still in the product. False is the interesting
    #: case: it is gone, and this is the only way back to it.
    file_exists: bool
    #: Where a request for this object has got to, if there is one.
    request_status: str | None


class BackupList(BaseModel):
    backups: list[BackupRow]


class BackupState(BaseModel):
    """What is available to restore from, told plainly rather than as a verdict."""

    id: str
    #: `verified` is a digest somebody compared. `copied` is a copy nobody
    #: could — most often because the provider never computed one. Both are
    #: restorable; the difference belongs with the person deciding.
    status: str
    size_bytes: int | None
    has_digest: bool


class RestoreRow(BaseModel):
    id: str
    file_id: str
    reason: str
    overwrite: bool
    status: str
    requested_by: str
    approved_by: str | None
    restored_file_id: str | None
    error: str | None


class RestoreList(BaseModel):
    restores: list[RestoreRow]


def _row(request: RestoreRequest) -> RestoreRow:
    return RestoreRow(
        id=request.id,
        file_id=request.file_id,
        reason=request.reason,
        overwrite=request.overwrite,
        status=str(request.status),
        requested_by=request.requested_by,
        approved_by=request.approved_by,
        restored_file_id=request.restored_file_id,
        error=request.error,
    )


def _require_permission(claims: AuthDep) -> None:
    if PERMISSION not in permissions_for(claims.roles):
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.PERMISSION_MISSING,
            "asking for a file to be restored needs the file management permission",
        )


async def _found(session: DbSession, tenant_id: str, restore_id: str) -> RestoreRequest:
    request = await get_restore(session, tenant_id=tenant_id, restore_id=restore_id)
    if request is None:
        # 404 rather than 403 for another tenant's request, so that list and
        # URL agree and a status code does not confirm existence.
        raise api_error(
            status.HTTP_404_NOT_FOUND, ApiErrorCode.RESTORE_NOT_FOUND, "no such restore request"
        )
    return request


#: The catalogue as a person needs to read it: what has a copy, whether the
#: object is still here, and whether anybody has already asked for it.
#:
#: Without this route the feature is unusable, and the reason is worth stating.
#: `GET /files/{id}/backup` answers about an id the caller already has, and the
#: `files` row for a purged object is gone -- so the Files page cannot offer it
#: and nothing else knows it existed. The catalogue outlives the object
#: precisely so that somebody can find it afterwards; a product that stored
#: that fact and had no way to read it would have a backup nobody could use.
_CATALOGUE = text(
    "select b.file_id::text as file_id, b.source_key, b.status, b.size_bytes, b.copied_at, "
    " (f.id is not null) as file_exists, f.name as current_name, r.status as request_status "
    "from public.file_backups b "
    "left join public.files f on f.id = b.file_id "
    "left join lateral ("
    "  select status from public.restore_requests rr "
    "   where rr.file_id = b.file_id and rr.tenant_id = b.tenant_id "
    "   order by created_at desc limit 1"
    ") r on true "
    "where b.tenant_id = cast(:tenant_id as uuid) "
    "order by b.copied_at desc limit :limit"
)


@router.get("/backups", response_model=BackupList)
async def list_backups(
    claims: AuthDep, tenant: TenantDep, session: DbSession
) -> BackupList:
    """Everything this tenant has a copy of, and what state it is in."""
    _require_permission(claims)
    rows = (await session.execute(_CATALOGUE, {"tenant_id": tenant.id, "limit": 200})).all()
    return BackupList(
        backups=[
            BackupRow(
                file_id=row.file_id,
                # The current name where the object is still here, and the last
                # segment of the key where it is not. A key segment is not a
                # pretty name, and it is the only name left for a deleted file.
                name=row.current_name or row.source_key.rsplit("/", 1)[-1],
                status=row.status,
                size_bytes=row.size_bytes,
                copied_at=row.copied_at,
                file_exists=row.file_exists,
                request_status=row.request_status,
            )
            for row in rows
        ]
    )


@router.get("/restores", response_model=RestoreList)
async def list_restore_requests(
    claims: AuthDep, tenant: TenantDep, session: DbSession
) -> RestoreList:
    _require_permission(claims)
    return RestoreList(
        restores=[_row(r) for r in await list_restores(session, tenant_id=tenant.id)]
    )


@router.get("/files/{file_id}/backup", response_model=BackupState)
async def file_backup_state(
    file_id: str, claims: AuthDep, tenant: TenantDep, session: DbSession
) -> BackupState:
    """Whether this object has a copy, and what the copy is worth.

    Asked before requesting, so that a person is not proposing a restore of
    something nothing backed up — and so that "copied but never verified" is
    visible at the moment of the decision rather than after it.
    """
    _require_permission(claims)
    backup = await available_backup(session, tenant_id=tenant.id, file_id=file_id)
    if backup is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.BACKUP_NOT_FOUND,
            "no backup of that file exists to restore from",
        )
    return BackupState(
        id=backup.id,
        status=backup.status,
        size_bytes=backup.size_bytes,
        # The digest itself is not returned. It identifies the bytes, and a
        # person deciding needs to know whether one exists, not what it is.
        has_digest=backup.backup_digest is not None,
    )


@router.post("/restores", response_model=RestoreRow, status_code=status.HTTP_202_ACCEPTED)
async def ask_for_restore(
    body: RestoreAsk, claims: AuthDep, tenant: TenantDep, session: DbSession
) -> RestoreRow:
    """Ask. Nothing is restored until somebody else approves it."""
    _require_permission(claims)

    backup = await available_backup(session, tenant_id=tenant.id, file_id=body.file_id)
    if backup is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.BACKUP_NOT_FOUND,
            "no backup of that file exists to restore from",
        )

    try:
        request = await request_restore(
            session,
            tenant_id=tenant.id,
            file_id=body.file_id,
            backup_id=backup.id,
            reason=body.reason,
            overwrite=body.overwrite,
            requested_by=claims.sub,
        )
    except Exception as problem:
        # The unique index on (tenant, file) while a request is in flight. Two
        # restores racing to write the same object is the one way a
        # non-destructive restore becomes destructive.
        await session.rollback()
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiErrorCode.RESTORE_ALREADY_REQUESTED,
            "a restore of that file is already waiting to be decided",
        ) from problem

    await record(
        session,
        tenant_id=tenant.id,
        actor_id=claims.sub,
        action="storage.restore.requested",
        target_type="file",
        target_id=body.file_id,
        outcome="pending",
        # Whether it would overwrite, and whether the copy was ever verified.
        # Never the reason: a reason names a matter, and a matter usually names
        # a person, and an audit row is read by more people than a request is.
        details={"overwrite": body.overwrite, "backup": backup.status},
    )
    return _row(request)


@router.post("/restores/{restore_id}/approve", response_model=RestoreRow)
async def approve_restore(
    restore_id: str,
    body: Approval,
    claims: AuthDep,
    tenant: TenantDep,
    session: DbSession,
) -> RestoreRow:
    """Approve. The worker runs it; this route never touches a bucket."""
    _require_permission(claims)
    request = await _found(session, tenant.id, restore_id)

    if request.requested_by == claims.sub:
        await record(
            session,
            tenant_id=tenant.id,
            actor_id=claims.sub,
            action="storage.restore.refused",
            target_type="file",
            target_id=request.file_id,
            outcome="denied",
            details={"reason": "self"},
        )
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.ROLE_REQUIRED,
            "a restore is approved by someone other than the person who asked for it",
        )

    if body.overwrite != request.overwrite:
        # Retyped rather than inherited. An approver who did not notice a
        # checkbox has not approved a deletion, and this is the only place the
        # product can tell the difference.
        await record(
            session,
            tenant_id=tenant.id,
            actor_id=claims.sub,
            action="storage.restore.refused",
            target_type="file",
            target_id=request.file_id,
            outcome="denied",
            details={"reason": "overwrite_unconfirmed", "asked": request.overwrite},
        )
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiErrorCode.RESTORE_OVERWRITE_UNCONFIRMED,
            "this request would overwrite the existing object; approve it saying so"
            if request.overwrite
            else "this request does not overwrite the existing object",
        )

    moved = await _move(session, tenant.id, request, RestoreStatus.APPROVED, claims.sub)
    await record(
        session,
        tenant_id=tenant.id,
        actor_id=claims.sub,
        action="storage.restore.approved",
        target_type="file",
        target_id=request.file_id,
        outcome="ok",
        details={"overwrite": request.overwrite, "requested_by": request.requested_by},
    )
    return _row(moved)


@router.post("/restores/{restore_id}/refuse", response_model=RestoreRow)
async def refuse_restore(
    restore_id: str, claims: AuthDep, tenant: TenantDep, session: DbSession
) -> RestoreRow:
    """Refuse, and keep the row. A refused request is the one somebody asks about."""
    _require_permission(claims)
    request = await _found(session, tenant.id, restore_id)
    moved = await _move(session, tenant.id, request, RestoreStatus.REFUSED, claims.sub)
    await record(
        session,
        tenant_id=tenant.id,
        actor_id=claims.sub,
        action="storage.restore.refused",
        target_type="file",
        target_id=request.file_id,
        outcome="denied",
        details={"reason": "decision", "requested_by": request.requested_by},
    )
    return _row(moved)


async def _move(
    session: DbSession,
    tenant_id: str,
    request: RestoreRequest,
    wanted: RestoreStatus,
    actor_id: str,
) -> RestoreRequest:
    try:
        return await move_restore(
            session, tenant_id=tenant_id, request=request, wanted=wanted, actor_id=actor_id
        )
    except InvalidTransition as problem:
        raise api_error(
            status.HTTP_409_CONFLICT, ApiErrorCode.RESTORE_NOT_TRANSITIONABLE, str(problem)
        ) from problem
