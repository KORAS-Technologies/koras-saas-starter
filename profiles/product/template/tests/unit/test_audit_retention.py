"""The audit sweep keeps each class for its own time, on the provisioning context.

Foundation, like the sweep itself. One number governed the whole table until
2026-09-16: too long for an opened file, too short for a refusal.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

pytest.importorskip("koras_worker")
from koras_worker.tasks.audit_retention import (  # noqa: E402
    AuditSettings,
    purge_audit_events,
    purge_audit_history,
    retention_by_class,
)


class _Rows:
    def __init__(self, n: int) -> None:
        self._n = n

    def all(self) -> list[tuple[str]]:
        return [(f"a{i}",) for i in range(self._n)]


class _Session:
    def __init__(self, removed: int) -> None:
        self.statements: list[tuple[str, dict[str, Any] | None]] = []
        self.committed = False
        self._removed = removed

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> _Rows:
        self.statements.append((str(statement), parameters))
        return _Rows(self._removed if parameters else 0)

    async def commit(self) -> None:
        self.committed = True


def _retention() -> dict[str, int]:
    return {"activity": 90, "audit": 365, "administrative": 365, "security": 1095}


async def test_every_class_is_swept_at_its_own_age_in_one_transaction() -> None:
    session = _Session(removed=2)
    removed = await purge_audit_events(session, retention=_retention())  # type: ignore[arg-type]

    assert removed == {"activity": 2, "administrative": 2, "audit": 2, "security": 2}
    assert session.committed

    provisioning, *deletes = session.statements
    assert "app.provisioning" in provisioning[0]
    # One provisioning setting for all four deletes: a sweep interrupted half
    # way leaves the table consistent with itself.
    assert len(deletes) == 4
    assert all("delete from public.audit_events" in text for text, _ in deletes)

    by_class = {p["classification"]: p["before"] for _, p in deletes if p is not None}
    now = datetime.now(UTC)
    assert now - by_class["activity"] > timedelta(days=89)
    assert now - by_class["security"] > timedelta(days=1094)
    # Security is kept longest; activity the shortest. The ordering is the
    # whole point of the column.
    assert by_class["security"] < by_class["audit"] < by_class["activity"]


async def test_retention_of_nothing_is_refused_for_any_class() -> None:
    retention = _retention()
    retention["security"] = 0
    with pytest.raises(ValueError, match="security"):
        await purge_audit_events(_Session(0), retention=retention)  # type: ignore[arg-type]


async def test_nothing_is_deleted_when_one_class_is_misconfigured() -> None:
    """The guard runs over every class before the first delete, so a typo in
    one number cannot wipe the three that were spelled correctly."""
    retention = _retention()
    retention["audit"] = -1
    session = _Session(5)
    with pytest.raises(ValueError):
        await purge_audit_events(session, retention=retention)  # type: ignore[arg-type]
    assert session.statements == []
    assert not session.committed


def test_administrative_shares_the_default_and_security_does_not() -> None:
    mapping = retention_by_class(AuditSettings())
    assert mapping["administrative"] == mapping["audit"] == 365
    assert mapping["activity"] == 90
    assert mapping["security"] == 1095


async def test_the_sweep_skips_loudly_without_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from koras_worker import settings as worker_settings

    monkeypatch.setattr(worker_settings.settings, "database_url", "")
    assert await purge_audit_history({}) == {"status": "skipped", "reason": "no database"}
