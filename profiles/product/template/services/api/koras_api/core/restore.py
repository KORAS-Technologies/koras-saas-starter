"""Restore: the state machine, and the rule that two people decide.

Its own machine rather than the assistant's, and the reason is structural. ADR
0006 decision 6 said restore would reuse the AI foundation's action state
machine; `ai_actions` arrives with the `ai` capability, which is off by default,
so a storage safety operation would have been unavailable in most products
because they did not buy an assistant. `core/holds.py` faced the same choice and
answered it the same way: borrow the rule, not the machinery.

The rule, restated because it is the good part: **an approver must be somebody
other than the requester.** A person who can propose and approve alone is a
person with no second pair of eyes, and the whole point of an approval step is
the second pair of eyes.

**Overwriting is asked for twice.** A restore writes a new object by default and
destroys nothing. Overwriting an existing one is the only way this loses
anything, so it is named on the request and confirmed again on the approval --
an approver who did not notice a checkbox has not approved a deletion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class RestoreStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    RESTORING = "restoring"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUSED = "refused"


#: What may follow what. `restoring` is reachable only from `approved`, and the
#: worker is the only thing that enters it -- a route cannot start a restore,
#: which is what keeps "approved" and "happening" distinguishable in the record.
#:
#: `failed` leads nowhere. A restore that failed is asked for again as a new
#: request, so the history keeps both the attempt and the retry rather than
#: overwriting the first with the second.
TRANSITIONS: dict[RestoreStatus, frozenset[RestoreStatus]] = {
    RestoreStatus.REQUESTED: frozenset({RestoreStatus.APPROVED, RestoreStatus.REFUSED}),
    RestoreStatus.APPROVED: frozenset({RestoreStatus.RESTORING, RestoreStatus.REFUSED}),
    RestoreStatus.RESTORING: frozenset({RestoreStatus.COMPLETED, RestoreStatus.FAILED}),
    RestoreStatus.COMPLETED: frozenset(),
    RestoreStatus.FAILED: frozenset(),
    RestoreStatus.REFUSED: frozenset(),
}


class InvalidTransition(Exception):
    """A move the machine does not have."""


def check_transition(current: RestoreStatus, wanted: RestoreStatus) -> None:
    if wanted not in TRANSITIONS[current]:
        raise InvalidTransition(f"a restore cannot go from {current} to {wanted}")


@dataclass(frozen=True)
class RestoreRequest:
    id: str
    tenant_id: str
    file_id: str
    backup_id: str
    reason: str
    overwrite: bool
    requested_by: str
    approved_by: str | None
    restored_file_id: str | None
    error: str | None
    status: RestoreStatus
    created_at: datetime
    approved_at: datetime | None
    finished_at: datetime | None


# Spelled out in each statement rather than interpolated from a constant.
# An f-string building SQL is a string-built query however constant the parts
# are, and the linter is right not to distinguish -- the next hand to touch it
# might interpolate something that came from a request.
_INSERT = text(
    "insert into public.restore_requests "
    " (tenant_id, file_id, backup_id, reason, overwrite, requested_by) "
    "values (cast(:tenant_id as uuid), cast(:file_id as uuid), cast(:backup_id as uuid), "
    " :reason, :overwrite, :requested_by) "
    "returning id::text as id, tenant_id::text as tenant_id, file_id::text as file_id, "
    "backup_id::text as backup_id, reason, overwrite, requested_by, approved_by, "
    "restored_file_id::text as restored_file_id, error, status, created_at, "
    "approved_at, finished_at "
)

_LIST = text(
    "select id::text as id, tenant_id::text as tenant_id, file_id::text as file_id, "
    "backup_id::text as backup_id, reason, overwrite, requested_by, approved_by, "
    "restored_file_id::text as restored_file_id, error, status, created_at, "
    "approved_at, finished_at "
    "from public.restore_requests "
    "where tenant_id = cast(:tenant_id as uuid) order by created_at desc limit :limit"
)

_ONE = text(
    "select id::text as id, tenant_id::text as tenant_id, file_id::text as file_id, "
    "backup_id::text as backup_id, reason, overwrite, requested_by, approved_by, "
    "restored_file_id::text as restored_file_id, error, status, created_at, "
    "approved_at, finished_at "
    "from public.restore_requests "
    "where id = cast(:id as uuid) and tenant_id = cast(:tenant_id as uuid)"
)

#: Conditional on the status the caller read, so two people approving the same
#: request at once do not both succeed against different starting states.
_TRANSITION = text(
    "update public.restore_requests set status = :status, "
    " approved_by = coalesce(:approved_by, approved_by), "
    " approved_at = case when :status = 'approved' then now() else approved_at end "
    "where id = cast(:id as uuid) and tenant_id = cast(:tenant_id as uuid) "
    "  and status = :expected "
    "returning id::text as id, tenant_id::text as tenant_id, file_id::text as file_id, "
    "backup_id::text as backup_id, reason, overwrite, requested_by, approved_by, "
    "restored_file_id::text as restored_file_id, error, status, created_at, "
    "approved_at, finished_at "
)

#: The backup this request would read from. `verified` is a digest somebody
#: compared; `copied` is a copy nobody could. Both are restorable -- refusing an
#: unverifiable copy would mean refusing the only copy of an object whose
#: provider never computed a digest -- and the difference is carried to the
#: person deciding rather than hidden from them.
_BACKUP = text(
    "select id::text as id, status, backup_key, backup_digest, size_bytes "
    "from public.file_backups "
    "where tenant_id = cast(:tenant_id as uuid) and file_id = cast(:file_id as uuid) "
    "order by copied_at desc limit 1"
)


def _request(row: object) -> RestoreRequest:
    return RestoreRequest(
        id=row.id,  # type: ignore[attr-defined]
        tenant_id=row.tenant_id,  # type: ignore[attr-defined]
        file_id=row.file_id,  # type: ignore[attr-defined]
        backup_id=row.backup_id,  # type: ignore[attr-defined]
        reason=row.reason,  # type: ignore[attr-defined]
        overwrite=row.overwrite,  # type: ignore[attr-defined]
        requested_by=row.requested_by,  # type: ignore[attr-defined]
        approved_by=row.approved_by,  # type: ignore[attr-defined]
        restored_file_id=row.restored_file_id,  # type: ignore[attr-defined]
        error=row.error,  # type: ignore[attr-defined]
        status=RestoreStatus(row.status),  # type: ignore[attr-defined]
        created_at=row.created_at,  # type: ignore[attr-defined]
        approved_at=row.approved_at,  # type: ignore[attr-defined]
        finished_at=row.finished_at,  # type: ignore[attr-defined]
    )


@dataclass(frozen=True)
class AvailableBackup:
    id: str
    status: str
    backup_key: str
    backup_digest: str | None
    size_bytes: int | None


async def available_backup(
    session: AsyncSession, *, tenant_id: str, file_id: str
) -> AvailableBackup | None:
    """The most recent copy of one object, or None where there is none."""
    row = (await session.execute(_BACKUP, {"tenant_id": tenant_id, "file_id": file_id})).first()
    if row is None:
        return None
    return AvailableBackup(
        id=row.id,
        status=row.status,
        backup_key=row.backup_key,
        backup_digest=row.backup_digest,
        size_bytes=row.size_bytes,
    )


async def request_restore(
    session: AsyncSession,
    *,
    tenant_id: str,
    file_id: str,
    backup_id: str,
    reason: str,
    overwrite: bool,
    requested_by: str,
) -> RestoreRequest:
    """Record the ask. It restores nothing until somebody else approves it."""
    row = (
        await session.execute(
            _INSERT,
            {
                "tenant_id": tenant_id,
                "file_id": file_id,
                "backup_id": backup_id,
                "reason": reason.strip(),
                "overwrite": overwrite,
                "requested_by": requested_by,
            },
        )
    ).one()
    await session.commit()
    return _request(row)


async def list_restores(
    session: AsyncSession, *, tenant_id: str, limit: int = 100
) -> list[RestoreRequest]:
    rows = (await session.execute(_LIST, {"tenant_id": tenant_id, "limit": limit})).all()
    return [_request(row) for row in rows]


async def get_restore(
    session: AsyncSession, *, tenant_id: str, restore_id: str
) -> RestoreRequest | None:
    row = (await session.execute(_ONE, {"id": restore_id, "tenant_id": tenant_id})).first()
    return _request(row) if row is not None else None


async def move_restore(
    session: AsyncSession,
    *,
    tenant_id: str,
    request: RestoreRequest,
    wanted: RestoreStatus,
    actor_id: str | None = None,
) -> RestoreRequest:
    """Move a request, refusing a transition the machine does not have.

    A lost race raises rather than silently doing nothing: "nothing happened"
    and "somebody else got there first" are different answers, and only one of
    them means the caller should look again.
    """
    check_transition(request.status, wanted)
    approver = actor_id if wanted is RestoreStatus.APPROVED else None
    result = await session.execute(
        _TRANSITION,
        {
            "id": request.id,
            "tenant_id": tenant_id,
            "status": str(wanted),
            "expected": str(request.status),
            "approved_by": approver,
        },
    )
    row = result.first()
    if row is None:
        await session.rollback()
        raise InvalidTransition("the request changed while this one was deciding")
    await session.commit()
    return _request(row)
