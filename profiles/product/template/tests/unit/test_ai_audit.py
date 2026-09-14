"""The durable audit: buffered per request, written on the tenant session, read by an approver."""

from __future__ import annotations

import os
from typing import Any

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from fastapi.testclient import TestClient  # noqa: E402
from koras_api.core.ai import SqlAuditSink  # noqa: E402
from koras_audit import AuditEvent  # noqa: E402
from test_ai_api import AUTH, Harness  # noqa: E402
from test_ai_api import client as client_fixture  # noqa: E402, F401
from test_ai_api import harness as harness_fixture  # noqa: E402, F401


class _Session:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> _Rows:
        self.calls.append((str(statement).split("(")[0].strip().split("\n")[0], parameters))
        return _Rows()

    async def commit(self) -> None:
        self.calls.append(("commit", None))


class _Rows:
    def fetchall(self) -> list[Any]:
        return []


def _event(action: str = "ai.action.approved") -> AuditEvent:
    return AuditEvent(
        action=action,
        actor_id="user-1",
        tenant_id="tenant-1",
        target_type="action",
        target_id="act-1",
        outcome="ok",
        details={"tool": "files.delete"},
    )


async def test_events_are_buffered_then_written_in_order_and_the_tenant_rebound() -> None:
    session = _Session()
    sink = SqlAuditSink(session, "tenant-1")  # type: ignore[arg-type]
    sink.emit(_event("ai.tool.proposed"))
    sink.emit(_event("ai.action.approved"))
    assert session.calls == []

    written = await sink.flush()

    assert written == 2
    assert [c[0] for c in session.calls] == [
        "insert into public.ai_audit_events",
        "insert into public.ai_audit_events",
        "commit",
        "select set_config",
    ]
    first = session.calls[0][1]
    assert first is not None
    assert first["action"] == "ai.tool.proposed" and first["tenant_id"] == "tenant-1"
    assert '"tool": "files.delete"' in first["details"]
    # Flushed once; a second flush writes nothing.
    assert await sink.flush() == 0


async def test_an_event_for_another_tenant_is_refused_at_the_sink() -> None:
    sink = SqlAuditSink(_Session(), "tenant-2")  # type: ignore[arg-type]
    try:
        sink.emit(_event())
    except ValueError as refused:
        assert "tenant" in str(refused)
    else:
        raise AssertionError("an event for another tenant was accepted")


def test_the_activity_read_needs_the_approve_permission(
    harness_fixture: Harness,  # noqa: F811
    client_fixture: TestClient,  # noqa: F811
) -> None:
    assert client_fixture.get("/api/v1/ai/audit", headers=AUTH).status_code == 200
    harness_fixture.as_member()
    assert client_fixture.get("/api/v1/ai/audit", headers=AUTH).status_code == 403
