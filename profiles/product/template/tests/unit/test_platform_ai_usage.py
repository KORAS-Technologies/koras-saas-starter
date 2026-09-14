"""The platform reads every tenant's AI usage, aggregated, from the private router.

The route is on the machine-only router and the provisioning session, which
the isolation suite (070) proves can read across tenants and write nothing.
What is checked here is the shape and the window: aggregates in, a bounded
`since`, and the same identity rule every route on that router has.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from fastapi.testclient import TestClient  # noqa: E402
from koras_api.core.database import get_platform_session  # noqa: E402
from koras_api.core.platform_auth import require_platform_machine  # noqa: E402
from koras_api.main import app  # noqa: E402

ROWS = [
    {
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "day": datetime.now(UTC).date(),
        "model_alias": "koras-balanced",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "calls": 3,
        "errors": 1,
        "input_tokens": 300,
        "output_tokens": 90,
        "total_tokens": 390,
        "estimated_cost_micros": 99,
        "overage_calls": 1,
        "billable_micros": 132,
    }
]


class _Result:
    def mappings(self) -> _Result:
        return self

    def all(self) -> list[dict[str, Any]]:
        return ROWS


class _Session:
    def __init__(self) -> None:
        self.parameters: list[dict[str, Any]] = []

    async def execute(self, statement: object, parameters: dict[str, Any]) -> _Result:
        self.parameters.append(parameters)
        return _Result()


def _client(session: _Session) -> TestClient:
    async def _session() -> AsyncIterator[_Session]:
        yield session

    app.dependency_overrides[require_platform_machine] = lambda: None
    app.dependency_overrides[get_platform_session] = _session
    app.state.redis = None
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_usage_is_aggregated_per_tenant_and_day() -> None:
    session = _Session()
    answer = _client(session).get("/internal/platform/v1/ai-usage?since=2026-09-01")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["days"][0]["tenant_id"] == ROWS[0]["tenant_id"]
    assert body["days"][0]["calls"] == 3
    assert body["days"][0]["estimated_cost_micros"] == 99
    assert body["days"][0]["overage_calls"] == 1
    assert body["days"][0]["billable_micros"] == 132
    # No user, no conversation: aggregates leave the product, rows do not.
    assert "user_id" not in body["days"][0]


def test_the_window_is_bounded_on_the_product_side() -> None:
    session = _Session()
    client = _client(session)
    a_year_ago = (datetime.now(UTC).date() - timedelta(days=365)).isoformat()
    answer = client.get(f"/internal/platform/v1/ai-usage?since={a_year_ago}")
    assert answer.status_code == 200
    start = datetime.fromisoformat(answer.json()["since"]).date()
    assert datetime.now(UTC).date() - start <= timedelta(days=92)
    assert session.parameters[-1]["since"] == start

    # No `since` at all is the whole window, not today alone.
    answer = client.get("/internal/platform/v1/ai-usage")
    assert answer.status_code == 200
    assert datetime.fromisoformat(answer.json()["since"]).date() == start


def test_a_human_token_is_refused_like_every_platform_route() -> None:
    app.dependency_overrides.clear()
    app.state.redis = None
    answer = TestClient(app).get("/internal/platform/v1/ai-usage")
    assert answer.status_code in (401, 403)
