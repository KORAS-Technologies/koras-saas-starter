"""The retention sweep deletes by age, on the provisioning context, and refuses zero."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

# The worker is installed into the root environment only when the product was
# generated with it; without it there is nothing here to test.
pytest.importorskip("koras_worker")
from koras_worker.tasks.ai_retention import purge_conversations  # noqa: E402


class _Rows:
    def __init__(self, n: int) -> None:
        self._n = n

    def all(self) -> list[tuple[str]]:
        return [(f"c{i}",) for i in range(self._n)]


class _Session:
    def __init__(self, removed: int) -> None:
        self.statements: list[tuple[str, dict[str, Any] | None]] = []
        self.committed = False
        self._removed = removed

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> _Rows:
        self.statements.append((str(statement), parameters))
        return _Rows(self._removed if "delete" in str(statement) else 0)

    async def commit(self) -> None:
        self.committed = True


async def test_it_sets_the_provisioning_context_then_deletes_by_age() -> None:
    session = _Session(removed=3)
    started = datetime.now(UTC)

    removed = await purge_conversations(session, retention_days=90)  # type: ignore[arg-type]

    assert removed == 3
    assert session.committed
    first, second = session.statements
    assert "app.provisioning" in first[0] and "'on'" in first[0]
    assert "delete from public.ai_conversations" in second[0]
    assert "updated_at <" in second[0]
    before = second[1]["before"] if second[1] else None
    assert before is not None
    assert timedelta(days=89, hours=23) < started - before < timedelta(days=90, minutes=1)


async def test_a_retention_of_zero_is_refused_not_run() -> None:
    session = _Session(removed=0)
    with pytest.raises(ValueError, match="at least 1"):
        await purge_conversations(session, retention_days=0)  # type: ignore[arg-type]
    assert session.statements == []
