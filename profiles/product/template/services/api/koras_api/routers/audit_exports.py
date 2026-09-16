"""Audit exports: ask, wait, download, expire.

An export is the moment audit records leave the product, and every decision
here follows from that one fact.

**Exporting is its own authority.** `audit.view` shows a page inside the
product; `audit.export` makes a copy that leaves it. Owners and administrators
carry the second; a security administrator who may read the history may not
take it away.

**An unresolved plan refuses.** Search continues during a platform outage,
because an outage should not stop a customer reading their own history. Export
does not, because an outage is not a reason to let unverified data move. The
same asymmetry storage draws between uploading and restoring, and the same rule
reporting applies to its own exports.

**Always 202.** The row exists before the artifact does, so a request that dies
half way is a `pending` row somebody can find rather than a request that
vanished. One shape whether the result took a second or a minute.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, status
from koras_audit import Outcome
from koras_auth.permissions import permissions_for
from koras_storage import Category, object_key
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit import record
from ..core.audit_export import DEFAULT_EXPIRY_DAYS, MEDIA_TYPES, filename, render
from ..core.auth import AuthDep
from ..core.database import DbSession, tenant_session
from ..core.errors import ApiErrorCode, api_error
from ..core.storage import StorageDep, TenantStorage
from ..core.tenant import TenantDep
from .audit import (
    EXPORT_PERMISSION,
    MAX_RANGE_DAYS,
    SEARCH_STATEMENT,
    max_range,
    require_view,
    visible_classes,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["audit"])

#: A signed download lasts five minutes, as every other download here does.
DOWNLOAD_SECONDS = 5 * 60

#: The most rows one export may contain. A ceiling rather than a page: an
#: export is a file somebody keeps, so it either covers the range asked for or
#: is refused, never silently truncated -- which is why a range wider than this
#: allows is narrowed by the caller rather than trimmed by the server.
EXPORT_ROW_CEILING = 200_000


class ExportRequest(BaseModel):
    format: str = "csv"
    action: str | None = None
    actor_id: str | None = None
    outcome: str | None = None
    classification: str | None = None
    since: datetime | None = None
    before: datetime | None = None


class ExportRow(BaseModel):
    id: str
    format: str
    status: str
    rows_exported: int
    size_bytes: int | None
    error: str | None
    expires_at: datetime | None
    created_at: datetime
    ready_at: datetime | None


class ExportList(BaseModel):
    exports: list[ExportRow]


class DownloadTicket(BaseModel):
    url: str
    expires_in: int


_INSERT = text(
    "insert into public.audit_exports (tenant_id, requested_by, format, filters, expires_at) "
    "values (cast(:tenant_id as uuid), :requested_by, :format, cast(:filters as jsonb), :expires) "
    "returning id::text as id, format, status, rows_exported, size_bytes, error, "
    " expires_at, created_at, ready_at"
)
_READY = text(
    "update public.audit_exports set status = 'ready', storage_key = :key, "
    " size_bytes = :size, rows_exported = :rows, ready_at = now() "
    "where id = cast(:id as uuid)"
)
_FAILED = text(
    "update public.audit_exports set status = 'failed', error = :error where id = cast(:id as uuid)"
)
_LIST = text(
    "select id::text as id, format, status, rows_exported, size_bytes, error, "
    " expires_at, created_at, ready_at "
    "from public.audit_exports where tenant_id = cast(:tenant_id as uuid) "
    "order by created_at desc limit 50"
)
_ONE = text(
    "select id::text as id, format, status, storage_key, expires_at "
    "from public.audit_exports "
    "where id = cast(:id as uuid) and tenant_id = cast(:tenant_id as uuid)"
)
_EXPIRED = text(
    "select id::text as id, storage_key from public.audit_exports "
    "where tenant_id = cast(:tenant_id as uuid) and status = 'ready' "
    "  and storage_key is not null and expires_at is not null and expires_at < now()"
)
_DELETE = text("delete from public.audit_exports where id = cast(:id as uuid)")


def _export_row(row: object) -> ExportRow:
    return ExportRow(
        id=row.id,  # type: ignore[attr-defined]
        format=row.format,  # type: ignore[attr-defined]
        status=row.status,  # type: ignore[attr-defined]
        rows_exported=row.rows_exported,  # type: ignore[attr-defined]
        size_bytes=row.size_bytes,  # type: ignore[attr-defined]
        error=row.error,  # type: ignore[attr-defined]
        expires_at=row.expires_at,  # type: ignore[attr-defined]
        created_at=row.created_at,  # type: ignore[attr-defined]
        ready_at=row.ready_at,  # type: ignore[attr-defined]
    )


def require_export(claims: AuthDep, storage: StorageDep) -> None:
    """Permission, then plan, in that order."""
    if EXPORT_PERMISSION not in permissions_for(claims.roles):
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.PERMISSION_MISSING,
            "exporting the audit history needs the audit export permission",
        )
    if not storage.grant.resolved:
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.STORAGE_UNAVAILABLE,
            "the plan could not be read, and an export is refused while it cannot",
        )


@router.get("/audit/exports", response_model=ExportList)
async def list_audit_exports(
    claims: AuthDep, tenant: TenantDep, session: DbSession, storage: StorageDep
) -> ExportList:
    """This tenant's exports, retiring anything expired on the way past.

    Retired here rather than by a sweep: it costs nothing to do while somebody
    is already looking, and a cross-tenant schedule for it would be machinery
    with no purpose. A bucket that will not delete is a leak, not a 500.
    """
    require_view(claims)
    await retire_expired(session, tenant.id, storage)
    result = await session.execute(_LIST, {"tenant_id": tenant.id})
    return ExportList(exports=[_export_row(row) for row in result.all()])


@router.post("/audit/exports", response_model=ExportRow, status_code=status.HTTP_202_ACCEPTED)
async def create_audit_export(
    body: ExportRequest,
    claims: AuthDep,
    tenant: TenantDep,
    session: DbSession,
    storage: StorageDep,
    background: BackgroundTasks,
) -> ExportRow:
    require_view(claims)
    require_export(claims, storage)

    if body.format not in MEDIA_TYPES:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ApiErrorCode.EXPORT_FORMAT_UNKNOWN,
            f"unknown export format {body.format!r}",
        )

    allowed = visible_classes(claims)
    if body.classification is not None and body.classification not in allowed:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.PERMISSION_MISSING,
            "exporting security events needs an owner or administrator",
        )

    now = datetime.now(UTC)
    end = body.before or now
    start = body.since or (end - max_range())
    if start >= end or (end - start) > max_range():
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ApiErrorCode.FILTER_INVALID,
            f"an export covers at most {MAX_RANGE_DAYS} days",
        )

    classes = [body.classification] if body.classification else list(allowed)
    filters = {
        "action": body.action,
        "actor_id": body.actor_id,
        "outcome": body.outcome,
        "classification": body.classification,
        "since": start.isoformat(),
        "before": end.isoformat(),
    }
    created = (
        await session.execute(
            _INSERT,
            {
                "tenant_id": tenant.id,
                "requested_by": claims.sub,
                "format": body.format,
                "filters": json.dumps(filters),
                "expires": now + timedelta(days=DEFAULT_EXPIRY_DAYS),
            },
        )
    ).one()
    await session.commit()
    row = _export_row(created)

    # The export is itself an event: a copy of the records left the product.
    # The shape of the request, never one exported row.
    await record(
        session,
        tenant_id=tenant.id,
        actor_id=claims.sub,
        action="audit.exported",
        target_type="audit_export",
        target_id=row.id,
        outcome="pending",
        details={"format": body.format, "days": (end - start).days},
    )

    background.add_task(
        write_export,
        tenant_id=tenant.id,
        user_id=claims.sub,
        export_id=row.id,
        fmt=body.format,
        classes=classes,
        start=start,
        end=end,
        action=body.action,
        actor_id=body.actor_id,
        outcome=body.outcome,
        storage=storage,
    )
    return row


async def write_export(
    *,
    tenant_id: str,
    user_id: str,
    export_id: str,
    fmt: str,
    classes: list[str],
    start: datetime,
    end: datetime,
    action: str | None,
    actor_id: str | None,
    outcome: str | None,
    storage: TenantStorage,
) -> None:
    """Render and store the artifact after the response has gone.

    Opens its own tenant session, because the request's is closed by now -- the
    same path a report export takes. A failure marks the row `failed` with a
    sentence a person can read: an export that silently never appears is worse
    than one that says why it did not.
    """
    async with tenant_session(tenant_id, user_id=user_id) as session:
        try:
            result = await session.execute(
                SEARCH_STATEMENT,
                {
                    "tenant_id": tenant_id,
                    "classes": classes,
                    "since": start,
                    "before": end,
                    "action": action,
                    "actor_id": actor_id,
                    "outcome": outcome,
                    "target_type": None,
                    # One more than the ceiling, so a full page is
                    # distinguishable from an over-full one.
                    "limit": EXPORT_ROW_CEILING + 1,
                },
            )
            rows = result.all()
            if len(rows) > EXPORT_ROW_CEILING:
                # The ceiling is a refusal, not a trim. An evidential export
                # handed to an auditor as a complete record of a period, that
                # silently held only the most recent 200,000 rows, is worse
                # than one that did not arrive. The comment above promised
                # this and the code truncated until a review found it.
                raise ValueError(
                    f"the range contains more than {EXPORT_ROW_CEILING} rows; narrow it"
                )
            payload = render(rows, fmt)
            name = filename(export_id, fmt)
            key = object_key(tenant_id, export_id, name, category=Category.EXPORTS)
            storage.store.put(key, payload, MEDIA_TYPES[fmt])
            await session.execute(
                _READY,
                {"id": export_id, "key": key, "size": len(payload), "rows": len(rows)},
            )
            await _completed(session, tenant_id, user_id, export_id, "ok", rows=len(rows))
            await session.commit()
        except Exception as problem:
            logger.exception("an audit export could not be written")
            await session.rollback()
            await session.execute(
                _FAILED,
                {
                    "id": export_id,
                    # A fixed sentence. The class name said `ClientError`,
                    # `NoCredentialsError`, `EndpointConnectionError` -- which
                    # is infrastructure fingerprinting handed to a customer,
                    # and the table's own comment forbids it. The detail is in
                    # the log, with the export id to find it by.
                    "error": (
                        "the export could not be produced; quote this export's"
                        " id to support"
                        if not isinstance(problem, ValueError)
                        else str(problem)
                    ),
                },
            )
            await _completed(session, tenant_id, user_id, export_id, "failed", rows=0)
            await session.commit()


async def _completed(
    session: AsyncSession,
    tenant_id: str,
    user_id: str,
    export_id: str,
    outcome: Outcome,
    *,
    rows: int,
) -> None:
    """Close the request event out with a second event, never by editing the first.

    The request records `pending`, because the row exists before the artifact
    does. Resolving that by updating the row would be an update on
    `audit_events`, which carries no update policy -- append-only is the point
    of the table -- so the statement would touch zero rows and report success.
    A second event with the same target is the honest shape: the history says
    an export was asked for and then says how it ended.
    """
    await record(
        session,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="audit.export_completed",
        target_type="audit_export",
        target_id=export_id,
        outcome=outcome,
        details={"rows": rows},
    )


@router.get("/audit/exports/{export_id}/download", response_model=DownloadTicket)
async def download_audit_export(
    export_id: str,
    claims: AuthDep,
    tenant: TenantDep,
    session: DbSession,
    storage: StorageDep,
) -> DownloadTicket:
    """A signed URL for a finished export, refused once it has expired."""
    require_view(claims)
    require_export(claims, storage)

    row = (await session.execute(_ONE, {"id": export_id, "tenant_id": tenant.id})).first()
    if row is None or row.status != "ready" or not row.storage_key:
        raise api_error(status.HTTP_404_NOT_FOUND, ApiErrorCode.EXPORT_NOT_FOUND, "no such export")
    if row.expires_at is not None and row.expires_at < datetime.now(UTC):
        raise api_error(
            status.HTTP_404_NOT_FOUND, ApiErrorCode.EXPORT_NOT_FOUND, "that export has expired"
        )

    await record(
        session,
        tenant_id=tenant.id,
        actor_id=claims.sub,
        action="audit.export_downloaded",
        target_type="audit_export",
        target_id=export_id,
        outcome="ok",
        details={"format": row.format},
    )
    return DownloadTicket(
        url=storage.store.presign_download(
            row.storage_key, filename(export_id, row.format), DOWNLOAD_SECONDS
        ),
        expires_in=DOWNLOAD_SECONDS,
    )


async def retire_expired(session: DbSession, tenant_id: str, storage: StorageDep) -> int:
    """Remove artifacts past their expiry. The object first, then the row."""
    retired = 0
    for row in (await session.execute(_EXPIRED, {"tenant_id": tenant_id})).all():
        try:
            storage.store.delete(row.storage_key)
        except Exception:
            logger.warning("an expired audit export could not be removed from the bucket")
            continue
        await session.execute(_DELETE, {"id": row.id})
        retired += 1
    if retired:
        await session.commit()
    return retired
