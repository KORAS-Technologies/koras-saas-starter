"""The reporting routes, asked of the app with the reporting dependency replaced.

What is tested here is the boundary the router owns: that every route needs
a verified caller, that a report the caller may not have does not exist for
them, that a report the plan lacks is a commercial refusal, that a filter
the report did not declare is refused, that an export is gated twice and
recorded, and that a sensitive report is recorded when opened. The
framework's own behaviour -- the registries, the filter parser, the
visibility rule, the CSV writer -- is tested where it lives, in
`python-packages/koras-reporting`; the resolvers' statements in
`test_reporting_standard.py`.

The dependency is overridden with one built around a session that answers
every statement from a script, so no database and no platform are needed.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from fastapi.testclient import TestClient  # noqa: E402
from koras_api.core.auth import require_auth  # noqa: E402
from koras_api.core.reporting import (  # noqa: E402
    ReportingGrant,
    SqlAuditSink,
    TenantReporting,
    plan_from,
    tenant_reporting,
)
from koras_api.main import app  # noqa: E402
from koras_api.reporting import catalogue  # noqa: E402
from koras_auth import JWTClaims  # noqa: E402
from koras_auth.permissions import permissions_for  # noqa: E402
from koras_platform import OrganizationRole  # noqa: E402
from koras_reporting import Entitlement, Plan, ReportContext, Scope  # noqa: E402
from reporting_support import ScriptedSession  # noqa: E402

app.state.redis = None

TENANT = "00000000-0000-0000-0000-000000000001"


def plan(*codes: str, resolved: bool = True) -> Plan:
    return Plan(
        resolved=resolved,
        code="pro" if resolved else None,
        status="active" if resolved else None,
        entitlements={code: Entitlement(enabled=True) for code in codes},
    )


class Harness:
    def __init__(self, roles: frozenset[OrganizationRole], the_plan: Plan) -> None:
        self.session = ScriptedSession()
        self.roles = roles
        self.plan = the_plan
        self.capabilities: frozenset[str] = frozenset({"storage", "ai", "reporting"})

    def claims(self) -> JWTClaims:
        return JWTClaims(sub="user-1", roles=self.roles, organization_id="org-1")

    def reporting(self) -> TenantReporting:
        context = ReportContext(
            scope=Scope.TENANT,
            user_id="user-1",
            permissions=permissions_for(self.roles),
            plan=self.plan,
            session=self.session,
            tenant_id=TENANT,
            organization_id="org-1",
            product_code="sample",
            now=datetime(2026, 9, 14, 12, tzinfo=UTC),
        )
        return TenantReporting(
            context=context,
            grant=ReportingGrant(self.plan),
            catalogue=catalogue,
            capabilities=self.capabilities,
            audit=SqlAuditSink(self.session, TENANT),  # type: ignore[arg-type]
        )


def _install(harness: Harness) -> TestClient:
    app.dependency_overrides[tenant_reporting] = harness.reporting
    app.dependency_overrides[require_auth] = harness.claims
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


OWNER = frozenset({OrganizationRole.OWNER})
MEMBER = frozenset({OrganizationRole.MEMBER})
BILLING = frozenset({OrganizationRole.BILLING_ADMIN})


def keys(body: dict[str, Any]) -> dict[str, str]:
    return {row["key"]: row["visibility"] for row in body["reports"]}


def test_every_route_needs_a_verified_caller() -> None:
    app.dependency_overrides.clear()
    client = TestClient(app)
    for path in ("/api/v1/reports", "/api/v1/reports/usage.overview/data", "/api/v1/metrics"):
        assert client.get(path).status_code in (401, 403), path


def test_a_member_sees_the_basic_reports_and_no_sensitive_one() -> None:
    client = _install(Harness(MEMBER, plan("reporting.basic", "reporting.advanced")))
    listed = keys(client.get("/api/v1/reports").json())
    assert listed["usage.overview"] == "available"
    assert listed["usage.quotas"] == "available"
    assert listed["billing.subscription"] == "available"
    # Hidden by permission, not locked: a member is not told these exist.
    assert "people.users" not in listed
    assert "activity.audit" not in listed
    assert client.get("/api/v1/reports/people.users").status_code == 404
    assert client.get("/api/v1/reports/people.users/data").status_code == 404


def test_an_owner_sees_advanced_reports_locked_when_the_plan_lacks_them() -> None:
    client = _install(Harness(OWNER, plan("reporting.basic")))
    listed = keys(client.get("/api/v1/reports").json())
    assert listed["people.users"] == "locked"
    assert listed["activity.audit"] == "locked"
    answer = client.get("/api/v1/reports/people.users/data")
    assert answer.status_code == 402
    assert "reporting.advanced" in answer.json()["detail"]


def test_a_report_whose_capability_was_not_generated_does_not_exist() -> None:
    harness = Harness(OWNER, plan("reporting.basic", "reporting.advanced"))
    harness.capabilities = frozenset({"storage", "reporting"})
    client = _install(harness)
    listed = keys(client.get("/api/v1/reports").json())
    assert "ai.usage" not in listed
    if "ai.usage" in catalogue.reports:
        assert client.get("/api/v1/reports/ai.usage").status_code == 404


def test_an_unresolved_plan_still_answers_the_basic_reports() -> None:
    client = _install(Harness(OWNER, plan(resolved=False)))
    body = client.get("/api/v1/reports").json()
    assert body["resolved"] is False
    listed = keys(body)
    assert listed["usage.overview"] == "available"
    assert listed["people.users"] == "locked"
    answer = client.get("/api/v1/reports/usage.overview/data")
    assert answer.status_code == 200, answer.text
    assert answer.json()["resolved"] is False
    # A download leaves the product, so it waits for a plan that answered.
    assert client.get("/api/v1/reports/usage.overview/export").status_code == 402


def test_the_data_carries_metrics_series_and_a_bounded_range() -> None:
    harness = Harness(OWNER, plan("reporting.basic", "reporting.advanced"))
    client = _install(harness)
    answer = client.get("/api/v1/reports/usage.overview/data?from=2026-09-01&to=2026-09-14")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["key"] == "usage.overview"
    assert body["range"] == {"start": "2026-09-01", "end": "2026-09-14", "bucket": "day"}
    assert {m["key"] for m in body["metrics"]} >= {"members_total", "files_total", "active_users"}
    assert body["series"][0]["key"] == "activity_events"
    # Every statement the resolver ran bound this tenant, policies or not.
    assert harness.session.statements
    assert all(p.get("tenant_id") == TENANT for _, p in harness.session.statements if p)


def test_filters_the_report_did_not_declare_are_refused() -> None:
    client = _install(Harness(OWNER, plan("reporting.basic", "reporting.advanced")))
    answer = client.get("/api/v1/reports/usage.overview/data?tenant_id=other")
    assert answer.status_code == 422
    assert "does not accept: tenant_id" in answer.json()["detail"]
    answer = client.get("/api/v1/reports/activity.audit/data?outcome=ok'%20or%201=1")
    assert answer.status_code == 422
    answer = client.get("/api/v1/reports/usage.overview/data?from=2020-01-01&to=2026-09-14")
    assert answer.status_code == 422
    assert "366" in answer.json()["detail"]


def test_opening_a_sensitive_report_is_recorded() -> None:
    harness = Harness(OWNER, plan("reporting.basic", "reporting.advanced"))
    client = _install(harness)
    answer = client.get("/api/v1/reports/activity.audit/data?outcome=ok&limit=5")
    assert answer.status_code == 200, answer.text
    recorded = harness.session.inserted("audit_events")
    assert [r["action"] for r in recorded] == ["report.viewed"]
    assert recorded[0]["target_id"] == "activity.audit"
    assert recorded[0]["actor_id"] == "user-1"
    assert recorded[0]["tenant_id"] == TENANT
    # And a basic one is not: the record is for reports about people.
    harness.session.clear()
    client.get("/api/v1/reports/usage.overview/data")
    assert harness.session.inserted("audit_events") == []


def test_export_is_gated_by_permission_then_plan_and_recorded() -> None:
    # A member holds reports.read and not reports.export.
    client = _install(Harness(MEMBER, plan("reporting.basic", "reporting.export")))
    assert client.get("/api/v1/reports/usage.quotas/export").status_code == 403

    # A billing administrator may export; the plan has to include it.
    client = _install(Harness(BILLING, plan("reporting.basic")))
    answer = client.get("/api/v1/reports/usage.quotas/export")
    assert answer.status_code == 402
    assert "reporting.export" in answer.json()["detail"]

    harness = Harness(BILLING, plan("reporting.basic", "reporting.export"))
    client = _install(harness)
    answer = client.get("/api/v1/reports/usage.quotas/export?from=2026-09-01&to=2026-09-14")
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"].startswith("text/csv")
    assert (
        'filename="usage-quotas-2026-09-01-to-2026-09-14.csv"'
        in answer.headers["content-disposition"]
    )
    assert answer.text.splitlines()[0] == "Quota,Used,Included,Remaining,Used %"
    recorded = harness.session.inserted("audit_events")
    assert [r["action"] for r in recorded] == ["report.exported"]
    assert recorded[0]["outcome"] == "ok"


def test_the_definition_says_whether_this_caller_may_export() -> None:
    client = _install(Harness(OWNER, plan("reporting.basic")))
    body = client.get("/api/v1/reports/usage.quotas").json()
    assert body["can_export"] is False
    assert [f["key"] for f in body["filters"]] == ["date_range"]
    client = _install(Harness(OWNER, plan("reporting.basic", "reporting.export")))
    assert client.get("/api/v1/reports/usage.quotas").json()["can_export"] is True
    client = _install(Harness(MEMBER, plan("reporting.basic", "reporting.export")))
    assert client.get("/api/v1/reports/usage.quotas").json()["can_export"] is False


def test_the_metric_registry_is_listed() -> None:
    client = _install(Harness(MEMBER, plan("reporting.basic")))
    body = client.get("/api/v1/metrics").json()
    listed = {m["key"]: m for m in body["metrics"]}
    assert listed["members_total"]["unit"] == "count"
    assert listed["storage_used_bytes"]["format"] == "bytes"


def test_the_portal_answer_becomes_a_plan() -> None:
    from koras_api.core.platform import PortalAnswer

    assert plan_from(None).resolved is False
    nothing = plan_from(PortalAnswer(None))
    assert nothing.resolved is True and nothing.entitlements == {}
    parsed = plan_from(
        PortalAnswer(
            {
                "plan_code": "pro",
                "status": "trialing",
                "trial_ends_at": "2026-10-01T00:00:00Z",
                "entitlements": [
                    {"code": "reporting.basic", "enabled": True, "limit_value": None},
                    {"code": "seats", "enabled": True, "limit_value": 25},
                    {"code": "reporting.export", "enabled": False, "limit_value": None},
                    "not a row",
                ],
            }
        )
    )
    assert parsed.code == "pro"
    assert parsed.status == "trialing"
    assert parsed.trial_ends_at is not None and parsed.trial_ends_at.tzinfo is not None
    assert parsed.includes("reporting.basic")
    assert parsed.limit_of("seats") == 25
    assert not parsed.includes("reporting.export")
    grant = ReportingGrant(parsed)
    assert grant.entitled("reporting.basic") and not grant.can_export
    unresolved = ReportingGrant(Plan(resolved=False))
    assert unresolved.entitled("reporting.basic") and not unresolved.entitled("reporting.advanced")
