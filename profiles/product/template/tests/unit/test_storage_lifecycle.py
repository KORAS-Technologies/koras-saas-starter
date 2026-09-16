"""Object retention: the floors, the one-directional extension, and the hold.

The columns existed from 00018 and nothing wrote them. These assert the three
properties that make writing them safe: a retention of nothing is refused
before anything happens, a shortened floor never brings a deletion forward, and
a held object is never even selected for removal.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

pytest.importorskip("koras_worker")
from koras_worker.tasks.storage_lifecycle import (  # noqa: E402
    Floors,
    LifecycleSettings,
    extend_to_floor,
    floors_from,
    purge_expired,
    resolve_retention,
    sweep_storage_lifecycle,
)

NOW = datetime(2026, 9, 16, tzinfo=UTC)
FLOORS = Floors(standard=2555, sensitive=3650, restricted=3650)


class _File:
    def __init__(
        self,
        file_id: str = "file-1",
        classification: str | None = "standard",
        created_at: datetime | None = None,
        storage_key: str = "tenants/t/documents/file-1/a.pdf",
        size_bytes: int = 10,
    ) -> None:
        self.id = file_id
        self.tenant_id = "11111111-1111-1111-1111-111111111111"
        self.classification = classification
        self.created_at = created_at or NOW
        self.storage_key = storage_key
        self.size_bytes = size_bytes


class _Held:
    def __init__(self, held: int) -> None:
        self.held = held


class _Result:
    def __init__(self, rows: list[Any], held: int = 0) -> None:
        self._rows = rows
        self._held = held

    def all(self) -> list[Any]:
        return self._rows

    def one(self) -> _Held:
        return _Held(self._held)


class _Session:
    def __init__(self, rows: list[Any] | None = None, held: int = 0) -> None:
        self._rows = rows or []
        self._held = held
        self.statements: list[tuple[str, dict[str, Any] | None]] = []
        self.commits = 0

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> _Result:
        text = str(statement)
        self.statements.append((text, parameters))
        if "count(*)" in text:
            return _Result([], self._held)
        if "select" in text and "from public.files" in text:
            return _Result(list(self._rows))
        if "returning id" in text:
            return _Result(list(self._rows))
        return _Result([])

    async def commit(self) -> None:
        self.commits += 1


class _Store:
    def __init__(self, fail: bool = False) -> None:
        self.deleted: list[str] = []
        self._fail = fail

    def delete(self, key: str) -> None:
        if self._fail:
            raise RuntimeError("the provider refused")
        self.deleted.append(key)


def test_a_retention_of_nothing_is_refused_before_anything_is_resolved() -> None:
    settings = LifecycleSettings(storage_retention_days_sensitive=0)
    with pytest.raises(ValueError, match="sensitive"):
        floors_from(settings)


def test_every_floor_is_checked_before_any_is_used() -> None:
    """One mistyped number must not act on the two that were right -- the same
    ordering the audit sweep uses, for the same reason."""
    settings = LifecycleSettings(storage_retention_days_restricted=-1)
    with pytest.raises(ValueError, match="restricted"):
        floors_from(settings)


def test_a_sensitive_object_is_kept_longer_than_a_standard_one() -> None:
    assert FLOORS.days_for("sensitive") > FLOORS.days_for("standard")
    assert FLOORS.days_for("restricted") == FLOORS.days_for("sensitive")
    # An unclassified object takes the standard floor rather than no floor.
    assert FLOORS.days_for(None) == FLOORS.days_for("standard")


async def test_a_date_is_derived_from_when_the_object_was_stored() -> None:
    """Resolving late must not grant an old file a fresh full term."""
    old = NOW - timedelta(days=1000)
    session = _Session([_File(created_at=old)])
    resolved = await resolve_retention(session, floors=FLOORS, limit=10)  # type: ignore[arg-type]

    assert resolved == 1
    update = next(p for t, p in session.statements if "set retain_until" in t and p is not None)
    assert update["until"] == old + timedelta(days=2555)
    assert update["policy"] == "platform:standard"


async def test_extension_only_ever_lengthens() -> None:
    """A floor raised today protects objects stored yesterday. A floor lowered
    today must not pull an existing date forward -- that direction is a
    configuration change deleting data."""
    session = _Session([_File()])
    await extend_to_floor(session, floors=FLOORS)  # type: ignore[arg-type]

    updates = [t for t, _ in session.statements if "set retain_until" in t]
    assert len(updates) == 3  # one per classification
    for statement in updates:
        assert "retain_until < created_at + make_interval" in statement
        assert "retain_until is not null" in statement


async def test_a_held_object_is_never_selected_for_removal() -> None:
    session = _Session(rows=[], held=4)
    purged, held, stranded = await purge_expired(session, _Store(), limit=10)  # type: ignore[arg-type]

    assert (purged, held, stranded) == (0, 4, 0)
    due = next(t for t, _ in session.statements if "order by f.retain_until" in t)
    assert "not public.under_legal_hold(f.tenant_id, 'files')" in due
    assert "f.legal_hold = false" in due


async def test_the_row_is_marked_before_the_object_is_removed() -> None:
    """A crash between the two must leave a row that says what was supposed to
    happen, not a ready row with no bytes behind it."""
    store = _Store()
    session = _Session(rows=[_File()])
    purged, _, _ = await purge_expired(session, store, limit=1)  # type: ignore[arg-type]

    assert purged == 1
    assert store.deleted == ["tenants/t/documents/file-1/a.pdf"]

    order = [t for t, _ in session.statements if "public.files" in t]
    mark = next(i for i, t in enumerate(order) if "status = 'purged'" in t)
    delete = next(i for i, t in enumerate(order) if t.startswith("delete from public.files"))
    assert mark < delete


async def test_an_object_the_provider_will_not_delete_is_stranded_not_lost() -> None:
    """Its row stays marked `purged`, which reconciliation later reports as a
    row without an object -- a finding rather than a silent leak."""
    session = _Session(rows=[_File()])
    purged, _, stranded = await purge_expired(session, _Store(fail=True), limit=1)  # type: ignore[arg-type]

    assert (purged, stranded) == (0, 1)
    assert not any(t.startswith("delete from public.files") for t, _ in session.statements)


async def test_the_sweep_is_off_unless_asked_for() -> None:
    assert await sweep_storage_lifecycle({}) == {"status": "skipped", "reason": "not enabled"}


async def test_an_enabled_sweep_without_a_database_skips_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from koras_worker.tasks import storage_lifecycle

    monkeypatch.setattr(storage_lifecycle.lifecycle, "storage_lifecycle_enabled", True)
    monkeypatch.setattr(storage_lifecycle.settings, "database_url", "")
    assert await sweep_storage_lifecycle({}) == {"status": "skipped", "reason": "no database"}


async def test_an_enabled_sweep_without_storage_credentials_skips_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from koras_worker.tasks import storage_lifecycle

    monkeypatch.setattr(storage_lifecycle.lifecycle, "storage_lifecycle_enabled", True)
    monkeypatch.setattr(storage_lifecycle.settings, "database_url", "postgresql://x/y")
    monkeypatch.setattr(storage_lifecycle.lifecycle, "storage_bucket", "")
    assert await sweep_storage_lifecycle({}) == {"status": "skipped", "reason": "no storage"}
