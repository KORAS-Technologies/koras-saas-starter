"""The Koras reporting framework: definitions, registries, filters, the
authorization rule, the result shape and the CSV writer.

Runs no query and holds no driver. A product's API and the Control Plane's
API each build a catalogue from their own definitions and hand each
resolver their own session; what they share is the vocabulary a report is
described in and the rule that decides who may open one.
"""

from .authorization import Visibility, visibility_for
from .context import UNRESOLVED_PLAN, Entitlement, Plan, ReportContext
from .definitions import (
    DATE_RANGE,
    Aggregation,
    Category,
    ExportFormat,
    FilterDefinition,
    FilterKind,
    Format,
    MetricDefinition,
    ReportDefinition,
    Resolver,
    Scope,
    Status,
    Unit,
    Visualization,
)
from .export import EXPORT_ROW_LIMIT, export_filename, to_csv
from .filters import (
    DEFAULT_RANGE_DAYS,
    EMPTY_FILTERS,
    MAX_RANGE_DAYS,
    Bucket,
    DateRange,
    FilterError,
    ResolvedFilters,
    resolve_filters,
)
from .registry import MetricRegistry, ReportingCatalogue, ReportRegistry, build_catalogue
from .results import (
    Cell,
    Kind,
    MetricValue,
    RangeView,
    ReportResult,
    Series,
    SeriesPoint,
    Table,
    TableColumn,
)

__all__ = [
    "DATE_RANGE",
    "DEFAULT_RANGE_DAYS",
    "EMPTY_FILTERS",
    "EXPORT_ROW_LIMIT",
    "MAX_RANGE_DAYS",
    "UNRESOLVED_PLAN",
    "Aggregation",
    "Bucket",
    "Category",
    "Cell",
    "DateRange",
    "Entitlement",
    "ExportFormat",
    "FilterDefinition",
    "FilterError",
    "FilterKind",
    "Format",
    "Kind",
    "MetricDefinition",
    "MetricRegistry",
    "MetricValue",
    "Plan",
    "RangeView",
    "ReportContext",
    "ReportDefinition",
    "ReportRegistry",
    "ReportResult",
    "ReportingCatalogue",
    "ResolvedFilters",
    "Resolver",
    "Scope",
    "Series",
    "SeriesPoint",
    "Status",
    "Table",
    "TableColumn",
    "Unit",
    "Visibility",
    "Visualization",
    "build_catalogue",
    "export_filename",
    "resolve_filters",
    "to_csv",
    "visibility_for",
]
