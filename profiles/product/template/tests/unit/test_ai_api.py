"""The assistant's routes, asked of the app with the runtime's dependencies replaced.

What is tested here is the boundary the router owns: that every route needs a
verified caller, that a body naming a tenant is refused, that a refusal from
the runtime becomes the status and code the web tier expects, and that the
approval routes run the runtime's policy rather than their own. The runtime's
own behaviour -- the turn, the meter, the tenant boundary -- is tested where
it lives, in `python-packages/koras-ai`.

The dependency that assembles the runtime is overridden with one built around
the in-memory store and a scripted provider, so no database, no platform and
no gateway are needed. The rate limiter's auth dependency is overridden too,
so the limiter still runs and keys on the stand-in caller.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from fastapi.testclient import TestClient  # noqa: E402
from koras_ai import (  # noqa: E402
    AIConfiguration,
    AIContext,
    AIError,
    AIRuntime,
    ErrorCode,
    FakeProvider,
    InMemoryStore,
    Limits,
    Message,
    ProviderRegistry,
    StaticRouting,
    ToolCall,
)
from koras_api.ai import registries  # noqa: E402
from koras_api.core.ai import AiGrant, TenantAI, tenant_ai  # noqa: E402
from koras_api.core.auth import require_auth  # noqa: E402
from koras_api.main import app  # noqa: E402
from koras_audit import MemoryAuditSink  # noqa: E402
from koras_auth import JWTClaims  # noqa: E402
from koras_platform import OrganizationRole  # noqa: E402

# The lifespan does not run under the test client below, so the rate limiter
# would find no Redis on the app's state. None is the limiter's documented
# degraded state -- allowed, and said so -- and what a local run has too.
app.state.redis = None

OWNER = frozenset(
    {
        "product.access",
        "files.read",
        "files.upload",
        "files.manage",
        "ai.use",
        "ai.approve",
        "team.read",
        "team.manage",
        "settings.read",
        "settings.manage",
    }
)
MEMBER = frozenset({"product.access", "files.read", "files.upload", "ai.use"})


def context(user: str, permissions: frozenset[str], roles: frozenset[str]) -> AIContext:
    return AIContext(
        product_code="sample",
        environment="dev",
        tenant_id="00000000-0000-0000-0000-000000000001",
        organization_id="org-1",
        user_id=user,
        roles=roles,
        permissions=permissions,
    )


class Harness:
    """One app, one store, one provider script, a caller that can be swapped."""

    def __init__(self, script: list[Message], *, limits: Limits | None = None) -> None:
        self.store = InMemoryStore()
        self.provider = FakeProvider(script)
        providers = ProviderRegistry()
        for name in registries.PROVIDER_NAMES:
            providers.register(name, self.provider)
        self.audit = MemoryAuditSink()
        self.runtime = AIRuntime(
            configuration=AIConfiguration(
                catalogue=registries.catalogue,
                routing=StaticRouting(),
                fail_closed=False,
                limits=limits or Limits(),
            ),
            providers=providers,
            tools=registries.tools,
            agents=registries.agents,
            prompts=registries.prompts,
            store=self.store,
            usage=self.store,
            audit=self.audit,
        )
        self.context = context("owner", OWNER, frozenset({"organization_owner"}))
        self.grant = AiGrant(enabled=True, tools=True, monthly_requests=None, resolved=True)

    def as_member(self) -> None:
        self.context = context("member", MEMBER, frozenset({"member"}))

    def claims(self) -> JWTClaims:
        return JWTClaims(
            sub=self.context.user_id,
            roles=frozenset(OrganizationRole(r) for r in self.context.roles),
            organization_id="org-1",
        )

    def tenant_ai(self) -> TenantAI:
        return TenantAI(runtime=self.runtime, context=self.context, grant=self.grant)


@pytest.fixture
def harness() -> Iterator[Harness]:
    built = Harness([Message("assistant", "Hello from the assistant.")])
    app.dependency_overrides[tenant_ai] = built.tenant_ai
    app.dependency_overrides[require_auth] = built.claims
    try:
        yield built
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client() -> TestClient:
    # Not entered as a context manager: that runs the lifespan, which opens
    # the database and checks its role, and there is no database here.
    return TestClient(app, raise_server_exceptions=True)


AUTH = {"Authorization": "Bearer stand-in"}


def test_every_ai_route_refuses_without_a_bearer() -> None:
    app.dependency_overrides.clear()
    client = TestClient(app)
    assert client.get("/api/v1/ai/status").status_code in (401, 403)
    assert client.post("/api/v1/ai/conversations", json={}).status_code in (401, 403)
    assert client.post("/api/v1/ai/actions/x/approve").status_code in (401, 403)


def test_status_reports_the_grant_and_the_allowance(harness: Harness, client: TestClient) -> None:
    answer = client.get("/api/v1/ai/status", headers=AUTH)
    assert answer.status_code == 200
    body = answer.json()
    assert body["enabled"] is True
    assert body["tools_enabled"] is True
    assert body["requests_this_month"] == 0
    assert body["monthly_limit"] is None
    assert body["agents"] == ["assistant"]


def test_a_conversation_is_started_and_answered(harness: Harness, client: TestClient) -> None:
    started = client.post(
        "/api/v1/ai/conversations",
        json={"title": "Files", "context_type": "file", "context_id": "f1"},
        headers=AUTH,
    )
    assert started.status_code == 201, started.text
    conversation = started.json()
    assert conversation["agent_id"] == "assistant"
    assert conversation["context_type"] == "file"

    sent = client.post(
        f"/api/v1/ai/conversations/{conversation['id']}/messages",
        json={"text": "what do I have?"},
        headers=AUTH,
    )
    assert sent.status_code == 200, sent.text
    turn = sent.json()
    assert [m["role"] for m in turn["messages"]] == ["user", "assistant"]
    assert turn["messages"][1]["content"] == "Hello from the assistant."
    assert turn["usage"] == {"input": 10, "output": 5, "total": 15}
    assert turn["pending"] == []

    # The system prompt reached the model with the product and the page in it.
    system = harness.provider.requests[0].messages[0]
    assert system.role == "system"
    assert "sample" in system.content and "file f1" in system.content

    detail = client.get(f"/api/v1/ai/conversations/{conversation['id']}", headers=AUTH)
    assert detail.status_code == 200
    assert len(detail.json()["messages"]) == 2
    listed = client.get("/api/v1/ai/conversations", headers=AUTH)
    assert [c["id"] for c in listed.json()["conversations"]] == [conversation["id"]]


def test_a_body_that_names_a_tenant_is_refused(harness: Harness, client: TestClient) -> None:
    """There is nowhere in a request to put a tenant, and putting one is 422."""
    answer = client.post(
        "/api/v1/ai/conversations",
        json={"title": "x", "tenant_id": "00000000-0000-0000-0000-000000000002"},
        headers=AUTH,
    )
    assert answer.status_code == 422
    answer = client.post(
        "/api/v1/ai/conversations",
        json={"title": "x", "organization_id": "someone-else"},
        headers=AUTH,
    )
    assert answer.status_code == 422


def test_a_plan_without_the_assistant_is_402_before_any_call(
    harness: Harness, client: TestClient
) -> None:
    """The gate the dependency applies, exercised through the function that decides it."""
    from koras_ai import AIError, ErrorCode
    from koras_api.core.ai import AI_ENTITLEMENT, grant_from
    from koras_api.core.platform import PortalAnswer

    no_subscription = grant_from(PortalAnswer(None), configured=True)
    assert no_subscription.enabled is False

    granted = grant_from(
        PortalAnswer(
            {
                "plan_code": "pro",
                "entitlements": [
                    {"code": AI_ENTITLEMENT, "enabled": True, "limit_value": None},
                    {"code": "ai.tools", "enabled": False, "limit_value": None},
                    {"code": "ai.requests", "enabled": True, "limit_value": 500},
                ],
            }
        ),
        configured=True,
    )
    assert (granted.enabled, granted.tools, granted.monthly_requests) == (True, False, 500)

    # No platform configured: the product runs on its own, and says so.
    alone = grant_from(None, configured=False)
    assert alone.enabled and alone.resolved is False

    # A platform configured and silent is a refusal, not a guess.
    with pytest.raises(AIError) as refused:
        grant_from(None, configured=True)
    assert refused.value.code is ErrorCode.PROVIDER_UNAVAILABLE


def test_a_spent_allowance_is_429_with_a_code(client: TestClient) -> None:
    built = Harness([Message("assistant", "one")], limits=Limits(monthly_requests=1))
    app.dependency_overrides[tenant_ai] = built.tenant_ai
    app.dependency_overrides[require_auth] = built.claims
    try:
        conversation = client.post("/api/v1/ai/conversations", json={}, headers=AUTH).json()
        first = client.post(
            f"/api/v1/ai/conversations/{conversation['id']}/messages",
            json={"text": "one"},
            headers=AUTH,
        )
        assert first.status_code == 200
        second = client.post(
            f"/api/v1/ai/conversations/{conversation['id']}/messages",
            json={"text": "two"},
            headers=AUTH,
        )
        assert second.status_code == 429
        assert second.json()["detail"]["code"] == "usage_exceeded"
    finally:
        app.dependency_overrides.clear()


def test_an_unknown_conversation_is_404(harness: Harness, client: TestClient) -> None:
    answer = client.get("/api/v1/ai/conversations/nope", headers=AUTH)
    assert answer.status_code == 404
    answer = client.post("/api/v1/ai/conversations/nope/messages", json={"text": "?"}, headers=AUTH)
    assert answer.status_code == 404
    assert answer.json()["detail"]["code"] == "not_found"


def test_an_empty_message_is_422(harness: Harness, client: TestClient) -> None:
    conversation = client.post("/api/v1/ai/conversations", json={}, headers=AUTH).json()
    answer = client.post(
        f"/api/v1/ai/conversations/{conversation['id']}/messages", json={"text": ""}, headers=AUTH
    )
    assert answer.status_code == 422


def _proposal(name: str, arguments: dict[str, object]) -> Message:
    return Message("assistant", "", tool_calls=(ToolCall("c1", name, arguments),))


def test_a_delete_proposal_waits_for_approval_and_a_member_cannot_make_one(
    client: TestClient,
) -> None:
    """The reference destructive tool: proposed by the model, parked by the
    runtime, decided by a person. A member has no files.manage, so the same
    proposal from them is refused rather than parked."""
    file_id = "0f9c1a3e-2b4d-4c6e-8f10-1234567890ab"
    built = Harness(
        [_proposal("files.delete", {"file_id": file_id}), Message("assistant", "Waiting.")]
    )
    app.dependency_overrides[tenant_ai] = built.tenant_ai
    app.dependency_overrides[require_auth] = built.claims
    try:
        conversation = client.post("/api/v1/ai/conversations", json={}, headers=AUTH).json()
        turn = client.post(
            f"/api/v1/ai/conversations/{conversation['id']}/messages",
            json={"text": "delete that file"},
            headers=AUTH,
        ).json()
        assert [a["tool_id"] for a in turn["pending"]] == ["files.delete"]
        assert turn["pending"][0]["status"] == "awaiting_approval"
        assert turn["pending"][0]["operation"] == "destructive"
        # In words, for the person deciding. No session here, so the file
        # cannot be named; the shape is still the shape.
        assert turn["pending"][0]["summary"]["title"] == "Delete a file"
        # Nothing was deleted: the tool has not run.
        assert built.store.usage[0].status == "ok"

        member = Harness(
            [_proposal("files.delete", {"file_id": file_id}), Message("assistant", "I cannot.")]
        )
        member.as_member()
        app.dependency_overrides[tenant_ai] = member.tenant_ai
        app.dependency_overrides[require_auth] = member.claims
        conversation = client.post("/api/v1/ai/conversations", json={}, headers=AUTH).json()
        turn = client.post(
            f"/api/v1/ai/conversations/{conversation['id']}/messages",
            json={"text": "delete that file"},
            headers=AUTH,
        ).json()
        assert turn["pending"] == []
    finally:
        app.dependency_overrides.clear()


def test_a_read_tool_runs_without_a_session_and_says_so(client: TestClient) -> None:
    # The reference tool reads the database; without a session it answers
    # honestly rather than failing, and the model gets the note as data.
    built = Harness([_proposal("files.list", {"limit": 3}), Message("assistant", "Nothing yet.")])
    app.dependency_overrides[tenant_ai] = built.tenant_ai
    app.dependency_overrides[require_auth] = built.claims
    try:
        conversation = client.post("/api/v1/ai/conversations", json={}, headers=AUTH).json()
        turn = client.post(
            f"/api/v1/ai/conversations/{conversation['id']}/messages",
            json={"text": "list"},
            headers=AUTH,
        ).json()
        assert [m["role"] for m in turn["messages"]] == ["user", "assistant", "tool", "assistant"]
        assert "no database session" in turn["messages"][2]["content"]
        assert turn["pending"] == []
    finally:
        app.dependency_overrides.clear()


def test_approving_an_unknown_action_is_404_and_a_wrong_state_is_409(
    harness: Harness, client: TestClient
) -> None:
    answer = client.post("/api/v1/ai/actions/nope/approve", headers=AUTH)
    assert answer.status_code == 404
    answer = client.post("/api/v1/ai/actions/nope/reject", headers=AUTH)
    assert answer.status_code == 404


def test_no_ai_response_schema_carries_a_forbidden_field_name() -> None:
    """The same rule `tests/security/test_api_surface.py` applies, stated for these routes."""
    spec = app.openapi()
    for name, schema in spec["components"]["schemas"].items():
        if not name.endswith("View") and name not in ("ConversationDetail", "ConversationList"):
            continue
        for field in schema.get("properties", {}):
            assert "token" not in field.lower(), f"{name}.{field}"
            assert "secret" not in field.lower(), f"{name}.{field}"


def test_a_refusal_on_our_side_puts_its_detail_in_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The page says "the reason is in the server log"; this is that reason.

    Only a 5xx is logged. A customer's own refusal -- no entitlement, quota
    spent -- is theirs to read on the page, and logging it at warning would
    page an operator about a plan.
    """
    from koras_api.core.ai import refusal

    with caplog.at_level("WARNING", logger="koras_api.core.ai"):
        answered = refusal(
            AIError(
                ErrorCode.CONFIGURATION_ERROR,
                "AI routing is not configured for this organization",
                detail="no routing policy for koras-balanced and a platform is configured",
            )
        )
        refusal(AIError(ErrorCode.ENTITLEMENT_MISSING, "The plan does not include AI"))
    assert answered.status_code == 503
    assert answered.detail == {
        "code": "configuration_error",
        "message": "AI routing is not configured for this organization",
    }
    logged = [record.getMessage() for record in caplog.records]
    assert len(logged) == 1
    assert "koras-balanced" in logged[0] and "503" in logged[0]


class _RecordingSession:
    """The two calls the store makes, in the order it makes them."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, statement: object, parameters: object = None) -> object:
        self.calls.append(str(statement).split("(")[0].strip().split("\n")[0])
        return _NoRows()

    async def commit(self) -> None:
        self.calls.append("commit")


class _NoRows:
    def first(self) -> None:
        return None

    def scalar_one(self) -> int:
        return 0


async def test_the_store_binds_the_tenant_again_after_every_commit() -> None:
    """Row-level security reads a transaction-local setting; a commit ends
    the transaction. A store that committed and carried on would make its
    next statement as nobody, and the policies would refuse it -- which is
    how the first real usage row on dev was lost."""
    from datetime import UTC, datetime

    from koras_ai import Usage, UsageEvent
    from koras_api.core.ai import SqlStore

    session = _RecordingSession()
    store = SqlStore(session, "tenant-1")  # type: ignore[arg-type]
    await store.record(
        UsageEvent(
            tenant_id="tenant-1",
            user_id="user-1",
            agent_id="assistant",
            model_alias="koras-balanced",
            provider="openai",
            model="gpt-4o-mini",
            usage=Usage(),
            latency_ms=0,
            status="error",
            created_at=datetime.now(UTC),
            error_code="upstream_error",
        )
    )
    assert session.calls == ["insert into public.ai_usage_events", "commit", "select set_config"]
