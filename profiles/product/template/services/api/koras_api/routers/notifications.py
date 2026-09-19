"""A person's own feed: what they have been told, and what they have read.

**No permission on any route here, and that is the design rather than an
omission.** Every route answers for the caller's own tenant and the caller's
own subject, and none of them takes a parameter naming either — the same
position `/me/settings` and `/settings/effective` already hold. What protects a
feed is the policy keyed to the verified subject, not a permission string: a
member without `settings.read` still has notifications, and a permission here
would mean the bell was a premium feature.

**There is no route that writes one.** A notification is produced by the thing
that happened — an upload, an approval, a delivery — on the server, inside the
transaction that caused it. A create route would let any signed-in person put
any message in a colleague's feed under the product's own branding, which is a
phishing vector with a REST interface.

**The unread count is its own route.** The shell asks for it on every dashboard
load and wants a number, not a page of rows; separating them keeps the common
case one index scan.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, status
from pydantic import BaseModel

from ..core.database import DbSession
from ..core.errors import ApiErrorCode, api_error
from ..core.notifications import (
    MAX_PAGE,
    PAGE,
    dismiss,
    mark_all_read,
    mark_read,
    recent,
    unread_count,
)
from ..core.tenant import TenantDep, require_subject

router = APIRouter(tags=["notifications"])


class NotificationView(BaseModel):
    id: str
    kind: str
    title: str
    body: str
    url: str
    severity: str
    created_at: datetime
    read_at: datetime | None


class NotificationList(BaseModel):
    notifications: list[NotificationView]
    unread: int


class UnreadCount(BaseModel):
    unread: int


class Marked(BaseModel):
    marked: int


@router.get("/notifications", response_model=NotificationList)
async def list_notifications(
    tenant: TenantDep,
    session: DbSession,
    limit: int = Query(default=PAGE, ge=1, le=MAX_PAGE),
    unread: bool = Query(default=False),
) -> NotificationList:
    """This person's feed, newest first, with the unread count beside it.

    The count comes back with the list because the drawer shows both and a
    second round trip for a number the same request could answer is a round
    trip. `require_subject` is called for its refusal: a caller with a tenant
    and no subject — the worker, a platform collector — has no feed, and
    answering it an empty list would read as "you have nothing" rather than
    "you are not a person".
    """
    require_subject(tenant)
    return NotificationList(
        notifications=[
            NotificationView(
                id=row.id,
                kind=row.kind,
                title=row.title,
                body=row.body,
                url=row.url,
                severity=row.severity,
                created_at=row.created_at,
                read_at=row.read_at,
            )
            for row in await recent(session, limit=limit, unread_only=unread)
        ],
        unread=await unread_count(session),
    )


@router.get("/notifications/unread-count", response_model=UnreadCount)
async def count_unread(tenant: TenantDep, session: DbSession) -> UnreadCount:
    """How many this person has not read.

    Registered before the `{notification_id}` routes below, because a router
    reads a static segment as an id if the id route was registered first —
    `/reports/exports` and `/audit/exports` are both here for the same reason.
    """
    require_subject(tenant)
    return UnreadCount(unread=await unread_count(session))


@router.post("/notifications/read-all", response_model=Marked)
async def read_all(tenant: TenantDep, session: DbSession) -> Marked:
    """Mark everything unread as read. Answers how many it changed."""
    require_subject(tenant)
    marked = await mark_all_read(session)
    await session.commit()
    return Marked(marked=marked)


@router.post("/notifications/{notification_id}/read", response_model=Marked)
async def read_one(
    notification_id: str, tenant: TenantDep, session: DbSession
) -> Marked:
    """Mark one read.

    **404 covers three cases and tells them apart for nobody**: the row does
    not exist, it belongs to somebody else, or it was already read. The first
    two are indistinguishable by design — a caller who could tell them apart
    could enumerate a colleague's notification ids — and the third answers 404
    rather than 200 so that a client is not told it changed something it did
    not.
    """
    require_subject(tenant)
    if not await mark_read(session, notification_id):
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.NOTIFICATION_NOT_FOUND,
            "no unread notification of yours has that id",
        )
    await session.commit()
    return Marked(marked=1)


@router.delete("/notifications/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_one(
    notification_id: str, tenant: TenantDep, session: DbSession
) -> None:
    """Remove one from this person's feed.

    204 whether or not a row was there, which is what `DELETE /me/settings/{key}`
    already does: a dismissal is a statement about what the caller wants to see
    next, and repeating it is not an error.
    """
    require_subject(tenant)
    await dismiss(session, notification_id)
    await session.commit()
