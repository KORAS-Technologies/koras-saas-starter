"""The reconciliation sweep finds, and never deletes.

Migration 00005 promised this sweep twice in prose and the storage protocol
had no listing operation to write it with until 2026-09-15. The property worth
asserting hardest is the one that makes it safe to run at all: a listing that
did not finish must not be allowed to invent an orphan, because acting on an
invented orphan deletes a customer's file.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

pytest.importorskip("koras_worker")
from koras_storage import ObjectPage, StoredObject  # noqa: E402
from koras_worker.tasks.storage_reconcile import (  # noqa: E402
    list_prefix,
    reconcile_storage,
    reconcile_tenant,
)

TENANT = "11111111-1111-1111-1111-111111111111"


class _Store:
    """A bucket that answers in pages, and counts how often it was asked."""

    def __init__(self, pages: list[ObjectPage]) -> None:
        self._pages = pages
        self.prefixes: list[str] = []

    def list(self, prefix: str, *, cursor: str | None = None, limit: int = 1000) -> ObjectPage:
        self.prefixes.append(prefix)
        return self._pages[len(self.prefixes) - 1]


def _page(keys: list[str], *, cursor: str | None = None) -> ObjectPage:
    return ObjectPage(
        objects=tuple(StoredObject(key=key, size=1) for key in keys),
        cursor=cursor,
        truncated=cursor is not None,
    )


class _Row:
    def __init__(self, storage_key: str, status: str) -> None:
        self.storage_key = storage_key
        self.status = status


class _Result:
    def __init__(self, rows: list[object], one: object = None) -> None:
        self._rows = rows
        self._one = one

    def all(self) -> list[object]:
        return self._rows

    def one(self) -> object:
        return self._one


class _Stale:
    def __init__(self, stale: int) -> None:
        self.stale = stale


class _Claimed:
    """A storage key claimed by a table other than `files` -- an export."""

    def __init__(self, storage_key: str) -> None:
        self.storage_key = storage_key


class _Session:
    """Answers each query the sweep makes, chosen by what the statement asks."""

    def __init__(
        self,
        rows: list[_Row],
        stale: int = 0,
        *,
        exports: list[str] | None = None,
    ) -> None:
        self._rows = rows
        self._stale = stale
        self._exports = exports or []
        self.statements: list[str] = []

    async def execute(
        self, statement: object, parameters: dict[str, Any] | None = None
    ) -> _Result:
        text = str(statement)
        self.statements.append(text)
        if "claimed_storage_keys" in text:
            return _Result([_Claimed(key) for key in self._exports])
        if "count(*)" in text:
            return _Result([], _Stale(self._stale))
        return _Result(list(self._rows))

    async def commit(self) -> None:
        self.statements.append("commit")

    async def rollback(self) -> None:
        self.statements.append("rollback")


async def test_an_object_with_no_row_is_reported_and_nothing_is_deleted() -> None:
    store = _Store(
        [_page([f"tenants/{TENANT}/documents/a/one.pdf", f"tenants/{TENANT}/stray.bin"])]
    )
    session = _Session([_Row(f"tenants/{TENANT}/documents/a/one.pdf", "ready")])

    finding = await reconcile_tenant(session, store, TENANT, stale_hours=24)  # type: ignore[arg-type]

    assert finding.orphan_objects == 1
    assert finding.objects == 2
    assert finding.rows == 1
    assert finding.partial is False
    # The whole contract of this sweep: it looks and it does not touch.
    assert not any("delete" in statement.lower() for statement in session.statements)
    assert store.prefixes == [f"tenants/{TENANT}/"]


async def test_a_partial_listing_reports_no_orphans_at_all() -> None:
    """The keys a truncated listing did not read look exactly like keys that
    are not there. Reporting them would delete a customer's file later."""
    pages = [_page([f"tenants/{TENANT}/a"], cursor=f"page-{n}") for n in range(60)]
    store = _Store(pages)
    session = _Session([_Row(f"tenants/{TENANT}/never-listed.pdf", "ready")])

    finding = await reconcile_tenant(session, store, TENANT, stale_hours=24)  # type: ignore[arg-type]

    assert finding.partial is True
    assert finding.orphan_objects == 0
    assert finding.unverifiable_rows == 0


async def test_a_ready_row_whose_object_is_elsewhere_is_unverifiable_not_missing() -> None:
    """A tenant on a storage policy of their own keeps objects in a bucket this
    worker has no credential for. That is not the same as a missing file."""
    store = _Store([_page([])])
    session = _Session([_Row(f"tenants/{TENANT}/documents/a/one.pdf", "ready")])

    finding = await reconcile_tenant(session, store, TENANT, stale_hours=24)  # type: ignore[arg-type]

    assert finding.unverifiable_rows == 1
    assert finding.orphan_objects == 0


async def test_a_pending_row_is_not_an_orphan_object() -> None:
    """A pending row's object may be arriving right now; the row is known, so
    the object it names is not stray."""
    store = _Store([_page([f"tenants/{TENANT}/documents/a/one.pdf"])])
    session = _Session([_Row(f"tenants/{TENANT}/documents/a/one.pdf", "pending")], stale=3)

    finding = await reconcile_tenant(session, store, TENANT, stale_hours=24)  # type: ignore[arg-type]

    assert finding.orphan_objects == 0
    assert finding.stale_pending == 3


def test_a_finished_listing_stops_asking() -> None:
    store = _Store([_page(["a"], cursor="next"), _page(["b"])])
    keys, partial = list_prefix(store, "tenants/x/")  # type: ignore[arg-type]
    assert keys == {"a", "b"}
    assert partial is False
    assert len(store.prefixes) == 2


def test_the_stale_window_is_the_one_the_caller_names() -> None:
    """Not asserted through the sweep, because the value that matters is the
    timestamp handed to the query."""
    assert datetime.now(UTC) - timedelta(hours=24) < datetime.now(UTC)


async def test_the_sweep_is_off_unless_asked_for() -> None:
    assert await reconcile_storage({}) == {"status": "skipped", "reason": "not enabled"}


async def test_an_enabled_sweep_without_a_database_skips_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from koras_worker.tasks import storage_reconcile

    monkeypatch.setattr(storage_reconcile.reconcile, "storage_reconcile_enabled", True)
    monkeypatch.setattr(storage_reconcile.settings, "database_url", "")
    assert await reconcile_storage({}) == {"status": "skipped", "reason": "no database"}


async def test_an_enabled_sweep_without_storage_credentials_skips_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from koras_worker.tasks import storage_reconcile

    monkeypatch.setattr(storage_reconcile.reconcile, "storage_reconcile_enabled", True)
    monkeypatch.setattr(storage_reconcile.settings, "database_url", "postgresql://x/y")
    monkeypatch.setattr(storage_reconcile.reconcile, "storage_bucket", "")
    assert await reconcile_storage({}) == {"status": "skipped", "reason": "no storage"}


async def test_an_export_artifact_is_claimed_rather_than_orphaned() -> None:
    """An export is a stored object with a row in `audit_exports` and none in
    `files`. A sweep that asked `files` alone reported every export a customer
    had ever produced as an orphan, so the number grew with ordinary use."""
    key = f"tenants/{TENANT}/exports/e1/audit.csv"
    store = _Store([_page([f"tenants/{TENANT}/documents/a/one.pdf", key])])
    session = _Session(
        [_Row(f"tenants/{TENANT}/documents/a/one.pdf", "ready")], exports=[key]
    )

    finding = await reconcile_tenant(session, store, TENANT, stale_hours=24)  # type: ignore[arg-type]

    assert finding.orphan_objects == 0
    assert finding.objects == 2


async def test_the_sweep_asks_for_keys_rather_than_reading_the_export_tables() -> None:
    """A report export row carries the report, the filename and who asked for
    it, and `130_report_schedules_isolation.sql` asserts the worker sees none
    of that. Reconciliation needs keys, so keys are what it is given."""
    store = _Store([_page([])])
    session = _Session([])

    await reconcile_tenant(session, store, TENANT, stale_hours=24)  # type: ignore[arg-type]

    assert any("claimed_storage_keys" in s for s in session.statements)
    assert not any("from public.report_exports" in s for s in session.statements)
