"""The per-minute ceiling on the assistant, per organization.

The tier-2 limiter bounds a caller's requests and the plan bounds the
month; between them a loop could still make a model call every few
milliseconds until the month ran out. This is the ceiling in between: a
fixed window per tenant, on the two routes that call a model, refused
with the same 429 the monthly allowance uses. Zero switches it off, and a
missing Redis degrades to allowing, the way every limiter here does.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from fastapi import HTTPException  # noqa: E402
from koras_api.core import ai as ai_module  # noqa: E402
from koras_api.core.settings import settings  # noqa: E402


class _Redis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def incr(self, name: str) -> int:
        self.counts[name] = self.counts.get(name, 0) + 1
        return self.counts[name]

    async def expire(self, name: str, seconds: int) -> bool:
        return True


class _State:
    pass


class _App:
    def __init__(self, redis: _Redis | None) -> None:
        self.state = _State()
        self.state.redis = redis  # type: ignore[attr-defined]


class _Request:
    def __init__(self, redis: _Redis | None) -> None:
        self.app = _App(redis)
        self.state: Any = _State()


class _Tenant:
    """The verified token's claims, as far as the ceiling reads them."""

    organization_id = "org-00000000-0000-0000-0000-000000000001"
    sub = "user-1"


async def test_the_ceiling_refuses_the_call_past_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_requests_per_minute", 2)
    redis = _Redis()
    request = _Request(redis)
    await ai_module.limit_ai_turns(request, _Tenant())  # type: ignore[arg-type]
    await ai_module.limit_ai_turns(request, _Tenant())  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as refused:
        await ai_module.limit_ai_turns(request, _Tenant())  # type: ignore[arg-type]
    assert refused.value.status_code == 429
    assert "minute" in str(refused.value.detail)
    # Keyed by tenant, in its own bucket, so it shares nothing with tier 2.
    assert all(key.startswith("ratelimit:ai:") for key in redis.counts)
    assert all(_Tenant.organization_id in key for key in redis.counts)


async def test_zero_switches_the_ceiling_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_requests_per_minute", 0)
    redis = _Redis()
    for _ in range(5):
        await ai_module.limit_ai_turns(_Request(redis), _Tenant())  # type: ignore[arg-type]
    assert redis.counts == {}


async def test_no_redis_degrades_to_allowing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_requests_per_minute", 1)
    request = _Request(None)
    for _ in range(3):
        await ai_module.limit_ai_turns(request, _Tenant())  # type: ignore[arg-type]
    assert request.state.rate_limit.degraded is True
