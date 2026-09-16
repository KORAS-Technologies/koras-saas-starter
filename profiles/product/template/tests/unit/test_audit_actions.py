"""The audit action registry: declared, classified, refused on a duplicate.

The class an action is kept under belongs to the action rather than to the
call site. These assert that, and that an action nobody declared is refused at
the point of recording rather than silently given a default -- which is how a
security event ends up swept on the activity schedule.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_api.core.audit import STORAGE_ACTIONS, record  # noqa: E402
from koras_audit import (  # noqa: E402
    AuditAction,
    AuditActionRegistry,
    Classification,
    actions,
)


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


def test_every_storage_action_is_registered_at_import() -> None:
    for action in STORAGE_ACTIONS:
        assert action.key in actions


def test_a_refusal_is_security_and_an_ordinary_read_is_activity() -> None:
    """The two that matter: a download is noise a month later, a refusal is
    the thing somebody asks about two years later."""
    assert actions.classification_of("storage.object.downloaded") is Classification.ACTIVITY
    assert actions.classification_of("storage.upload.refused") is Classification.SECURITY
    assert actions.classification_of("storage.object.delete_refused") is Classification.SECURITY
    assert actions.classification_of("storage.object.uploaded") is Classification.AUDIT


def test_an_unregistered_action_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(ValueError, match="not registered"):
        actions.classification_of("storage.object.teleported")


async def test_recording_an_undeclared_action_fails_instead_of_writing_a_row() -> None:
    session = _Session()
    with pytest.raises(ValueError, match="not registered"):
        await record(
            session,  # type: ignore[arg-type]
            tenant_id="tenant-1",
            actor_id="user-1",
            action="storage.object.teleported",
            target_type="file",
            target_id="file-1",
            outcome="ok",
        )
    assert not any("audit_events" in call[0] for call in session.calls)


def test_a_duplicate_key_is_refused_where_it_is_a_traceback() -> None:
    registry = AuditActionRegistry()
    registry.add(AuditAction("a.b", Classification.AUDIT, "first"))
    with pytest.raises(ValueError, match="already registered"):
        registry.add(AuditAction("a.b", Classification.SECURITY, "second"))
    assert registry.classification_of("a.b") is Classification.AUDIT


def test_a_key_that_is_not_dotted_lower_case_is_refused() -> None:
    for bad in ("Storage.Object", "storage", "storage..object", "storage.Object", "1.b"):
        with pytest.raises(ValueError, match="dotted lower-case"):
            AuditAction(bad, Classification.AUDIT, "x")


def test_an_action_without_a_summary_is_refused() -> None:
    with pytest.raises(ValueError, match="summary"):
        AuditAction("a.b", Classification.AUDIT, "   ")


def test_iteration_is_ordered_so_two_runs_of_one_build_agree() -> None:
    registry = AuditActionRegistry()
    for key in ("c.one", "a.two", "b.three"):
        registry.add(AuditAction(key, Classification.AUDIT, key))
    assert [action.key for action in registry] == ["a.two", "b.three", "c.one"]
