"""This product's own reports.

The extension point. The starter ships the six standard tenant reports in
`standard.py` and nothing of any product's domain; a product adds its
metrics and reports here, and the router, the page and the sidebar pick
them up with no other change.

A report is a `ReportDefinition` with a resolver: a coroutine given the
`ReportContext` -- the tenant session with row-level security forced, the
caller's permissions, the plan -- and the filters the definition declared,
answering a `ReportResult`. Bind the tenant id as a parameter even though
the policies scope the session; a reader of the resolver should see what it
selects. Every metric a report names must be in `METRICS`.

    from koras_reporting import (
        DATE_RANGE, Aggregation, Category, Format, MetricDefinition,
        ReportDefinition, Unit, Visualization,
    )

    METRICS = [
        MetricDefinition(
            key="orders_total", name="Orders", description="Orders placed",
            unit=Unit.COUNT, format=Format.INTEGER, aggregation=Aggregation.COUNT,
        ),
    ]
    REPORTS = [
        ReportDefinition(
            key="shop.orders", name="Orders", description="Orders in the period",
            category=Category.PRODUCT, resolver=orders, permission="reports.read",
            entitlement="reporting.basic", metrics=("orders_total",),
            filters=(DATE_RANGE,), default_visualization=Visualization.LINE,
            visualizations=(Visualization.KPI, Visualization.LINE, Visualization.TABLE),
        ),
    ]
"""

from __future__ import annotations

from koras_reporting import MetricDefinition, ReportDefinition

METRICS: list[MetricDefinition] = []

REPORTS: list[ReportDefinition] = []
