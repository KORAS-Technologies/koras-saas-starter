"""The registries, and the one catalogue a service builds from them.

Built once at import. A duplicate key or a report naming a metric nobody
registered is an error at import, where it is a traceback, rather than at
request time, where it is a 500 for a customer.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from .definitions import Category, MetricDefinition, ReportDefinition


class MetricRegistry:
    def __init__(self) -> None:
        self._metrics: dict[str, MetricDefinition] = {}

    def add(self, metric: MetricDefinition) -> None:
        if metric.key in self._metrics:
            raise ValueError(f"metric {metric.key!r} is registered twice")
        self._metrics[metric.key] = metric

    def get(self, key: str) -> MetricDefinition | None:
        return self._metrics.get(key)

    def __contains__(self, key: str) -> bool:
        return key in self._metrics

    def __iter__(self) -> Iterator[MetricDefinition]:
        return iter(sorted(self._metrics.values(), key=lambda m: m.key))

    def __len__(self) -> int:
        return len(self._metrics)


_CATEGORY_ORDER: dict[Category, int] = {category: index for index, category in enumerate(Category)}


class ReportRegistry:
    def __init__(self, metrics: MetricRegistry) -> None:
        self._metrics = metrics
        self._reports: dict[str, ReportDefinition] = {}

    def add(self, report: ReportDefinition) -> None:
        if report.key in self._reports:
            raise ValueError(f"report {report.key!r} is registered twice")
        missing = [key for key in report.metrics if key not in self._metrics]
        if missing:
            raise ValueError(f"report {report.key!r} names unregistered metrics: {missing}")
        self._reports[report.key] = report

    def get(self, key: str) -> ReportDefinition | None:
        return self._reports.get(key)

    def __contains__(self, key: str) -> bool:
        return key in self._reports

    def __iter__(self) -> Iterator[ReportDefinition]:
        return iter(
            sorted(
                self._reports.values(),
                key=lambda r: (_CATEGORY_ORDER.get(r.category, 99), r.order, r.key),
            )
        )

    def __len__(self) -> int:
        return len(self._reports)


class ReportingCatalogue:
    """Everything one service can report on, built once."""

    def __init__(self, metrics: MetricRegistry, reports: ReportRegistry) -> None:
        self.metrics = metrics
        self.reports = reports


def build_catalogue(
    metrics: Iterable[MetricDefinition],
    reports: Iterable[ReportDefinition],
) -> ReportingCatalogue:
    metric_registry = MetricRegistry()
    for metric in metrics:
        metric_registry.add(metric)
    report_registry = ReportRegistry(metric_registry)
    for report in reports:
        report_registry.add(report)
    return ReportingCatalogue(metric_registry, report_registry)
