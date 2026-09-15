"""The registry refuses what would fail at request time, at import instead."""

from __future__ import annotations

import pytest
from koras_reporting import (
    DATE_RANGE,
    Aggregation,
    Category,
    FilterDefinition,
    FilterKind,
    Format,
    MetricDefinition,
    ReportContext,
    ReportDefinition,
    ReportResult,
    ResolvedFilters,
    Unit,
    Visualization,
    build_catalogue,
)


async def _answer(context: ReportContext, filters: ResolvedFilters) -> ReportResult:
    return ReportResult(key="x.y", generated_at=context.now)


def metric(key: str = "things_total") -> MetricDefinition:
    return MetricDefinition(
        key=key,
        name="Things",
        description="How many things",
        unit=Unit.COUNT,
        format=Format.INTEGER,
        aggregation=Aggregation.COUNT,
    )


def report(key: str = "things.overview", **overrides: object) -> ReportDefinition:
    fields: dict[str, object] = {
        "key": key,
        "name": "Things overview",
        "description": "The things",
        "category": Category.PRODUCT,
        "resolver": _answer,
        "permission": "reports.read",
        "metrics": ("things_total",),
        "filters": (DATE_RANGE,),
    }
    fields.update(overrides)
    return ReportDefinition(**fields)  # type: ignore[arg-type]


def test_a_catalogue_lists_reports_by_category_then_order() -> None:
    catalogue = build_catalogue(
        [metric()],
        [
            report("things.second", category=Category.PRODUCT, order=20),
            report("usage.overview", category=Category.OVERVIEW, order=10),
            report("things.first", category=Category.PRODUCT, order=10),
        ],
    )
    assert [r.key for r in catalogue.reports] == ["usage.overview", "things.first", "things.second"]
    assert "things_total" in catalogue.metrics
    assert len(catalogue.reports) == 3


def test_a_report_naming_an_unregistered_metric_is_refused() -> None:
    with pytest.raises(ValueError, match="unregistered metrics"):
        build_catalogue([metric()], [report(metrics=("things_total", "nobody_defined"))])


def test_a_duplicate_key_is_refused() -> None:
    with pytest.raises(ValueError, match="registered twice"):
        build_catalogue([metric(), metric()], [])
    with pytest.raises(ValueError, match="registered twice"):
        build_catalogue([metric()], [report(), report()])


def test_keys_have_one_shape_each() -> None:
    with pytest.raises(ValueError, match="snake_case"):
        metric("Things-Total")
    with pytest.raises(ValueError, match="dotted"):
        report("overview")


def test_a_default_visualization_must_be_offered() -> None:
    with pytest.raises(ValueError, match="does not offer"):
        report(default_visualization=Visualization.LINE, visualizations=(Visualization.KPI,))


def test_a_choice_filter_needs_options_and_an_offered_default() -> None:
    with pytest.raises(ValueError, match="no options"):
        FilterDefinition(key="status", kind=FilterKind.CHOICE, label="Status")
    with pytest.raises(ValueError, match="does not offer"):
        FilterDefinition(
            key="status", kind=FilterKind.CHOICE, label="Status", options=("a",), default="b"
        )
    with pytest.raises(ValueError, match="declares a filter twice"):
        report(filters=(DATE_RANGE, DATE_RANGE))


def test_a_tenant_context_refuses_to_exist_without_a_tenant() -> None:
    from koras_reporting import UNRESOLVED_PLAN, Scope

    with pytest.raises(ValueError, match="needs a tenant"):
        ReportContext(
            scope=Scope.TENANT,
            user_id="u",
            permissions=frozenset(),
            plan=UNRESOLVED_PLAN,
            session=None,
        )
    platform = ReportContext(
        scope=Scope.PLATFORM,
        user_id="staff",
        permissions=frozenset({"platform_admin"}),
        plan=UNRESOLVED_PLAN,
        session=None,
    )
    assert platform.tenant_id is None
