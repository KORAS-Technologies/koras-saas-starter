"""A tenant's own audit history: search, filter, page.

Until now a customer's only window on their own records was the Activity
report's aggregate, which answers "how much" and never "what". This answers
"what", within one tenant, for the people entitled to ask.

Three rules, all borrowed rather than invented:

**Filters are declared and bound.** Every accepted filter is a typed query
parameter; anything else is refused; no value reaches SQL except as a bound
parameter. There is no free-text filter at all -- the same rule
`koras_reporting` enforces, and for the same reason.

**Security-classified rows need more than the permission.** `audit.view` gets a
member of the administrative roles their tenant's ordinary history. Refusals,
authorization decisions and holds are the security class, and reading those
needs an owner or an administrator: a security_admin can see that the tenant is
active without seeing every colleague who was refused something.

**404, never 403, for a row this caller may not have.** A 403 confirms the row
exists, which is the disclosure the 404 exists to prevent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from koras_audit import Classification
from koras_auth.permissions import permissions_for
from koras_platform import OrganizationRole
from pydantic import BaseModel
from sqlalchemy import text

from ..core.audit import record
from ..core.auth import AuthDep
from ..core.database import DbSession
from ..core.errors import ApiErrorCode, api_error
from ..core.tenant import TenantDep

router = APIRouter(tags=["audit"])

PERMISSION = "audit.view"

#: Reading the security class. The same two roles that may delete a file and
#: lift a hold, because all three answer "who may see what went wrong".
_MANAGERS = (OrganizationRole.OWNER, OrganizationRole.ADMIN)

#: A page. Bounded so that a caller cannot ask for the whole table, and small
#: enough that the tenant-leading index is doing the work.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

#: How far back a search may reach in one request. Not a retention limit --
#: rows older than this exist and are swept on their own schedule -- but a
#: bound on how much of the index one query walks.
MAX_RANGE_DAYS = 400


def _max_range() -> timedelta:
    return timedelta(days=MAX_RANGE_DAYS)


class AuditRow(BaseModel):
    id: str
    action: str
    actor_id: str
    target_type: str
    target_id: str
    outcome: str
    classification: str
    details: dict[str, Any]
    created_at: datetime


class AuditPage(BaseModel):
    events: list[AuditRow]
    #: The `created_at` of the last row, to pass back as `before`. Absent when
    #: the page was not full, which is how a caller knows to stop.
    cursor: datetime | None = None
    #: Which classes this caller was allowed to see, so a page that looks thin
    #: is explicable rather than mysterious.
    classifications: list[str]


def _require_permission(claims: AuthDep) -> None:
    if PERMISSION not in permissions_for(claims.roles):
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.PERMISSION_MISSING,
            "reading the audit history needs the audit view permission",
        )


def visible_classes(claims: AuthDep) -> tuple[str, ...]:
    """Which classes this caller may read.

    A pure function, so the list route and the single-row route cannot answer
    it differently -- which is the way a row becomes readable by id but not by
    listing.
    """
    ordinary = (
        Classification.ACTIVITY.value,
        Classification.AUDIT.value,
        Classification.ADMINISTRATIVE.value,
    )
    if claims.has_role(*_MANAGERS):
        return (*ordinary, Classification.SECURITY.value)
    return ordinary


_SEARCH = text(
    "select id::text as id, action, actor_id, target_type, target_id, outcome, "
    " classification, details, created_at "
    "from public.audit_events "
    "where tenant_id = cast(:tenant_id as uuid) "
    "  and classification = any(:classes) "
    "  and created_at >= :since "
    "  and created_at < :before "
    "  and (:action is null or action = :action) "
    "  and (:actor_id is null or actor_id = :actor_id) "
    "  and (:outcome is null or outcome = :outcome) "
    "  and (:target_type is null or target_type = :target_type) "
    "order by created_at desc "
    "limit :limit"
)

_ONE = text(
    "select id::text as id, action, actor_id, target_type, target_id, outcome, "
    " classification, details, created_at "
    "from public.audit_events "
    "where id = cast(:id as uuid) and tenant_id = cast(:tenant_id as uuid) "
    "  and classification = any(:classes)"
)


def _row(row: object) -> AuditRow:
    return AuditRow(
        id=row.id,  # type: ignore[attr-defined]
        action=row.action,  # type: ignore[attr-defined]
        actor_id=row.actor_id,  # type: ignore[attr-defined]
        target_type=row.target_type,  # type: ignore[attr-defined]
        target_id=row.target_id,  # type: ignore[attr-defined]
        outcome=row.outcome,  # type: ignore[attr-defined]
        classification=row.classification,  # type: ignore[attr-defined]
        details=dict(row.details or {}),  # type: ignore[attr-defined]
        created_at=row.created_at,  # type: ignore[attr-defined]
    )


@router.get("/audit", response_model=AuditPage)
async def search_audit(
    claims: AuthDep,
    tenant: TenantDep,
    session: DbSession,
    action: Annotated[str | None, Query(max_length=120)] = None,
    actor_id: Annotated[str | None, Query(max_length=200)] = None,
    outcome: Annotated[str | None, Query(pattern="^(ok|denied|failed|pending)$")] = None,
    target_type: Annotated[str | None, Query(max_length=60)] = None,
    classification: Annotated[
        str | None, Query(pattern="^(activity|audit|security|administrative)$")
    ] = None,
    since: datetime | None = None,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> AuditPage:
    """One page of this tenant's history, newest first.

    `before` is both the range's end and the cursor: pass back the previous
    page's cursor to continue. Paging by timestamp rather than by offset,
    because an offset into a table that is being written to skips rows.
    """
    _require_permission(claims)
    allowed = visible_classes(claims)

    if classification is not None:
        if classification not in allowed:
            # Asking for a class this caller cannot read is refused rather than
            # silently answered with nothing: an empty page would read as "the
            # tenant had no refusals", which is a different and wrong answer.
            raise api_error(
                status.HTTP_403_FORBIDDEN,
                ApiErrorCode.PERMISSION_MISSING,
                "reading security events needs an owner or administrator",
            )
        allowed = (classification,)

    now = datetime.now(UTC)
    end = before or now
    start = since or (end - _max_range())
    if start >= end:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ApiErrorCode.FILTER_INVALID,
            "the range starts after it ends",
        )
    if (end - start) > _max_range():
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ApiErrorCode.FILTER_INVALID,
            f"a search covers at most {MAX_RANGE_DAYS} days; narrow the range",
        )

    result = await session.execute(
        _SEARCH,
        {
            "tenant_id": tenant.id,
            "classes": list(allowed),
            "since": start,
            "before": end,
            "action": action,
            "actor_id": actor_id,
            "outcome": outcome,
            "target_type": target_type,
            "limit": limit,
        },
    )
    rows = [_row(row) for row in result.all()]

    # Reading a tenant's own history is itself an event, and an ordinary one:
    # activity, not audit. Recorded with the shape of the question and never
    # the answer.
    await record(
        session,
        tenant_id=tenant.id,
        actor_id=claims.sub,
        action="audit.searched",
        target_type="audit",
        target_id="-",
        outcome="ok",
        details={"rows": len(rows), "filtered": action is not None or actor_id is not None},
    )

    return AuditPage(
        events=rows,
        cursor=rows[-1].created_at if len(rows) == limit else None,
        classifications=list(allowed),
    )


@router.get("/audit/{event_id}", response_model=AuditRow)
async def read_audit_event(
    event_id: str, claims: AuthDep, tenant: TenantDep, session: DbSession
) -> AuditRow:
    """One row, or 404.

    404 rather than 403 for a row belonging to another tenant *and* for a row
    of a class this caller may not read, so that neither a tenancy boundary nor
    a classification boundary can be probed with a status code.
    """
    _require_permission(claims)
    try:
        row = (
            await session.execute(
                _ONE,
                {"id": event_id, "tenant_id": tenant.id, "classes": list(visible_classes(claims))},
            )
        ).first()
    except Exception:
        # A malformed uuid is a caller error, not a server one, and answering
        # 404 keeps it indistinguishable from an id that simply is not there.
        await session.rollback()
        raise api_error(
            status.HTTP_404_NOT_FOUND, ApiErrorCode.AUDIT_EVENT_NOT_FOUND, "no such event"
        ) from None
    if row is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND, ApiErrorCode.AUDIT_EVENT_NOT_FOUND, "no such event"
        )
    return _row(row)

