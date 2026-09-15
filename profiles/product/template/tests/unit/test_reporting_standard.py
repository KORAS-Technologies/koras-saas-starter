"""The six standard resolvers, run against a scripted session.

Each is asked for its answer and checked for two things: that the shape a
page renders is there -- the metrics it declares, a series, a table where
one is promised -- and that every statement it ran bound the tenant and
the range, so a resolver copied into a product still says what it reads.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_api.reporting import catalogue, standard  # noqa: E402
from koras_reporting import (  # noqa: E402
    DateRange,
    Entitlement,
    Plan,
    ReportContext,
    ReportDefinition,
    ResolvedFilters,
    Scope,
    resolve_filters,
)
from reporting_support import ScriptedSession  # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
RANGE = DateRange(date(2026, 9, 1), date(2026, 9, 14))
PLAN = Plan(
    resolved=True,
    code="pro",
    status="active",
    trial_ends_at=None,
    period_ends_at=datetime(2026, 10, 1, tzinfo=UTC),
    entitlements={
        "reporting.basic": Entitlement(enabled=True),
        "seats": Entitlement(enabled=True, limit=10),
        "storage.files": Entitlement(enabled=True, limit=5),
        "ai.requests": Entitlement(enabled=True, limit=1000),
    },
)


def context(session: ScriptedSession, plan: Plan = PLAN) -> ReportContext:
    return ReportContext(
        scope=Scope.TENANT,
        user_id="user-1",
        permissions=frozenset({"reports.read", "reports.sensitive", "reports.export"}),
        plan=plan,
        session=session,
        tenant_id=TENANT,
        organization_id="org-1",
        product_code="sample",
        now=datetime(2026, 9, 14, 12, tzinfo=UTC),
    )


def _bound_everywhere(session: ScriptedSession) -> None:
    reads = [(sql, p) for sql, p in session.statements if sql.startswith("select")]
    assert reads, "the resolver read nothing"
    # A resolver reads the range and the same length before it, for a trend.
    windows = {
        (RANGE.start_at, RANGE.end_at),
        (RANGE.previous.start_at, RANGE.previous.end_at),
    }
    for sql, params in reads:
        assert params is not None and params.get("tenant_id") == TENANT, sql
        if ":start" in sql:
            assert (params["start"], params["end"]) in windows, sql


def _definition(key: str) -> ReportDefinition:
    definition = catalogue.reports.get(key)
    assert definition is not None, key
    return definition


@pytest.mark.parametrize(
    "key",
    ["usage.overview", "usage.quotas", "people.users", "activity.audit"],
)
async def test_every_ranged_report_binds_the_tenant_and_the_range(key: str) -> None:
    session = ScriptedSession()
    definition = _definition(key)
    filters = resolve_filters(definition, {"from": "2026-09-01", "to": "2026-09-14"})
    result = await definition.resolver(context(session), filters)
    assert result.key == key
    assert result.range is not None and result.range.bucket == "day"
    declared = set(definition.metrics)
    answered = {m.key for m in result.metrics}
    assert answered & declared, f"{key} answered none of the metrics it declares"
    _bound_everywhere(session)


async def test_the_overview_reports_quotas_with_the_plan_limits() -> None:
    session = ScriptedSession()
    result = await standard.overview(context(session), ResolvedFilters(RANGE, {}))
    by_key = {m.key: m for m in result.metrics}
    assert by_key["members_total"].value == 4 and by_key["members_total"].limit == 10
    assert by_key["storage_used_bytes"].limit == 5 * 1024**3
    assert by_key["members_joined"].previous == 1
    assert result.series[0].points[0].x == "2026-09-01"
    assert result.notes == []

    unresolved = await standard.overview(
        context(ScriptedSession(), Plan(resolved=False)), ResolvedFilters(RANGE, {})
    )
    assert unresolved.resolved is False
    assert {m.key: m.limit for m in unresolved.metrics}["members_total"] is None
    assert unresolved.notes


async def test_the_quota_table_says_used_included_remaining_and_percent() -> None:
    result = await standard.quotas(context(ScriptedSession()), ResolvedFilters(RANGE, {}))
    assert result.table is not None
    rows = {row["quota"]: row for row in result.table.rows}
    assert rows["Seats"] == {
        "quota": "Seats",
        "used": 4.0,
        "included": 10.0,
        "remaining": 6.0,
        "percent": 40.0,
    }
    assert rows["Files"]["included"] is None and rows["Files"]["percent"] is None


async def test_users_is_broken_down_by_role_as_a_bar_and_a_table() -> None:
    result = await standard.users(context(ScriptedSession()), ResolvedFilters(RANGE, {}))
    assert result.visualization == "bar"
    by_role = next(s for s in result.series if s.key == "members_total")
    assert [(p.x, p.y) for p in by_role.points] == [("member", 3.0), ("organization_owner", 1.0)]
    assert result.table is not None and result.table.rows[0] == {"role": "member", "value": 3}


async def test_subscription_lists_the_plan_and_names_the_portal() -> None:
    result = await standard.subscription(context(ScriptedSession()), ResolvedFilters(None, {}))
    assert result.table is not None
    items = {row["item"]: row["value"] for row in result.table.rows}
    assert items["Plan"] == "pro" and items["Status"] == "active"
    assert items["Current period ends"] == "2026-10-01"
    assert items["seats"] == "included, up to 10"
    assert any("billing page" in note for note in result.notes)
    assert result.range is None


async def test_activity_honours_the_outcome_filter_after_the_bounded_read() -> None:
    session = ScriptedSession()
    definition = _definition("activity.audit")
    filters = resolve_filters(
        definition, {"from": "2026-09-01", "to": "2026-09-14", "outcome": "denied", "limit": "5"}
    )
    result = await standard.activity(context(session), filters)
    assert result.table is not None
    assert [row["outcome"] for row in result.table.rows] == ["denied"]
    recent = next(sql for sql, _ in session.statements if "order by created_at desc" in sql)
    assert ":limit" in recent
    bound = next(p for sql, p in session.statements if "order by created_at desc" in sql)
    assert bound is not None and bound["limit"] == 5
    by_action = next(s for s in result.series if s.key == "activity_by_action")
    assert [p.x for p in by_action.points] == ["report.viewed (denied)"]


async def test_ai_usage_is_aggregates_only_when_the_capability_exists() -> None:
    if not hasattr(standard, "ai_usage"):
        pytest.skip("generated without the ai capability")
    session = ScriptedSession()
    result = await standard.ai_usage(context(session), ResolvedFilters(RANGE, {}))
    by_key = {m.key: m for m in result.metrics}
    assert by_key["ai_requests"].value == 3 and by_key["ai_errors"].value == 1
    assert by_key["ai_estimated_cost"].kind == "estimated"
    assert result.notes and "carried no price" in result.notes[0]
    assert result.table is not None
    row = result.table.rows[0]
    assert row["model"] == "gpt-4o-mini" and "user_id" not in row and "content" not in row
    for sql, _ in session.statements:
        assert "content" not in sql and "conversation_id" not in sql
    _bound_everywhere(session)


def test_the_catalogue_is_built_and_every_standard_metric_is_registered() -> None:
    assert len(catalogue.reports) >= 5
    for definition in catalogue.reports:
        for key in definition.metrics:
            assert key in catalogue.metrics, f"{definition.key} names {key}"
