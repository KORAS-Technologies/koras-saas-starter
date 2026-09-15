"""Filters, from a query string to typed values a resolver may bind.

A report declares what it accepts. Anything else in the query is refused
rather than ignored, because a filter that is silently dropped is a filter
the caller believes applied. A date range is bounded and defaulted here, so
no resolver can be asked to scan without limit, and the bucket a range is
drawn in is decided here too, from a closed set a resolver may interpolate
into a `date_trunc` without ever interpolating what a caller typed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from .definitions import FilterDefinition, FilterKind, ReportDefinition

#: How far back one call may ask. A year of days is a small answer; a
#: report that wants more wants pre-aggregation, which is a follow-up.
MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 30

Bucket = Literal["day", "week", "month"]


class FilterError(ValueError):
    """A filter the report does not accept, or a value of the wrong shape."""


@dataclass(frozen=True)
class DateRange:
    """Inclusive calendar days, in UTC."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise FilterError("the range ends before it starts")
        if self.days > MAX_RANGE_DAYS:
            raise FilterError(f"the range may cover at most {MAX_RANGE_DAYS} days")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def start_at(self) -> datetime:
        return datetime.combine(self.start, time.min, tzinfo=UTC)

    @property
    def end_at(self) -> datetime:
        """The first instant after the range, for a half-open comparison."""
        return datetime.combine(self.end + timedelta(days=1), time.min, tzinfo=UTC)

    @property
    def bucket(self) -> Bucket:
        """The granularity a series is drawn in. One of three fixed words."""
        if self.days <= 31:
            return "day"
        if self.days <= 183:
            return "week"
        return "month"

    @property
    def previous(self) -> DateRange:
        """The same length of time immediately before, for a comparison."""
        return DateRange(self.start - timedelta(days=self.days), self.start - timedelta(days=1))

    @staticmethod
    def last(days: int, *, today: date | None = None) -> DateRange:
        end = today or datetime.now(UTC).date()
        return DateRange(end - timedelta(days=days - 1), end)


@dataclass(frozen=True)
class ResolvedFilters:
    range: DateRange | None
    values: Mapping[str, str | int]

    def choice(self, key: str) -> str | None:
        value = self.values.get(key)
        return value if isinstance(value, str) else None

    def integer(self, key: str) -> int | None:
        value = self.values.get(key)
        return value if isinstance(value, int) else None


EMPTY_FILTERS = ResolvedFilters(range=None, values={})


def _parse_date(raw: str, name: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as error:
        raise FilterError(f"{name} is not a date") from error


def resolve_filters(
    definition: ReportDefinition,
    query: Mapping[str, str],
    *,
    today: date | None = None,
) -> ResolvedFilters:
    """Turn a query mapping into what the report declared, or refuse."""
    accepted = {"from", "to"} if definition.accepts_date_range else set()
    accepted |= {f.key for f in definition.filters if f.kind is not FilterKind.DATE_RANGE}
    unknown = sorted(key for key in query if key not in accepted)
    if unknown:
        raise FilterError(f"this report does not accept: {', '.join(unknown)}")

    date_range: DateRange | None = None
    if definition.accepts_date_range:
        raw_to = query.get("to")
        raw_from = query.get("from")
        end = _parse_date(raw_to, "to") if raw_to else (today or datetime.now(UTC).date())
        start = (
            _parse_date(raw_from, "from")
            if raw_from
            else end - timedelta(days=DEFAULT_RANGE_DAYS - 1)
        )
        date_range = DateRange(start, end)

    values: dict[str, str | int] = {}
    for spec in definition.filters:
        if spec.kind is FilterKind.DATE_RANGE:
            continue
        raw = query.get(spec.key)
        if raw is None or raw == "":
            if spec.default is not None:
                values[spec.key] = spec.default
            continue
        values[spec.key] = _coerce(spec, raw)
    return ResolvedFilters(range=date_range, values=values)


def _coerce(spec: FilterDefinition, raw: str) -> str | int:
    if spec.kind is FilterKind.CHOICE:
        if raw not in spec.options:
            raise FilterError(f"{spec.key} must be one of: {', '.join(spec.options)}")
        return raw
    if spec.kind is FilterKind.INTEGER:
        try:
            value = int(raw)
        except ValueError as error:
            raise FilterError(f"{spec.key} must be a whole number") from error
        if spec.minimum is not None and value < spec.minimum:
            raise FilterError(f"{spec.key} must be at least {spec.minimum}")
        if spec.maximum is not None and value > spec.maximum:
            raise FilterError(f"{spec.key} must be at most {spec.maximum}")
        return value
    raise FilterError(f"{spec.key} has a kind this build cannot parse")
