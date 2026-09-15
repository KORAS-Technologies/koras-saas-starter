"""An unauthenticated call to the gateway, or a wrongly authenticated one, is a 401, not a 500."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Loaded by path: the gateway is a workspace member that is not installed into
# the root environment, because installing it means installing the whole of
# LiteLLM for a module that imports nothing. The guard has no dependencies,
# which is what makes it testable this way and worth keeping that way.
_GUARD = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "ai-gateway"
    / "koras_ai_gateway"
    / "guard.py"
)
_spec = importlib.util.spec_from_file_location("koras_ai_gateway_guard", _GUARD)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)
RequireBearer = guard.RequireBearer
is_open = guard.is_open


def _app(key: str | None = None) -> TestClient:
    inner = FastAPI()

    @inner.get("/health/liveliness")
    async def liveliness() -> dict[str, str]:
        return {"status": "alive"}

    @inner.get("/v1/models")
    async def models() -> dict[str, Any]:
        return {"data": []}

    @inner.post("/v1/chat/completions")
    async def completions() -> dict[str, str]:
        return {"id": "chatcmpl-test"}

    inner.add_middleware(RequireBearer, key=key)
    return TestClient(inner)


def test_a_request_with_no_bearer_is_refused_with_401() -> None:
    answer = _app().get("/v1/models")
    assert answer.status_code == 401
    assert answer.headers["www-authenticate"] == "Bearer"
    assert answer.json()["error"]["type"] == "authentication_error"


def test_with_no_key_configured_any_bearer_reaches_the_proxy() -> None:
    # A smoke test with no master key: whether it is right is LiteLLM's to say.
    answer = _app().post("/v1/chat/completions", headers={"Authorization": "Bearer sk-x"})
    assert answer.status_code == 200
    assert answer.json()["id"] == "chatcmpl-test"


def test_the_right_key_reaches_the_proxy_and_the_wrong_one_is_401() -> None:
    client = _app(key="sk-right")
    ok = client.post("/v1/chat/completions", headers={"Authorization": "Bearer sk-right"})
    assert ok.status_code == 200
    wrong = client.post("/v1/chat/completions", headers={"Authorization": "Bearer sk-wrong"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["message"] == "Invalid gateway key"
    assert "sk-right" not in wrong.text
    # Not a bearer at all is the same as none.
    basic = client.get("/v1/models", headers={"Authorization": "Basic abc"})
    assert basic.status_code == 401
    assert client.get("/health/liveliness").status_code == 200


def test_liveness_needs_no_credential() -> None:
    assert _app().get("/health/liveliness").status_code == 200
    assert is_open("/health/readiness")
    assert is_open("/")
    assert not is_open("/v1/models")
    assert not is_open("/healthy-looking")
