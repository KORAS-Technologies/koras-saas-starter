"""The audit sweep deletes by age, on the provisioning context, and refuses zero;
the scheduled-delivery task says nothing is scheduled rather than pretending."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

pytest.importorskip("koras_worker")
from koras_worker.tasks.reporting import (  # noqa: E402
    deliver_scheduled_reports,
    purge_audit_events,
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


async def test_the_sweep_runs_on_the_provisioning_context_and_deletes_by_age() -> None:
    session = _Session(removed=3)
    removed = await purge_audit_events(session, retention_days=365)  # type: ignore[arg-type]
    assert removed == 3
    assert session.committed
    first, purge = session.statements
    assert "app.provisioning" in first[0]
    assert "delete from public.audit_events" in purge[0]
    assert purge[1] is not None
    assert datetime.now(UTC) - purge[1]["before"] > timedelta(days=364)


async def test_retention_of_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        await purge_audit_events(_Session(0), retention_days=0)  # type: ignore[arg-type]


async def test_scheduled_delivery_skips_loudly_without_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from koras_worker import settings as worker_settings

    monkeypatch.setattr(worker_settings.settings, "database_url", "")
    assert await deliver_scheduled_reports({}) == {"status": "skipped", "reason": "no database"}
