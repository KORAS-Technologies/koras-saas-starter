"""The reporting surface: the catalogue this caller may see, one report's
definition, its data, its export, and the metric registry.

Every route is on the customer surface and the tenant session. The decision
for each report is made here, before its resolver runs: the caller's
permissions against the definition's, the plan against its entitlement, the
build's capabilities against the one it needs. A report the caller may not
have is 404, not 403, so the list and the URL agree about what exists for
them; a report the plan lacks is 402, the status Files and the assistant use
for a commercial gate. Filters the report did not declare are 422.

An export is the report as a file in one of three formats, gated by the
export permission and the export entitlement, refused while the plan is
unresolved, and recorded. Past the row bound it is not refused: it is
written into the tenant's bucket after the response and answered with 202
and the export's id, which `reporting_schedules.py` lists and mints a
download for. A sensitive report is recorded when it is opened.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from koras_audit import AuditEvent
from koras_reporting import (
    EXPORT_ROW_LIMIT,
    ExportFormat,
    FilterError,
    ReportDefinition,
    ReportResult,
    Visibility,
    export_filename,
    render,
    resolve_filters,
    row_count,
    visibility_for,
)
from pydantic import BaseModel
from sqlalchemy import text

from ..core.database import tenant_session
from ..core.reporting import EXPORT_PERMISSION, ReportingDep, SqlAuditSink, TenantReporting
from ..core.storage import StorageDep, TenantStorage

router = APIRouter(tags=["reports"])

_log = logging.getLogger(__name__)


class FilterView(BaseModel):
    key: str
    kind: str
    label: str
    options: list[str]
    default: str | int | None
    minimum: int | None
    maximum: int | None


class ReportSummary(BaseModel):
    key: str
    name: str
    description: str
    category: str
    visibility: str
    entitlement: str | None
    default_visualization: str
    sensitive: bool
    order: int


class ReportView(ReportSummary):
    metrics: list[str]
    dimensions: list[str]
    filters: list[FilterView]
    visualizations: list[str]
    export_formats: list[str]
    can_export: bool
    #: Whether this caller may have the report delivered on a schedule.
    can_schedule: bool
    cache_seconds: int
    status: str
    version: int


class ReportList(BaseModel):
    reports: list[ReportSummary]
    #: Whether the platform answered about the plan. False means the basic
    #: reports are listed and the page should say the plan could not be read.
    resolved: bool
    plan: str | None


class MetricView(BaseModel):
    key: str
    name: str
    description: str
    unit: str
    format: str
    aggregation: str
    dimensions: list[str]


class MetricList(BaseModel):
    metrics: list[MetricView]


class ExportQueued(BaseModel):
    """The export is being written; the id to look for in the list."""

    export_id: str
    rows: int
    format: str


def _summary(definition: ReportDefinition, visibility: Visibility) -> ReportSummary:
    return ReportSummary(
        key=definition.key,
        name=definition.name,
        description=definition.description,
        category=definition.category.value,
        visibility=visibility.value,
        entitlement=definition.entitlement,
        default_visualization=definition.default_visualization.value,
        sensitive=definition.sensitive,
        order=definition.order,
    )


def visible(reporting: TenantReporting, definition: ReportDefinition) -> Visibility:
    return visibility_for(
        definition,
        permissions=reporting.context.permissions,
        entitled=reporting.grant.entitled,
        capabilities=reporting.capabilities,
    )


def lookup(reporting: TenantReporting, key: str) -> tuple[ReportDefinition, Visibility]:
    """The definition and the caller's visibility of it, or 404.

    Hidden is 404 rather than 403 on purpose: the list did not offer it, so
    the URL does not exist for this caller, and a 403 would tell them that
    an area they may not enter does.
    """
    definition = reporting.catalogue.reports.get(key)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such report")
    visibility = visible(reporting, definition)
    if visibility is Visibility.HIDDEN:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such report")
    return definition, visibility


def require_available(definition: ReportDefinition, visibility: Visibility) -> None:
    if visibility is Visibility.LOCKED:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"this organization's plan does not include {definition.entitlement}",
        )


def require_exporter(reporting: TenantReporting) -> None:
    """The two gates a download and a schedule share: the permission, then the plan."""
    if EXPORT_PERMISSION not in reporting.context.permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="exporting reports needs reports.export"
        )
    if not reporting.grant.can_export:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="this organization's plan does not include reporting.export",
        )


def export_format(definition: ReportDefinition, raw: str | None) -> ExportFormat:
    try:
        fmt = ExportFormat(raw or "csv")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_406_NOT_ACCEPTABLE, detail="unknown export format"
        ) from None
    if fmt not in definition.export_formats:
        raise HTTPException(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            detail=f"this report cannot be exported as {fmt.value}",
        )
    return fmt


def query_of(request: Request) -> dict[str, str]:
    # The last value wins for a repeated key, the way a form would submit it.
    # `format` and `background` belong to the export route, not the report.
    return {
        key: value
        for key, value in request.query_params.items()
        if key not in ("format", "background")
    }


async def resolve(
    reporting: TenantReporting, definition: ReportDefinition, query: dict[str, str]
) -> ReportResult:
    try:
        filters = resolve_filters(definition, query)
    except FilterError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    try:
        return await definition.resolver(reporting.context, filters)
    except HTTPException:
        raise
    except Exception as error:
        # The detail goes to the log; the customer gets a sentence. A
        # resolver's traceback names tables and columns nobody outside
        # should read.
        _log.exception("report %s failed: %s", definition.key, type(error).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="the report could not be produced; the reason is in the server log",
        ) from error


def range_of(result: ReportResult) -> dict[str, Any]:
    if result.range is None:
        return {}
    return {"from": result.range.start, "to": result.range.end}


@router.get("/reports", response_model=ReportList)
async def list_reports(reporting: ReportingDep) -> ReportList:
    """Every report this caller may see, available or locked, in catalogue order."""
    reports = []
    for definition in reporting.catalogue.reports:
        visibility = visible(reporting, definition)
        if visibility is Visibility.HIDDEN:
            continue
        reports.append(_summary(definition, visibility))
    return ReportList(
        reports=reports, resolved=reporting.grant.resolved, plan=reporting.context.plan.code
    )


@router.get("/reports/{key}", response_model=ReportView)
async def get_report(key: str, reporting: ReportingDep) -> ReportView:
    definition, visibility = lookup(reporting, key)
    summary = _summary(definition, visibility)
    may_export = (
        visibility is Visibility.AVAILABLE
        and EXPORT_PERMISSION in reporting.context.permissions
        and reporting.grant.can_export
        and bool(definition.export_formats)
    )
    return ReportView(
        **summary.model_dump(),
        metrics=list(definition.metrics),
        dimensions=list(definition.dimensions),
        filters=[
            FilterView(
                key=f.key,
                kind=f.kind.value,
                label=f.label,
                options=list(f.options),
                default=f.default,
                minimum=f.minimum,
                maximum=f.maximum,
            )
            for f in definition.filters
        ],
        visualizations=[v.value for v in definition.visualizations],
        export_formats=[e.value for e in definition.export_formats],
        can_export=may_export,
        can_schedule=may_export and reporting.grant.can_schedule,
        cache_seconds=definition.cache_seconds,
        status=definition.status.value,
        version=definition.version,
    )


@router.get("/reports/{key}/data", response_model=ReportResult)
async def report_data(key: str, request: Request, reporting: ReportingDep) -> ReportResult:
    """The report, resolved for this tenant under the filters the URL carries."""
    definition, visibility = lookup(reporting, key)
    require_available(definition, visibility)
    try:
        result = await resolve(reporting, definition, query_of(request))
        if definition.sensitive:
            reporting.record("report.viewed", report_key=definition.key, details=range_of(result))
        return result
    finally:
        await reporting.flush()


_EXPORT_INSERT = text(
    "insert into public.report_exports "
    " (id, tenant_id, report_key, format, filters, status, filename, rows, requested_by) "
    "values (:id, :tenant_id, :report_key, :format, cast(:filters as jsonb), 'pending', "
    " :filename, :rows, :requested_by)"
)

_EXPORT_READY = text(
    "update public.report_exports set status = 'ready', storage_key = :storage_key, "
    " size_bytes = :size_bytes, ready_at = now() "
    "where id = :id and tenant_id = :tenant_id"
)

_EXPORT_FAILED = text(
    "update public.report_exports set status = 'failed', error = :error "
    "where id = :id and tenant_id = :tenant_id"
)


def export_object_key(tenant_id: str, export_id: str, filename: str) -> str:
    return f"tenants/{tenant_id}/exports/{export_id}/{filename}"


@router.get(
    "/reports/{key}/export",
    responses={202: {"model": ExportQueued}},
)
async def export_report(
    key: str,
    request: Request,
    reporting: ReportingDep,
    storage: StorageDep,
    background: BackgroundTasks,
    format: str | None = None,  # noqa: A002 - the query parameter's name
) -> Response:
    """The report as a file. Gated twice, bounded once, recorded always.

    Within the bound the file is the response. Past it the row is written,
    202 is answered with the export's id, and the file is rendered and put
    into the tenant's bucket after the response -- the same after-response
    path uploads use for indexing. The customer finds it in the exports list.
    """
    definition, visibility = lookup(reporting, key)
    require_available(definition, visibility)
    require_exporter(reporting)
    fmt = export_format(definition, format)
    wanted_background = request.query_params.get("background") == "1"
    try:
        result = await resolve(reporting, definition, query_of(request))
        rows = row_count(result)
        start = result.range.start if result.range else None
        end = result.range.end if result.range else None
        filename = export_filename(definition.key, start, end, fmt.value)
        if rows > EXPORT_ROW_LIMIT or wanted_background:
            export_id = str(uuid.uuid4())
            session = reporting.context.session
            await session.execute(
                _EXPORT_INSERT,
                {
                    "id": export_id,
                    "tenant_id": reporting.context.tenant_id,
                    "report_key": definition.key,
                    "format": fmt.value,
                    "filters": _json(query_of(request)),
                    "filename": filename,
                    "rows": rows,
                    "requested_by": reporting.context.user_id,
                },
            )
            await session.commit()
            reporting.record(
                "report.exported",
                report_key=definition.key,
                details={"rows": rows, "format": fmt.value, "background": True, **range_of(result)},
            )
            background.add_task(
                write_export,
                storage,
                reporting.context.tenant_id or "",
                export_id,
                filename,
                result,
                fmt,
                definition.name,
            )
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content=ExportQueued(export_id=export_id, rows=rows, format=fmt.value).model_dump(),
            )
        reporting.record(
            "report.exported",
            report_key=definition.key,
            details={"rows": rows, "format": fmt.value, **range_of(result)},
        )
        rendered = render(result, fmt, title=definition.name)
        return Response(
            content=rendered.content,
            media_type=rendered.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )
    finally:
        await reporting.flush()


async def write_export(
    storage: TenantStorage,
    tenant_id: str,
    export_id: str,
    filename: str,
    result: ReportResult,
    fmt: ExportFormat,
    title: str,
) -> None:
    """Render the file and put it in the bucket, after the response.

    Its own session, because the request's is closed by the time this runs.
    A failure is recorded on the row and in the audit table rather than
    lost: a customer who asked for a file and finds a failed row knows to
    ask again or to narrow the range.
    """
    key = export_object_key(tenant_id, export_id, filename)
    async with tenant_session(tenant_id) as session:
        audit = SqlAuditSink(session, tenant_id)
        try:
            rendered = render(result, fmt, title=title)
            storage.store.put(key, rendered.content, rendered.media_type)
            await session.execute(
                _EXPORT_READY,
                {
                    "id": export_id,
                    "tenant_id": tenant_id,
                    "storage_key": key,
                    "size_bytes": len(rendered.content),
                },
            )
            await session.commit()
        except Exception as error:
            _log.exception("export %s failed: %s", export_id, type(error).__name__)
            await session.rollback()
            await session.execute(
                _EXPORT_FAILED,
                {
                    "id": export_id,
                    "tenant_id": tenant_id,
                    "error": "the file could not be written; the reason is in the server log",
                },
            )
            await session.commit()
            audit.emit(
                _event(
                    tenant_id, "report.export_failed", export_id, "failed", {"format": fmt.value}
                )
            )
            await audit.flush()


def _event(
    tenant_id: str, action: str, target_id: str, outcome: str, details: dict[str, Any]
) -> AuditEvent:
    return AuditEvent(
        action=action,
        actor_id="system",
        tenant_id=tenant_id,
        target_type="export",
        target_id=target_id,
        outcome=outcome,  # type: ignore[arg-type]
        details=details,
        at=datetime.now(UTC),
    )


def _json(values: dict[str, str]) -> str:
    import json

    return json.dumps(values, sort_keys=True)


@router.get("/metrics", response_model=MetricList)
async def list_metrics(reporting: ReportingDep) -> MetricList:
    """The metric registry: keys, units and meanings. What a BI tool would read."""
    return MetricList(
        metrics=[
            MetricView(
                key=m.key,
                name=m.name,
                description=m.description,
                unit=m.unit.value,
                format=m.format.value,
                aggregation=m.aggregation.value,
                dimensions=list(m.dimensions),
            )
            for m in reporting.catalogue.metrics
        ]
    )
