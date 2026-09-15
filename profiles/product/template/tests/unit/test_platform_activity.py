"""The platform reads every tenant's audited activity, aggregated, from the
private router: the same shape and the same identity rule as the AI half."""

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
        "action": "report.exported",
        "outcome": "ok",
        "events": 3,
        "actors": 2,
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


def test_activity_is_aggregated_per_tenant_day_and_action() -> None:
    answer = _client(_Session()).get("/internal/platform/v1/activity?since=2026-09-01")
    assert answer.status_code == 200, answer.text
    day = answer.json()["days"][0]
    assert day["action"] == "report.exported" and day["events"] == 3 and day["actors"] == 2
    assert "actor_id" not in day and "target_id" not in day


def test_the_window_is_bounded_on_the_product_side() -> None:
    session = _Session()
    a_year_ago = (datetime.now(UTC).date() - timedelta(days=365)).isoformat()
    answer = _client(session).get(f"/internal/platform/v1/activity?since={a_year_ago}")
    assert answer.status_code == 200
    start = datetime.fromisoformat(answer.json()["since"]).date()
    assert datetime.now(UTC).date() - start <= timedelta(days=92)
    assert session.parameters[-1]["since"] == start


def test_a_human_token_is_refused_like_every_platform_route() -> None:
    app.dependency_overrides.clear()
    app.state.redis = None
    assert TestClient(app).get("/internal/platform/v1/activity").status_code in (401, 403)
