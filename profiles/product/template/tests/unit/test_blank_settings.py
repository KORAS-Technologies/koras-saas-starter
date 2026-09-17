"""A cleared switch reads as off, rather than failing the sweep it disabled.

A secret store is not an environment. Doppler holds a key with an empty value as
readily as it holds no key at all, so "turn the sweep off" and "clear the box"
look like the same act. Pydantic disagrees: `bool` refuses `""`, and the sweep
whose switch was cleared raises `ValidationError` every night instead of
skipping.

Found on 2026-09-17 with `STORAGE_LIFECYCLE_ENABLED` blank in dev -- the setting
whose entire job is keeping a deleting sweep switched off.

These construct the real settings classes with the real environment variables,
because the defect lives in how pydantic reads a value and a test that asserted
on the base class alone would prove nothing about the classes that use it.

`ai_retention` uses the same base and is deliberately absent here: it ships only
with the `ai` capability, and importing it would fail every product generated
without one.
"""

from __future__ import annotations

import os

import pytest

# The worker's own settings are constructed at import time and have no
# defaults, on purpose: a worker that starts against the wrong queue is worse
# than one that refuses to start. The same convention as every other worker
# test here.
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

pytest.importorskip("koras_worker")
from koras_worker.tasks.audit_retention import AuditSettings  # noqa: E402
from koras_worker.tasks.governance_expiry import ExportExpirySettings  # noqa: E402
from koras_worker.tasks.reporting import ReportingSettings  # noqa: E402
from koras_worker.tasks.storage_backup import BackupSettings  # noqa: E402
from koras_worker.tasks.storage_lifecycle import LifecycleSettings  # noqa: E402
from koras_worker.tasks.storage_reconcile import ReconcileSettings  # noqa: E402

#: Each sweep's settings class, and the switch a person would clear to stop it.
SWITCHES = [
    (LifecycleSettings, "STORAGE_LIFECYCLE_ENABLED", "storage_lifecycle_enabled"),
    (ReconcileSettings, "STORAGE_RECONCILE_ENABLED", "storage_reconcile_enabled"),
    (BackupSettings, "STORAGE_BACKUP_ENABLED", "storage_backup_enabled"),
]


@pytest.mark.parametrize(("settings_class", "variable", "field"), SWITCHES)
def test_a_cleared_switch_is_off_rather_than_an_error(
    settings_class: type,
    variable: str,
    field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(variable, "")
    resolved = settings_class()
    assert getattr(resolved, field) is False, (
        f"{variable} was cleared, so {field} must read as off"
    )


@pytest.mark.parametrize(("settings_class", "variable", "field"), SWITCHES)
def test_the_switch_still_works_when_it_is_set(
    settings_class: type,
    variable: str,
    field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guards the guard. A base class that dropped every value, or a field that
    stopped being read, would satisfy the test above while switching nothing on."""
    monkeypatch.setenv(variable, "true")
    assert getattr(settings_class(), field) is True


@pytest.mark.parametrize(
    "settings_class",
    [
        AuditSettings,
        ExportExpirySettings,
        ReportingSettings,
        BackupSettings,
        LifecycleSettings,
        ReconcileSettings,
    ],
)
def test_every_sweep_tolerates_a_blank_value(
    settings_class: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blank every variable a sweep reads, and it still constructs.

    Named fields would go stale as settings are added. The class knows its own
    fields, so ask it: clear all of them and require the class to build. Any
    field whose type refuses an empty string -- bool, int, a constrained str --
    fails here unless the blank is dropped first.
    """
    for name in settings_class.model_fields:
        monkeypatch.setenv(name.upper(), "")
    settings_class()
