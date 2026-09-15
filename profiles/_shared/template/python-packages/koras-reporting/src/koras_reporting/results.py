"""What a report answers: numbers with units, series, rows, and what kind of
number each one is.

Pydantic, because this is the API's response model and the export's input,
and both need one shape. `kind` on a metric is the honesty field: a figure
the system computed from its own rows is `actual`; one it estimated from a
price list is `estimated`; one it derived from other figures is `derived`;
and one it could not obtain is `unavailable`, with the value null and never
zero, because zero is a number.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .definitions import Format, Unit, Visualization

Kind = Literal["actual", "estimated", "derived", "unavailable"]
Cell = str | int | float | None


class MetricValue(BaseModel):
    key: str
    label: str
    value: float | None
    unit: Unit
    format: Format
    kind: Kind = "actual"
    #: The plan's ceiling for a quota, so a card can say used of included.
    limit: float | None = None
    #: The same figure over the previous period, for a trend.
    previous: float | None = None
    note: str | None = None


class SeriesPoint(BaseModel):
    #: The bucket's first day, ISO; or a category label for a bar chart.
    x: str
    y: float | None


class Series(BaseModel):
    key: str
    label: str
    unit: Unit
    format: Format
    points: list[SeriesPoint]
    kind: Kind = "actual"


class TableColumn(BaseModel):
    key: str
    label: str
    format: Format | None = None
    align: Literal["left", "right"] = "left"


class Table(BaseModel):
    columns: list[TableColumn]
    rows: list[dict[str, Cell]]
    #: True when more rows exist than were returned.
    truncated: bool = False


class RangeView(BaseModel):
    start: str
    end: str
    bucket: Literal["day", "week", "month"]


class ReportResult(BaseModel):
    key: str
    generated_at: datetime
    range: RangeView | None = None
    metrics: list[MetricValue] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)
    table: Table | None = None
    #: Sentences about the answer: what is estimated, what could not be read.
    notes: list[str] = Field(default_factory=list)
    visualization: Visualization = Visualization.KPI
    #: False when a source the report needed did not answer.
    resolved: bool = True
