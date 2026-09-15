"""What a metric, a filter and a report are, before any of them has a value.

Definitions are code. A product declares them at import the way it declares
agents, tools and navigation modules, and the registry refuses what does
not fit: a metric nobody defined, a filter kind the framework cannot parse,
a default visualization the report does not offer. Nothing here knows about
a table or a tenant; the resolver a definition carries is where the query
lives, and the context it is handed is what scopes it.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import ReportContext
    from .filters import ResolvedFilters
    from .results import ReportResult

_SNAKE = re.compile(r"[a-z][a-z0-9]*(_[a-z0-9]+)*")
_DOTTED = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+")


class Unit(StrEnum):
    COUNT = "count"
    BYTES = "bytes"
    #: Millionths of a US dollar, the unit `ai_usage_events` already uses.
    MICROS = "micros"
    MILLISECONDS = "milliseconds"
    SECONDS = "seconds"
    PERCENT = "percent"


class Format(StrEnum):
    INTEGER = "integer"
    DECIMAL = "decimal"
    BYTES = "bytes"
    MONEY = "money"
    DURATION = "duration"
    PERCENT = "percent"


class Aggregation(StrEnum):
    SUM = "sum"
    COUNT = "count"
    AVERAGE = "average"
    MAX = "max"
    #: The value as of the end of the range: a balance, a member count.
    LATEST = "latest"


class Scope(StrEnum):
    #: Over one tenant's rows, on the tenant session.
    TENANT = "tenant"
    #: Over the estate, as a platform role.
    PLATFORM = "platform"


class Category(StrEnum):
    OVERVIEW = "overview"
    USAGE = "usage"
    PEOPLE = "people"
    BILLING = "billing"
    AI = "ai"
    ACTIVITY = "activity"
    #: A product's own domain: orders, cases, appointments.
    PRODUCT = "product"
    #: Platform-only categories, used by the Control Plane's catalogue.
    REVENUE = "revenue"
    CUSTOMERS = "customers"
    PROVISIONING = "provisioning"
    RELIABILITY = "reliability"
    SECURITY = "security"


class Visualization(StrEnum):
    KPI = "kpi"
    LINE = "line"
    BAR = "bar"
    TABLE = "table"


class ExportFormat(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"
    PDF = "pdf"


class Status(StrEnum):
    AVAILABLE = "available"
    PREVIEW = "preview"
    DEPRECATED = "deprecated"


class FilterKind(StrEnum):
    #: `from` and `to` dates, bounded; see `filters.py`.
    DATE_RANGE = "date_range"
    #: One of the declared options, and nothing else.
    CHOICE = "choice"
    #: A bounded integer.
    INTEGER = "integer"


@dataclass(frozen=True)
class MetricDefinition:
    """A name with a unit and a meaning.

    The calculation is the resolver's; the definition is what lets two
    reports say `ai_requests` and mean the same thing, what a card formats
    against, and what a warehouse would list.
    """

    key: str
    name: str
    description: str
    unit: Unit
    format: Format
    aggregation: Aggregation
    scope: Scope = Scope.TENANT
    dimensions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _SNAKE.fullmatch(self.key):
            raise ValueError(f"metric key {self.key!r} is not snake_case")


@dataclass(frozen=True)
class FilterDefinition:
    """One filter a report accepts.

    A choice carries its options and admits nothing outside them; an integer
    carries its bounds. There is no free-text kind, which is what keeps a
    filter value from ever reaching a query as anything but a bound
    parameter of a known shape.
    """

    key: str
    kind: FilterKind
    label: str
    options: tuple[str, ...] = ()
    default: str | int | None = None
    minimum: int | None = None
    maximum: int | None = None

    def __post_init__(self) -> None:
        if not _SNAKE.fullmatch(self.key):
            raise ValueError(f"filter key {self.key!r} is not snake_case")
        if self.kind is FilterKind.CHOICE and not self.options:
            raise ValueError(f"filter {self.key!r} is a choice with no options")
        if self.kind is FilterKind.CHOICE and self.default is not None:
            if self.default not in self.options:
                raise ValueError(f"filter {self.key!r} defaults to a value it does not offer")
        if self.kind is FilterKind.INTEGER and self.default is not None:
            if not isinstance(self.default, int):
                raise ValueError(f"filter {self.key!r} is an integer with a non-integer default")


DATE_RANGE = FilterDefinition(key="date_range", kind=FilterKind.DATE_RANGE, label="Period")

Resolver = Callable[["ReportContext", "ResolvedFilters"], Awaitable["ReportResult"]]


@dataclass(frozen=True)
class ReportDefinition:
    """One report: what it is, who may open it, what it accepts, who answers it."""

    key: str
    name: str
    description: str
    category: Category
    resolver: Resolver
    #: The product permission that opens it, or a platform role for the
    #: Control Plane's catalogue. Checked by the router before anything runs.
    permission: str
    #: The platform entitlement that includes it; None means always included.
    entitlement: str | None = None
    metrics: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    filters: tuple[FilterDefinition, ...] = ()
    default_visualization: Visualization = Visualization.KPI
    visualizations: tuple[Visualization, ...] = (Visualization.KPI, Visualization.TABLE)
    export_formats: tuple[ExportFormat, ...] = (
        ExportFormat.CSV,
        ExportFormat.XLSX,
        ExportFormat.PDF,
    )
    cache_seconds: int = 0
    status: Status = Status.AVAILABLE
    version: int = 1
    #: The generated capability the report's data needs; None for none.
    capability: str | None = None
    #: Order within its category, for the list.
    order: int = 100
    #: Recorded to the audit table when opened. For reports about people.
    sensitive: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not _DOTTED.fullmatch(self.key):
            raise ValueError(f"report key {self.key!r} is not dotted lower case")
        if self.default_visualization not in self.visualizations:
            raise ValueError(
                f"report {self.key!r} defaults to {self.default_visualization} "
                "but does not offer it"
            )
        if self.cache_seconds < 0:
            raise ValueError(f"report {self.key!r} has a negative cache")
        keys = [f.key for f in self.filters]
        if len(keys) != len(set(keys)):
            raise ValueError(f"report {self.key!r} declares a filter twice")

    def filter(self, key: str) -> FilterDefinition | None:
        for definition in self.filters:
            if definition.key == key:
                return definition
        return None

    @property
    def accepts_date_range(self) -> bool:
        return any(f.kind is FilterKind.DATE_RANGE for f in self.filters)
