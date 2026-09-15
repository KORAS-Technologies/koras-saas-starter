"""The reporting surface: the catalogue this caller may see, one report's
definition, its data, its CSV, and the metric registry.

Five routes, every one on the customer surface and the tenant session. The
decision for each report is made here, before its resolver runs: the
caller's permissions against the definition's, the plan against its
entitlement, the build's capabilities against the one it needs. A report
the caller may not have is 404, not 403, so the list and the URL agree
about what exists for them; a report the plan lacks is 402, the status
Files and the assistant use for a commercial gate. Filters the report did
not declare are 422.

An export is the report's rows as CSV, gated by the export permission and
the export entitlement, refused while the plan is unresolved, bounded, and
recorded. A sensitive report is recorded when it is opened.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from koras_reporting import (
    EXPORT_ROW_LIMIT,
    ExportFormat,
    FilterError,
    ReportDefinition,
    ReportResult,
    Visibility,
    export_filename,
    resolve_filters,
    to_csv,
    visibility_for,
)
from pydantic import BaseModel

from ..core.reporting import EXPORT_PERMISSION, ReportingDep, TenantReporting

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


def _visible(reporting: TenantReporting, definition: ReportDefinition) -> Visibility:
    return visibility_for(
        definition,
        permissions=reporting.context.permissions,
        entitled=reporting.grant.entitled,
        capabilities=reporting.capabilities,
    )


def _lookup(reporting: TenantReporting, key: str) -> tuple[ReportDefinition, Visibility]:
    """The definition and the caller's visibility of it, or 404.

    Hidden is 404 rather than 403 on purpose: the list did not offer it, so
    the URL does not exist for this caller, and a 403 would tell them that
    an area they may not enter does.
    """
    definition = reporting.catalogue.reports.get(key)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such report")
    visibility = _visible(reporting, definition)
    if visibility is Visibility.HIDDEN:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such report")
    return definition, visibility


def _require_available(definition: ReportDefinition, visibility: Visibility) -> None:
    if visibility is Visibility.LOCKED:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"this organization's plan does not include {definition.entitlement}",
        )


def _query(request: Request) -> dict[str, str]:
    # The last value wins for a repeated key, the way a form would submit it.
    return {key: value for key, value in request.query_params.items()}


async def _resolve(
    reporting: TenantReporting, definition: ReportDefinition, request: Request
) -> ReportResult:
    try:
        filters = resolve_filters(definition, _query(request))
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


@router.get("/reports", response_model=ReportList)
async def list_reports(reporting: ReportingDep) -> ReportList:
    """Every report this caller may see, available or locked, in catalogue order."""
    reports = []
    for definition in reporting.catalogue.reports:
        visibility = _visible(reporting, definition)
        if visibility is Visibility.HIDDEN:
            continue
        reports.append(_summary(definition, visibility))
    return ReportList(
        reports=reports, resolved=reporting.grant.resolved, plan=reporting.context.plan.code
    )


@router.get("/reports/{key}", response_model=ReportView)
async def get_report(key: str, reporting: ReportingDep) -> ReportView:
    definition, visibility = _lookup(reporting, key)
    summary = _summary(definition, visibility)
    can_export = (
        visibility is Visibility.AVAILABLE
        and EXPORT_PERMISSION in reporting.context.permissions
        and reporting.grant.can_export
        and ExportFormat.CSV in definition.export_formats
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
        can_export=can_export,
        cache_seconds=definition.cache_seconds,
        status=definition.status.value,
        version=definition.version,
    )


@router.get("/reports/{key}/data", response_model=ReportResult)
async def report_data(key: str, request: Request, reporting: ReportingDep) -> ReportResult:
    """The report, resolved for this tenant under the filters the URL carries."""
    definition, visibility = _lookup(reporting, key)
    _require_available(definition, visibility)
    try:
        result = await _resolve(reporting, definition, request)
        if definition.sensitive:
            reporting.record("report.viewed", report_key=definition.key, details=_range_of(result))
        return result
    finally:
        await reporting.flush()


@router.get("/reports/{key}/export")
async def export_report(key: str, request: Request, reporting: ReportingDep) -> Response:
    """The report's rows as CSV. Gated twice, bounded once, recorded always."""
    definition, visibility = _lookup(reporting, key)
    _require_available(definition, visibility)
    if EXPORT_PERMISSION not in reporting.context.permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="exporting reports needs reports.export"
        )
    if not reporting.grant.can_export:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="this organization's plan does not include reporting.export",
        )
    if ExportFormat.CSV not in definition.export_formats:
        raise HTTPException(
            status_code=status.HTTP_406_NOT_ACCEPTABLE, detail="this report cannot be exported"
        )
    try:
        result = await _resolve(reporting, definition, request)
        rows = len(result.table.rows) if result.table is not None else len(result.metrics)
        if rows > EXPORT_ROW_LIMIT:
            reporting.record(
                "report.exported",
                report_key=definition.key,
                outcome="denied",
                details={"rows": rows, "limit": EXPORT_ROW_LIMIT},
            )
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"the export would carry {rows} rows; narrow the range to "
                f"{EXPORT_ROW_LIMIT} or fewer",
            )
        reporting.record(
            "report.exported",
            report_key=definition.key,
            details={"rows": rows, "format": "csv", **_range_of(result)},
        )
        start = result.range.start if result.range else None
        end = result.range.end if result.range else None
        filename = export_filename(definition.key, start, end)
        return Response(
            content=to_csv(result),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )
    finally:
        await reporting.flush()


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


def _range_of(result: ReportResult) -> dict[str, Any]:
    if result.range is None:
        return {}
    return {"from": result.range.start, "to": result.range.end}
