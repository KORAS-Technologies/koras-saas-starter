"""Who may open a report, and what leaves as a file."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from koras_reporting import (
    Category,
    Format,
    MetricValue,
    ReportContext,
    ReportDefinition,
    ReportResult,
    ResolvedFilters,
    Status,
    Table,
    TableColumn,
    Unit,
    Visibility,
    export_filename,
    to_csv,
    visibility_for,
)


async def _answer(context: ReportContext, filters: ResolvedFilters) -> ReportResult:
    return ReportResult(key="p.q", generated_at=context.now)


def definition(**overrides: object) -> ReportDefinition:
    fields: dict[str, object] = {
        "key": "p.q",
        "name": "P",
        "description": "Q",
        "category": Category.USAGE,
        "resolver": _answer,
        "permission": "reports.read",
        "entitlement": "reporting.basic",
    }
    fields.update(overrides)
    return ReportDefinition(**fields)  # type: ignore[arg-type]


def entitled_to(*codes: str) -> Callable[[str], bool]:
    return lambda code: code in codes


def test_permission_hides_and_entitlement_locks() -> None:
    assert (
        visibility_for(
            definition(), permissions={"reports.read"}, entitled=entitled_to("reporting.basic")
        )
        is Visibility.AVAILABLE
    )
    assert (
        visibility_for(definition(), permissions={"reports.read"}, entitled=entitled_to())
        is Visibility.LOCKED
    )
    assert (
        visibility_for(
            definition(), permissions={"files.read"}, entitled=entitled_to("reporting.basic")
        )
        is Visibility.HIDDEN
    )


def test_a_missing_capability_and_a_deprecated_report_hide() -> None:
    assert (
        visibility_for(
            definition(capability="ai"),
            permissions={"reports.read"},
            entitled=entitled_to("reporting.basic"),
            capabilities=["storage"],
        )
        is Visibility.HIDDEN
    )
    assert (
        visibility_for(
            definition(capability="ai"),
            permissions={"reports.read"},
            entitled=entitled_to("reporting.basic"),
            capabilities=["ai"],
        )
        is Visibility.AVAILABLE
    )
    assert (
        visibility_for(
            definition(status=Status.DEPRECATED),
            permissions={"reports.read"},
            entitled=entitled_to("reporting.basic"),
        )
        is Visibility.HIDDEN
    )


def test_csv_writes_the_table_and_neutralises_formulas() -> None:
    result = ReportResult(
        key="p.q",
        generated_at=datetime(2026, 9, 14, tzinfo=UTC),
        table=Table(
            columns=[
                TableColumn(key="name", label="Name"),
                TableColumn(key="count", label="Count", align="right"),
            ],
            rows=[
                {"name": '=HYPERLINK("http://evil")', "count": 3},
                {"name": "plain, with comma", "count": None},
                {"name": "+1 555", "count": 1.5},
            ],
        ),
    )
    lines = to_csv(result).splitlines()
    assert lines[0] == "Name,Count"
    assert lines[1].startswith("\"'=HYPERLINK(")
    assert lines[2] == '"plain, with comma",'
    assert lines[3] == "'+1 555,1.5"


def test_csv_falls_back_to_the_metrics() -> None:
    result = ReportResult(
        key="p.q",
        generated_at=datetime(2026, 9, 14, tzinfo=UTC),
        metrics=[
            MetricValue(
                key="things_total",
                label="Things",
                value=4,
                unit=Unit.COUNT,
                format=Format.INTEGER,
                kind="actual",
            ),
            MetricValue(
                key="missing",
                label="Missing",
                value=None,
                unit=Unit.COUNT,
                format=Format.INTEGER,
                kind="unavailable",
            ),
        ],
    )
    lines = to_csv(result).splitlines()
    assert lines == [
        "metric,value,unit,kind",
        "Things,4,count,actual",
        "Missing,,count,unavailable",
    ]
    assert export_filename("p.q", "2026-09-01", "2026-09-14") == "p-q-2026-09-01-to-2026-09-14.csv"
    assert export_filename("p.q", None, None) == "p-q.csv"
