"""Storage records what it did: every upload, download and deletion, and every refusal.

The module that stores a customer's files was the one module whose operations
left no trace. These assert the shape of what it records now -- and, because
`koras_audit` refuses a detail named after a credential, that the object key
is never one of them.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_api.core.audit import SqlAuditSink, record  # noqa: E402
from koras_audit import AuditEvent  # noqa: E402


class _Rows:
    def all(self) -> list[Any]:
        return []


class _Session:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> _Rows:
        self.calls.append((str(statement), parameters))
        return _Rows()

    async def commit(self) -> None:
        self.calls.append(("commit", None))


def _insert(session: _Session) -> tuple[str, dict[str, Any] | None]:
    return next(call for call in session.calls if "audit_events" in call[0])


async def test_a_storage_event_is_written_to_the_general_audit_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    from koras_api.core import audit as core_audit

    async def rebind(bound: object, tenant_id: str) -> None:
        session.calls.append(("rebind", None))

    monkeypatch.setattr(core_audit, "rebind_tenant", rebind)
    await record(
        session,  # type: ignore[arg-type]
        tenant_id="tenant-1",
        actor_id="user-1",
        action="storage.object.uploaded",
        target_type="file",
        target_id="file-1",
        outcome="ok",
        details={"size_bytes": 12, "content_type": "text/plain"},
    )
    statement, parameters = _insert(session)
    assert "insert into public.audit_events" in statement
    assert parameters is not None
    assert parameters["tenant_id"] == "tenant-1"
    assert parameters["actor_id"] == "user-1"
    assert parameters["action"] == "storage.object.uploaded"
    assert parameters["target_type"] == "file"
    assert parameters["target_id"] == "file-1"
    assert parameters["outcome"] == "ok"
    assert ("commit", None) in session.calls
    assert ("rebind", None) in session.calls


def test_the_object_key_cannot_be_recorded_as_a_detail() -> None:
    """`storage_key` contains `key`, and the envelope refuses it by name.

    This is why every call site records `file_id` instead. A test rather than
    a comment, because the refusal is the only thing stopping half a signed
    URL from reaching an audit row.
    """
    with pytest.raises(ValueError):
        AuditEvent(
            action="storage.object.uploaded",
            actor_id="user-1",
            tenant_id="tenant-1",
            target_type="file",
            target_id="file-1",
            outcome="ok",
            details={"storage_key": "tenants/t/f/x.txt"},
        )


async def test_a_refusal_is_recorded_as_firmly_as_a_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    from koras_api.core import audit as core_audit

    async def rebind(bound: object, tenant_id: str) -> None:
        return None

    monkeypatch.setattr(core_audit, "rebind_tenant", rebind)
    await record(
        session,  # type: ignore[arg-type]
        tenant_id="tenant-1",
        actor_id="user-1",
        action="storage.upload.refused",
        target_type="file",
        target_id="-",
        outcome="denied",
        details={"reason": "quota", "size_bytes": 99},
    )
    _, parameters = _insert(session)
    assert parameters is not None
    assert parameters["outcome"] == "denied"
    assert "quota" in parameters["details"]


def test_the_sink_refuses_an_event_for_another_tenant() -> None:
    sink = SqlAuditSink(_Session(), "tenant-1")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="another tenant"):
        sink.emit(
            AuditEvent(
                action="storage.object.deleted",
                actor_id="user-1",
                tenant_id="tenant-2",
                target_type="file",
                target_id="file-1",
                outcome="ok",
            )
        )
