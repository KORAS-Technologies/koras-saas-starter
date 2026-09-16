"""The scheduled-delivery task says nothing is scheduled rather than pretending.

The audit sweep's tests moved to `test_audit_retention.py` with the sweep.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

pytest.importorskip("koras_worker")
from koras_worker.tasks.reporting import deliver_scheduled_reports  # noqa: E402


async def test_scheduled_delivery_skips_loudly_without_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from koras_worker import settings as worker_settings

    monkeypatch.setattr(worker_settings.settings, "database_url", "")
    assert await deliver_scheduled_reports({}) == {"status": "skipped", "reason": "no database"}
