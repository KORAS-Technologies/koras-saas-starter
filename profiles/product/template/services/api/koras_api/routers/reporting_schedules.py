"""Schedules and background exports: the two things reporting keeps as state.

A schedule is a person's standing request to have a report delivered:
which report, how often, in which format, to whom. Creating one takes the
same two gates a download does, the export permission and the export
entitlement, plus `reporting.scheduled`. The worker delivers on the
provisioning context, so what is validated here is the whole of what it
trusts: the report exists and is open to the caller, the format is one the
report offers, the filters are ones it declared, the addresses are shaped
like addresses and bounded in number.

A background export is what the export route wrote after its response.
Listing them is also where they are retired: a row older than the
retention is deleted with its object, on the tenant session with the
tenant's store at hand, which is the one place both are reachable without
the worker holding storage credentials.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, status
from koras_email import Locale, is_locale
from koras_reporting import ExportFormat, FilterError, FilterKind, resolve_filters
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.engine import Row

from ..core.errors import ApiErrorCode, api_error
from ..core.locale import RequestLocale
from ..core.reporting import ReportingDep
from ..core.settings import settings
from ..core.storage import StorageDep
from .reporting import export_format, lookup, require_available, require_exporter

router = APIRouter(tags=["reports"])
_log = logging.getLogger(__name__)

Cadence = Literal["daily", "weekly", "monthly"]

#: Delivery hour, UTC. Early enough to be in the inbox at the start of the
#: recipient's day in most of the world, late enough that the previous day
#: is complete everywhere.
DELIVERY_HOUR = 6
MAX_RECIPIENTS = 10
DOWNLOAD_URL_SECONDS = 5 * 60

#: The longest address SMTP will carry (RFC 5321 path limit less the brackets).
MAX_ADDRESS_LENGTH = 254

#: One `@`, a local part, and a domain of dot-separated labels, none of them
#: empty. Each label excludes the dot that separates it from the next, so there
#: is exactly one way to split a domain and matching is linear -- the previous
#: `[^@\s]+\.[^@\s]+` let both sides claim the same dots, which backtracks
#: polynomially on a long run of them (CodeQL py/polynomial-redos). The same
#: shape as `koras_import.mapping._EMAIL`.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cadence: Cadence
    format: str = "csv"
    recipients: list[str] = Field(min_length=1, max_length=MAX_RECIPIENTS)
    #: The report's declared filters other than the period.
    filters: dict[str, str] = Field(default_factory=dict)
    #: The language the deliveries are written in. The recipients may not be
    #: the person creating the schedule, so it is named rather than inferred;
    #: absent, the request's own language is used.
    locale: Locale | None = None


class ScheduleView(BaseModel):
    id: str
    report_key: str
    cadence: str
    format: str
    recipients: list[str]
    filters: dict[str, str]
    locale: str
    active: bool
    next_run_at: datetime
    last_run_at: datetime | None
    last_error: str | None
    created_by: str
    created_at: datetime


class ScheduleList(BaseModel):
    schedules: list[ScheduleView]


class ExportView(BaseModel):
    id: str
    report_key: str
    format: str
    status: str
    filename: str
    rows: int
    size_bytes: int | None
    error: str | None
    requested_by: str
    created_at: datetime
    ready_at: datetime | None


class ExportList(BaseModel):
    exports: list[ExportView]
    retention_days: int


class DownloadTicket(BaseModel):
    url: str
    expires_in: int


def next_run(cadence: str, now: datetime) -> datetime:
    """The next delivery after `now`: tomorrow, next Monday, or the first of
    next month, at the delivery hour, UTC."""
    at = now.astimezone(UTC).replace(hour=DELIVERY_HOUR, minute=0, second=0, microsecond=0)
    if cadence == "daily":
        return at + timedelta(days=1)
    if cadence == "weekly":
        days_ahead = (7 - at.weekday()) % 7 or 7
        return at + timedelta(days=days_ahead)
    first = (at.replace(day=1) + timedelta(days=32)).replace(day=1)
    return first


def _validate_recipients(recipients: list[str]) -> list[str]:
    cleaned = []
    for raw in recipients:
        address = raw.strip().lower()
        # Length first: the pattern is linear, but nothing over the limit is an
        # address, and refusing it before matching keeps the cost bounded by
        # the limit rather than by whatever the request body carried.
        if len(address) > MAX_ADDRESS_LENGTH or not _EMAIL.match(address):
            raise api_error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                ApiErrorCode.RECIPIENT_INVALID,
                f"{raw!r} is not an email address",
            )
        if address not in cleaned:
            cleaned.append(address)
    return cleaned


_SCHEDULES = text(
    "select id::text as id, report_key, cadence, format, recipients, filters, locale, active, "
    " next_run_at, last_run_at, last_error, created_by, created_at "
    "from public.report_schedules "
    "where tenant_id = :tenant_id and report_key = :report_key "
    "order by created_at desc"
)

_SCHEDULE_INSERT = text(
    "insert into public.report_schedules "
    " (tenant_id, report_key, cadence, format, recipients, filters, locale, created_by, "
    "  next_run_at) "
    "values (:tenant_id, :report_key, :cadence, :format, :recipients, cast(:filters as jsonb), "
    " :locale, :created_by, :next_run_at) "
    "returning id::text as id, report_key, cadence, format, recipients, filters, locale, active, "
    " next_run_at, last_run_at, last_error, created_by, created_at"
)

_SCHEDULE_DELETE = text(
    "delete from public.report_schedules where id = :id and tenant_id = :tenant_id "
    "returning report_key"
)


def _schedule(row: Row[Any]) -> ScheduleView:
    filters = row.filters if isinstance(row.filters, dict) else json.loads(row.filters or "{}")
    return ScheduleView(
        id=row.id,
        report_key=row.report_key,
        cadence=row.cadence,
        format=row.format,
        recipients=list(row.recipients),
        filters={str(k): str(v) for k, v in filters.items()},
        locale=str(row.locale) if is_locale(getattr(row, "locale", None)) else "en",
        active=bool(row.active),
        next_run_at=row.next_run_at,
        last_run_at=row.last_run_at,
        last_error=row.last_error,
        created_by=row.created_by,
        created_at=row.created_at,
    )


@router.get("/reports/{key}/schedules", response_model=ScheduleList)
async def list_schedules(key: str, reporting: ReportingDep) -> ScheduleList:
    definition, _visibility = lookup(reporting, key)
    rows = await reporting.context.session.execute(
        _SCHEDULES, {"tenant_id": reporting.context.tenant_id, "report_key": definition.key}
    )
    return ScheduleList(schedules=[_schedule(row) for row in rows.fetchall()])


@router.post(
    "/reports/{key}/schedules", response_model=ScheduleView, status_code=status.HTTP_201_CREATED
)
async def create_schedule(
    key: str, body: ScheduleCreate, reporting: ReportingDep, request_locale: RequestLocale
) -> ScheduleView:
    definition, visibility = lookup(reporting, key)
    require_available(definition, visibility)
    require_exporter(reporting)
    if not reporting.grant.can_schedule:
        raise api_error(
            status.HTTP_402_PAYMENT_REQUIRED,
            ApiErrorCode.ENTITLEMENT_MISSING,
            "this organization's plan does not include reporting.scheduled",
        )
    fmt = export_format(definition, body.format)
    recipients = _validate_recipients(body.recipients)
    if any(name in ("from", "to") for name in body.filters):
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ApiErrorCode.PERIOD_NOT_A_FILTER,
            "the period is decided by the cadence, not by a filter",
        )
    try:
        resolved = resolve_filters(definition, body.filters)
    except FilterError as error:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY, ApiErrorCode.FILTER_INVALID, str(error)
        ) from error
    kept = {
        f.key: str(resolved.values[f.key])
        for f in definition.filters
        if f.kind is not FilterKind.DATE_RANGE and f.key in resolved.values
    }
    session = reporting.context.session
    try:
        row = (
            await session.execute(
                _SCHEDULE_INSERT,
                {
                    "tenant_id": reporting.context.tenant_id,
                    "report_key": definition.key,
                    "cadence": body.cadence,
                    "format": fmt.value,
                    "recipients": recipients,
                    "filters": json.dumps(kept, sort_keys=True),
                    "locale": body.locale or request_locale,
                    "created_by": reporting.context.user_id,
                    "next_run_at": next_run(body.cadence, reporting.context.now),
                },
            )
        ).first()
        await session.commit()
        reporting.record(
            "report.scheduled",
            report_key=definition.key,
            details={"cadence": body.cadence, "format": fmt.value, "recipients": len(recipients)},
        )
    finally:
        await reporting.flush()
    assert row is not None  # noqa: S101 - `returning` always yields the row
    return _schedule(row)


@router.delete("/reports/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(schedule_id: str, reporting: ReportingDep) -> None:
    require_exporter_or_none(reporting)
    session = reporting.context.session
    try:
        row = (
            await session.execute(
                _SCHEDULE_DELETE, {"id": schedule_id, "tenant_id": reporting.context.tenant_id}
            )
        ).first()
        if row is None:
            raise api_error(
                status.HTTP_404_NOT_FOUND, ApiErrorCode.SCHEDULE_NOT_FOUND, "no such schedule"
            )
        await session.commit()
        reporting.record(
            "report.schedule_removed", report_key=str(row.report_key), details={"id": schedule_id}
        )
    finally:
        await reporting.flush()


def require_exporter_or_none(reporting: ReportingDep) -> None:
    # Removing a schedule needs the same authority as creating one, but not the
    # plan: a customer whose plan lapsed may still switch off what it sends.
    from ..core.reporting import EXPORT_PERMISSION

    if EXPORT_PERMISSION not in reporting.context.permissions:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.PERMISSION_MISSING,
            "managing schedules needs reports.export",
        )


# ── exports ───────────────────────────────────────────────────────────────────

_EXPORTS = text(
    "select id::text as id, report_key, format, status, filename, rows, size_bytes, error, "
    " requested_by, created_at, ready_at, storage_key "
    "from public.report_exports where tenant_id = :tenant_id "
    "order by created_at desc limit 50"
)

_EXPIRED = text(
    "select id::text as id, storage_key from public.report_exports "
    "where tenant_id = :tenant_id and created_at < :before"
)

_EXPORT_DELETE = text("delete from public.report_exports where id = :id and tenant_id = :tenant_id")

_EXPORT_ONE = text(
    "select id::text as id, storage_key, filename, status from public.report_exports "
    "where id = :id and tenant_id = :tenant_id"
)


async def _retire(reporting: ReportingDep, storage: StorageDep) -> None:
    """Delete exports past the retention, object then row, on the way to listing."""
    days = settings.report_export_retention_days
    if days < 1:
        return
    session = reporting.context.session
    before = reporting.context.now - timedelta(days=days)
    rows = (
        await session.execute(
            _EXPIRED, {"tenant_id": reporting.context.tenant_id, "before": before}
        )
    ).fetchall()
    for row in rows:
        if row.storage_key:
            try:
                storage.store.delete(str(row.storage_key))
            except Exception:  # noqa: BLE001 - a bucket that will not delete is a leak, not a 500
                _log.warning("export %s: the object could not be deleted; row kept", row.id)
                continue
        await session.execute(
            _EXPORT_DELETE, {"id": row.id, "tenant_id": reporting.context.tenant_id}
        )
    if rows:
        await session.commit()


@router.get("/reports/exports", response_model=ExportList)
async def list_exports(reporting: ReportingDep, storage: StorageDep) -> ExportList:
    """Every background export this tenant holds, newest first, retired past the retention."""
    await _retire(reporting, storage)
    rows = await reporting.context.session.execute(
        _EXPORTS, {"tenant_id": reporting.context.tenant_id}
    )
    return ExportList(
        exports=[
            ExportView(
                id=row.id,
                report_key=row.report_key,
                format=row.format,
                status=row.status,
                filename=row.filename,
                rows=int(row.rows),
                size_bytes=row.size_bytes,
                error=row.error,
                requested_by=row.requested_by,
                created_at=row.created_at,
                ready_at=row.ready_at,
            )
            for row in rows.fetchall()
        ],
        retention_days=settings.report_export_retention_days,
    )


@router.get("/reports/exports/{export_id}/download", response_model=DownloadTicket)
async def download_export(
    export_id: str, reporting: ReportingDep, storage: StorageDep
) -> DownloadTicket:
    """A signed URL for one ready export. The same gates as the export itself."""
    require_exporter(reporting)
    row = (
        await reporting.context.session.execute(
            _EXPORT_ONE, {"id": export_id, "tenant_id": reporting.context.tenant_id}
        )
    ).first()
    if row is None or row.status != "ready" or not row.storage_key:
        raise api_error(status.HTTP_404_NOT_FOUND, ApiErrorCode.EXPORT_NOT_FOUND, "no such export")
    return DownloadTicket(
        url=storage.store.presign_download(
            str(row.storage_key), str(row.filename), DOWNLOAD_URL_SECONDS
        ),
        expires_in=DOWNLOAD_URL_SECONDS,
    )


def formats_for(definition_formats: tuple[ExportFormat, ...]) -> list[str]:
    return [f.value for f in definition_formats]
