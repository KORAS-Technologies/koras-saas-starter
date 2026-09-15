"""Export formats, background exports, and schedules, at the API's boundary.

The same harness as `test_reporting_api.py` with the tenant's storage
replaced by a fake bucket, so the after-response write, the download ticket
and the retirement can be asserted without a bucket. What is proved: three
formats answer the file they name; an export past the bound is 202 with an
id and lands in the bucket; a schedule takes the two export gates plus its
own entitlement, validates what the worker will trust, and is recorded; the
period filters are refused on a schedule because the cadence decides them.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from fastapi.testclient import TestClient  # noqa: E402
from koras_api.core import database  # noqa: E402
from koras_api.core.auth import require_auth  # noqa: E402
from koras_api.core.reporting import (  # noqa: E402
    ReportingGrant,
    SqlAuditSink,
    TenantReporting,
    tenant_reporting,
)
from koras_api.core.storage import StorageGrant, TenantStorage, tenant_storage  # noqa: E402
from koras_api.main import app  # noqa: E402
from koras_api.reporting import catalogue  # noqa: E402
from koras_api.routers import reporting as reporting_router  # noqa: E402
from koras_auth import JWTClaims  # noqa: E402
from koras_auth.permissions import permissions_for  # noqa: E402
from koras_platform import OrganizationRole  # noqa: E402
from koras_reporting import EXPORT_ROW_LIMIT, Entitlement, Plan, ReportContext, Scope  # noqa: E402
from koras_storage import Provider  # noqa: E402
from reporting_support import ScriptedSession  # noqa: E402

app.state.redis = None

TENANT = "00000000-0000-0000-0000-000000000001"


class FakeStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.deleted: list[str] = []

    def presign_upload(self, key: str, content_type: str, size: int, expires_in: int) -> str:
        return f"https://bucket.invalid/put/{key}"

    def presign_download(self, key: str, filename: str, expires_in: int) -> str:
        return f"https://bucket.invalid/get/{key}?name={filename}"

    def head(self, key: str) -> int | None:
        held = self.objects.get(key)
        return len(held[0]) if held else None

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = (content, content_type)

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


def plan(*codes: str) -> Plan:
    return Plan(
        resolved=True,
        code="premium",
        status="active",
        entitlements={code: Entitlement(enabled=True) for code in codes},
    )


ALL = ("reporting.basic", "reporting.advanced", "reporting.export", "reporting.scheduled")


class Harness:
    def __init__(self, roles: frozenset[OrganizationRole], the_plan: Plan) -> None:
        self.session = ScriptedSession()
        self.store = FakeStore()
        self.roles = roles
        self.plan = the_plan

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
            capabilities=frozenset({"storage", "ai", "reporting"}),
            audit=SqlAuditSink(self.session, TENANT),  # type: ignore[arg-type]
        )

    def storage(self) -> TenantStorage:
        return TenantStorage(
            store=self.store,
            provider=Provider.SUPABASE,
            bucket="bucket",
            grant=StorageGrant(enabled=True, limit_bytes=None, resolved=True),
        )


@pytest.fixture
def owner(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Harness, TestClient]]:
    harness = Harness(frozenset({OrganizationRole.OWNER}), plan(*ALL))
    app.dependency_overrides[tenant_reporting] = harness.reporting
    app.dependency_overrides[tenant_storage] = harness.storage
    app.dependency_overrides[require_auth] = harness.claims

    # The after-response write opens a session of its own; hand it the script.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def scripted(tenant_id: str) -> AsyncIterator[ScriptedSession]:
        assert tenant_id == TENANT
        yield harness.session

    monkeypatch.setattr(reporting_router, "tenant_session", scripted)
    monkeypatch.setattr(database, "tenant_session", scripted)
    try:
        yield harness, TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ── formats ──────────────────────────────────────────────────────────────────


def test_each_format_answers_the_file_it_names(owner: tuple[Harness, TestClient]) -> None:
    _harness, client = owner
    csv = client.get("/api/v1/reports/usage.quotas/export?format=csv")
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    xlsx = client.get("/api/v1/reports/usage.quotas/export?format=xlsx")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    assert 'filename="usage-quotas-' in xlsx.headers["content-disposition"]
    assert xlsx.headers["content-disposition"].endswith('.xlsx"')
    pdf = client.get("/api/v1/reports/usage.quotas/export?format=pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get("/api/v1/reports/usage.quotas/export?format=docx").status_code == 406


def test_the_definition_says_which_formats_and_whether_scheduling_is_open(
    owner: tuple[Harness, TestClient],
) -> None:
    _harness, client = owner
    body = client.get("/api/v1/reports/usage.quotas").json()
    assert body["export_formats"] == ["csv", "xlsx", "pdf"]
    assert body["can_export"] is True and body["can_schedule"] is True


# ── background exports ───────────────────────────────────────────────────────


def test_an_export_past_the_bound_lands_in_the_bucket_after_the_response(
    owner: tuple[Harness, TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    harness, client = owner
    monkeypatch.setattr(reporting_router, "EXPORT_ROW_LIMIT", 0)
    answer = client.get(
        "/api/v1/reports/usage.quotas/export?format=xlsx&from=2026-09-01&to=2026-09-14"
    )
    assert answer.status_code == 202, answer.text
    export_id = answer.json()["export_id"]
    assert answer.json()["format"] == "xlsx"
    # The row was written before the response, the object after it.
    inserted = harness.session.inserted("report_exports")
    assert inserted and inserted[0]["id"] == export_id and inserted[0]["tenant_id"] == TENANT
    key = f"tenants/{TENANT}/exports/{export_id}/usage-quotas-2026-09-01-to-2026-09-14.xlsx"
    assert key in harness.store.objects
    content, media_type = harness.store.objects[key]
    assert content[:2] == b"PK" and media_type.endswith("spreadsheetml.sheet")
    ready = [p for sql, p in harness.session.statements if "set status = 'ready'" in sql]
    assert ready and ready[0] is not None and ready[0]["storage_key"] == key
    recorded = harness.session.inserted("audit_events")
    assert any(r["action"] == "report.exported" for r in recorded)
    assert EXPORT_ROW_LIMIT > 0, "the module's own bound is untouched by the patch"


def test_a_background_export_can_be_asked_for_and_downloaded(
    owner: tuple[Harness, TestClient],
) -> None:
    harness, client = owner
    answer = client.get("/api/v1/reports/usage.quotas/export?background=1")
    assert answer.status_code == 202
    harness.session.exports = [
        {
            "id": answer.json()["export_id"],
            "report_key": "usage.quotas",
            "format": "csv",
            "status": "ready",
            "filename": "usage-quotas.csv",
            "rows": 3,
            "size_bytes": 120,
            "error": None,
            "requested_by": "user-1",
            "created_at": datetime(2026, 9, 14, tzinfo=UTC),
            "ready_at": datetime(2026, 9, 14, tzinfo=UTC),
            "storage_key": f"tenants/{TENANT}/exports/x/usage-quotas.csv",
        }
    ]
    listed = client.get("/api/v1/reports/exports")
    assert listed.status_code == 200, listed.text
    assert listed.json()["retention_days"] == 7
    assert listed.json()["exports"][0]["status"] == "ready"
    ticket = client.get(f"/api/v1/reports/exports/{answer.json()['export_id']}/download")
    assert ticket.status_code == 200, ticket.text
    assert ticket.json()["url"].startswith("https://bucket.invalid/get/tenants/")


# ── schedules ────────────────────────────────────────────────────────────────


def test_a_schedule_is_validated_recorded_and_removable(owner: tuple[Harness, TestClient]) -> None:
    harness, client = owner
    answer = client.post(
        "/api/v1/reports/activity.audit/schedules",
        json={
            "cadence": "weekly",
            "format": "pdf",
            "recipients": ["Ada@Example.com", "ada@example.com", "bob@example.com"],
            "filters": {"outcome": "ok"},
        },
    )
    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert body["recipients"] == ["ada@example.com", "bob@example.com"]
    assert body["filters"] == {"outcome": "ok", "limit": "100"}
    assert body["cadence"] == "weekly" and body["format"] == "pdf"
    assert body["next_run_at"].startswith("2026-09-21T06:00:00")
    recorded = harness.session.inserted("audit_events")
    assert [r["action"] for r in recorded][-1] == "report.scheduled"

    gone = client.delete(f"/api/v1/reports/schedules/{body['id']}")
    assert gone.status_code == 204
    assert [r["action"] for r in harness.session.inserted("audit_events")][
        -1
    ] == "report.schedule_removed"


def test_a_schedule_refuses_what_the_worker_would_have_to_trust(
    owner: tuple[Harness, TestClient],
) -> None:
    _harness, client = owner
    base = {"cadence": "daily", "format": "csv", "recipients": ["ada@example.com"]}
    assert (
        client.post(
            "/api/v1/reports/usage.quotas/schedules",
            json={**base, "recipients": ["not-an-address"]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/reports/usage.quotas/schedules",
            json={**base, "filters": {"from": "2026-01-01"}},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/reports/activity.audit/schedules",
            json={**base, "filters": {"outcome": "drop table"}},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/reports/usage.quotas/schedules", json={**base, "format": "docx"}
        ).status_code
        == 406
    )
    assert (
        client.post(
            "/api/v1/reports/usage.quotas/schedules", json={**base, "cadence": "hourly"}
        ).status_code
        == 422
    )
    assert client.post("/api/v1/reports/nobody.home/schedules", json=base).status_code == 404


def test_a_schedule_needs_the_export_permission_and_the_scheduled_entitlement() -> None:
    body = {"cadence": "daily", "format": "csv", "recipients": ["ada@example.com"]}
    member = Harness(frozenset({OrganizationRole.MEMBER}), plan(*ALL))
    app.dependency_overrides[tenant_reporting] = member.reporting
    app.dependency_overrides[require_auth] = member.claims
    try:
        assert (
            TestClient(app).post("/api/v1/reports/usage.quotas/schedules", json=body).status_code
            == 403
        )
    finally:
        app.dependency_overrides.clear()

    unscheduled = Harness(
        frozenset({OrganizationRole.OWNER}), plan("reporting.basic", "reporting.export")
    )
    app.dependency_overrides[tenant_reporting] = unscheduled.reporting
    app.dependency_overrides[require_auth] = unscheduled.claims
    try:
        answer = TestClient(app).post("/api/v1/reports/usage.quotas/schedules", json=body)
        assert answer.status_code == 402 and "reporting.scheduled" in answer.json()["detail"]
        assert TestClient(app).get("/api/v1/reports/usage.quotas").json()["can_schedule"] is False
    finally:
        app.dependency_overrides.clear()
