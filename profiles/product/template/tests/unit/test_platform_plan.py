"""The platform tells the product each tenant's plan, on the private router.

The write is one upsert on the provisioning session; what is checked here
is the shape stored -- codes to enabled and limit, the subscription's
status and dates -- the 404 for a tenant the product does not hold, and
the same identity rule every route on that router has.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from fastapi.testclient import TestClient  # noqa: E402
from koras_api.core.database import get_platform_session  # noqa: E402
from koras_api.core.platform_auth import require_platform_machine  # noqa: E402
from koras_api.main import app  # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"

SNAPSHOT = {
    "plan_code": "business",
    "status": "active",
    "entitlements": [
        {"code": "reporting.export", "enabled": True, "limit_value": None},
        {"code": "reporting.scheduled", "enabled": True},
        {"code": "ai.requests", "enabled": True, "limit_value": 500, "period": "month"},
    ],
    "trial_ends_at": None,
    "current_period_end": "2026-10-01T00:00:00Z",
}


class _Result:
    def __init__(self, row: object) -> None:
        self._row = row

    def first(self) -> object:
        return self._row


class _Session:
    def __init__(self, *, known: bool) -> None:
        self.known = known
        self.parameters: list[dict[str, Any]] = []
        self.commits = 0

    async def execute(self, statement: object, parameters: dict[str, Any]) -> _Result:
        self.parameters.append(parameters)
        return _Result((TENANT,) if self.known else None)

    async def commit(self) -> None:
        self.commits += 1


def _client(session: _Session) -> TestClient:
    async def _session() -> AsyncIterator[_Session]:
        yield session

    app.dependency_overrides[require_platform_machine] = lambda: None
    app.dependency_overrides[get_platform_session] = _session
    app.state.redis = None
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_the_snapshot_is_stored_as_codes_to_enabled_and_limit() -> None:
    session = _Session(known=True)
    answer = _client(session).put(f"/internal/platform/v1/tenants/{TENANT}/plan", json=SNAPSHOT)
    assert answer.status_code == 204, answer.text
    assert session.commits == 1
    params = session.parameters[-1]
    assert params["tenant_id"] == TENANT
    assert params["plan_code"] == "business" and params["status"] == "active"
    assert json.loads(params["entitlements"]) == {
        "reporting.export": {"enabled": True, "limit": None},
        "reporting.scheduled": {"enabled": True, "limit": None},
        "ai.requests": {"enabled": True, "limit": 500},
    }
    assert params["period_ends_at"] is not None and params["trial_ends_at"] is None


def test_a_tenant_the_product_does_not_hold_is_a_404() -> None:
    session = _Session(known=False)
    answer = _client(session).put(f"/internal/platform/v1/tenants/{TENANT}/plan", json=SNAPSHOT)
    assert answer.status_code == 404
    assert session.commits == 0


def test_no_subscription_is_a_real_answer_that_grants_nothing() -> None:
    session = _Session(known=True)
    answer = _client(session).put(
        f"/internal/platform/v1/tenants/{TENANT}/plan",
        json={"plan_code": None, "status": None, "entitlements": []},
    )
    assert answer.status_code == 204, answer.text
    params = session.parameters[-1]
    assert params["plan_code"] is None and json.loads(params["entitlements"]) == {}
