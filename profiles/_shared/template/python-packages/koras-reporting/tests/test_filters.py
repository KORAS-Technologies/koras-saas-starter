"""Filters reach a resolver typed, bounded, and only when declared."""

from __future__ import annotations

from datetime import date

import pytest
from koras_reporting import (
    DATE_RANGE,
    DEFAULT_RANGE_DAYS,
    MAX_RANGE_DAYS,
    Category,
    DateRange,
    FilterDefinition,
    FilterError,
    FilterKind,
    ReportContext,
    ReportDefinition,
    ReportResult,
    ResolvedFilters,
    resolve_filters,
)

TODAY = date(2026, 9, 14)


async def _answer(context: ReportContext, filters: ResolvedFilters) -> ReportResult:
    return ReportResult(key="a.b", generated_at=context.now)


STATUS = FilterDefinition(
    key="status", kind=FilterKind.CHOICE, label="Status", options=("open", "closed")
)
LIMIT = FilterDefinition(
    key="limit", kind=FilterKind.INTEGER, label="Rows", default=10, minimum=1, maximum=100
)

REPORT = ReportDefinition(
    key="a.b",
    name="A",
    description="B",
    category=Category.PRODUCT,
    resolver=_answer,
    permission="reports.read",
    filters=(DATE_RANGE, STATUS, LIMIT),
)
NO_RANGE = ReportDefinition(
    key="a.c",
    name="A",
    description="C",
    category=Category.PRODUCT,
    resolver=_answer,
    permission="reports.read",
)


def test_the_default_range_is_the_last_thirty_days() -> None:
    resolved = resolve_filters(REPORT, {}, today=TODAY)
    assert resolved.range is not None
    assert resolved.range.end == TODAY
    assert resolved.range.days == DEFAULT_RANGE_DAYS
    assert resolved.range.bucket == "day"
    # The integer default applies; the choice has none and is absent.
    assert resolved.integer("limit") == 10
    assert resolved.choice("status") is None


def test_an_undeclared_filter_is_refused_not_ignored() -> None:
    with pytest.raises(FilterError, match="does not accept: tenant_id"):
        resolve_filters(REPORT, {"tenant_id": "other"}, today=TODAY)
    with pytest.raises(FilterError, match="does not accept: from"):
        resolve_filters(NO_RANGE, {"from": "2026-01-01"}, today=TODAY)


def test_a_choice_admits_only_its_options() -> None:
    assert resolve_filters(REPORT, {"status": "open"}, today=TODAY).choice("status") == "open"
    with pytest.raises(FilterError, match="must be one of"):
        resolve_filters(REPORT, {"status": "open' or 1=1"}, today=TODAY)


def test_an_integer_is_bounded() -> None:
    assert resolve_filters(REPORT, {"limit": "5"}, today=TODAY).integer("limit") == 5
    with pytest.raises(FilterError, match="at most 100"):
        resolve_filters(REPORT, {"limit": "1000"}, today=TODAY)
    with pytest.raises(FilterError, match="at least 1"):
        resolve_filters(REPORT, {"limit": "0"}, today=TODAY)
    with pytest.raises(FilterError, match="whole number"):
        resolve_filters(REPORT, {"limit": "ten"}, today=TODAY)


def test_a_range_is_bounded_and_buckets_by_length() -> None:
    with pytest.raises(FilterError, match=f"at most {MAX_RANGE_DAYS}"):
        resolve_filters(REPORT, {"from": "2020-01-01", "to": "2026-09-14"}, today=TODAY)
    with pytest.raises(FilterError, match="ends before it starts"):
        resolve_filters(REPORT, {"from": "2026-09-14", "to": "2026-09-01"}, today=TODAY)
    with pytest.raises(FilterError, match="not a date"):
        resolve_filters(REPORT, {"from": "yesterday"}, today=TODAY)

    assert DateRange(date(2026, 1, 1), date(2026, 1, 31)).bucket == "day"
    assert DateRange(date(2026, 1, 1), date(2026, 6, 30)).bucket == "week"
    assert DateRange(date(2025, 10, 1), date(2026, 9, 14)).bucket == "month"


def test_the_previous_range_is_the_same_length_immediately_before() -> None:
    current = DateRange(date(2026, 9, 1), date(2026, 9, 14))
    assert current.previous == DateRange(date(2026, 8, 18), date(2026, 8, 31))
    assert current.end_at.isoformat() == "2026-09-15T00:00:00+00:00"
