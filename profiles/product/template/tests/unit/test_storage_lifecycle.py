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
    retry_stranded,
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
    def __init__(
        self,
        rows: list[Any] | None = None,
        held: int = 0,
        *,
        stranded: list[Any] | None = None,
    ) -> None:
        self._rows = rows or []
        self._held = held
        self._stranded = stranded or []
        self.statements: list[tuple[str, dict[str, Any] | None]] = []
        self.commits = 0

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> _Result:
        text = str(statement)
        self.statements.append((text, parameters))
        if "count(*)" in text:
            return _Result([], self._held)
        # The backlog query, asked before the due one. Answering it with the
        # due rows would let this fixture delete objects the sweep had not
        # selected.
        if "status = 'purged'" in text:
            return _Result(list(self._stranded))
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


def test_the_floor_over_ordinary_content_does_not_outlast_the_customer_s_wish() -> None:
    """`standard` has no platform floor, and that means no deletion at all.

    The number does two jobs -- the floor a tenant may not go below, and the
    period after which an object is removed when nobody said otherwise -- and
    both wrong answers came from treating it as one. At 2555 a customer could
    not delete their own document for seven years. At 1, the correction made
    earlier the same day, every standard object would have been purged the day
    after upload in any product that switched the sweep on.

    Unset is the answer to both: no floor to breach, and no date to come due.
    ADR 0003 decision 15.
    """
    defaults = LifecycleSettings()
    assert defaults.storage_retention_days_standard is None
    assert defaults.storage_retention_days_sensitive == 3650
    assert defaults.storage_retention_days_restricted == 3650
    floors_from(defaults)


def test_a_sensitive_object_is_kept_longer_than_a_standard_one() -> None:
    assert FLOORS.days_for("sensitive") > FLOORS.days_for("standard")
    assert FLOORS.days_for("restricted") == FLOORS.days_for("sensitive")
    # An unclassified object takes the standard floor rather than no floor.
    assert FLOORS.days_for(None) == FLOORS.days_for("standard")


async def test_a_date_is_derived_from_when_the_object_was_stored() -> None:
    """Resolving late must not grant an old file a fresh full term.

    The arithmetic moved into SQL when tenant overrides arrived, so what is
    asserted here is that the statement derives from `created_at` rather than
    from now, and resolves the floor against the tenant.
    """
    old = NOW - timedelta(days=1000)
    session = _Session([_File(created_at=old)])
    resolved = await resolve_retention(session, floors=FLOORS, limit=10)  # type: ignore[arg-type]

    assert resolved == 1
    statement, params = next(
        (t, p) for t, p in session.statements if "set retain_until" in t and p is not None
    )
    assert "f.created_at + make_interval" in statement
    assert "public.retention_days_for(f.tenant_id" in statement
    assert "now()" not in statement
    assert params["days"] == 2555
    assert params["kind"] == "storage_standard"
    assert params["policy"] == "platform:standard"


async def test_extension_only_ever_lengthens() -> None:
    """A floor raised today protects objects stored yesterday. A floor lowered
    today must not pull an existing date forward -- that direction is a
    configuration change deleting data."""
    session = _Session([_File()])
    await extend_to_floor(session, floors=FLOORS)  # type: ignore[arg-type]

    updates = [(t, p) for t, p in session.statements if "set retain_until" in t]
    assert len(updates) == 3  # one per classification
    for statement, _ in updates:
        assert "f.retain_until < f.created_at + make_interval" in statement
        assert "f.retain_until is not null" in statement
        # Against the resolved floor, so a tenant that lengthened its own
        # retention is extended to *its* number rather than the platform's.
        assert "public.retention_days_for(f.tenant_id" in statement

    kinds = {p["classification"]: p["kind"] for _, p in updates if p is not None}
    assert kinds == {
        "standard": "storage_standard",
        "sensitive": "storage_sensitive",
        "restricted": "storage_restricted",
    }


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


async def test_a_stranded_object_is_tried_again_on_the_next_run() -> None:
    """`_DUE` excludes a row already marked `purged`, so before this existed a
    row that stranded once stranded for ever -- and reconciliation could not
    find it either, because it reads every `files` row as claimed."""
    stranded = _File(file_id="file-9", storage_key="tenants/t/documents/f9/nine.pdf")
    session = _Session(stranded=[stranded])
    store = _Store()

    cleared, still = await retry_stranded(session, store, limit=10)  # type: ignore[arg-type]

    assert cleared == 1
    assert still == 0
    assert store.deleted == ["tenants/t/documents/f9/nine.pdf"]
    # The row goes only once the object has: the reverse leaves bytes with no
    # record behind them.
    assert any("delete from public.files" in text for text, _ in session.statements)


async def test_a_backlog_the_bucket_still_refuses_keeps_its_row() -> None:
    stranded = _File(file_id="file-9", storage_key="tenants/t/documents/f9/nine.pdf")
    session = _Session(stranded=[stranded])

    cleared, still = await retry_stranded(session, _Store(fail=True), limit=10)  # type: ignore[arg-type]

    assert (cleared, still) == (0, 1)
    assert not any("delete from public.files" in text for text, _ in session.statements)


async def test_a_class_with_no_floor_and_no_override_is_given_no_date() -> None:
    """The defect this exists to catch is not subtle and would not have looked
    like one: with a one-day floor, `retain_until` became `created_at + 1 day`
    and the purge pass removed every standard object the following night.

    A resolved zero must write nothing. Null is not expired -- it means nobody
    has decided -- and the due query never selects a null date.
    """
    session = _Session(rows=[_File()])
    floors = Floors(standard=None, sensitive=3650, restricted=3650)

    await resolve_retention(session, floors=floors, limit=10)  # type: ignore[arg-type]

    statements = [text for text, _ in session.statements if "set retain_until" in text]
    assert statements, "the statement did not run at all"
    # The guard is in the statement rather than in Python, so that a tenant
    # override can still resolve above an absent floor and produce a date.
    assert all("retention_days_for(f.tenant_id, :kind, :days) > 0" in t for t in statements)


async def test_an_absent_floor_is_passed_as_zero_rather_than_as_null() -> None:
    """`make_interval(days => null)` is null, and `retain_until = null` would
    read as "nobody decided" by luck rather than by the guard. Zero makes the
    comparison in the statement decide it."""
    session = _Session(rows=[_File()])
    await resolve_retention(  # type: ignore[arg-type]
        session, floors=Floors(standard=None, sensitive=3650, restricted=3650), limit=10
    )
    params = [p for t, p in session.statements if "set retain_until" in t][0]
    assert params is not None and params["days"] == 0


def test_an_unset_floor_is_allowed_and_a_zero_one_is_not() -> None:
    """Unset is a decision -- this class is not automatically deleted. Zero is
    a mistyped number, and it would be a wipe."""
    floors_from(LifecycleSettings(storage_retention_days_standard=None))
    with pytest.raises(ValueError, match="at least 1 day"):
        floors_from(LifecycleSettings(storage_retention_days_standard=0))
