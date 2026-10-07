"""An in-memory `files` table behind the session interface the transitions use.

Kept under `tests/` and imported by nothing in the worker. It models what the
transitions rely on and nothing more: the tenant binding (a row is visible only
to the tenant bound on the session, as RLS would), the guarded `select ... for
update`, transaction boundaries (writes are staged and applied on commit,
discarded on rollback) and the audit insert. The SQL itself is exercised against
a real PostgreSQL in `tests/integration/test_scan_transition_real.py`.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from koras_worker.scanning import transition as t

TENANT = "11111111-1111-4111-8111-111111111111"
OTHER_TENANT = "22222222-2222-4222-8222-222222222222"
FILE = "33333333-3333-4333-8333-333333333333"
OTHER_FILE = "44444444-4444-4444-8444-444444444444"
NOW = datetime(2026, 10, 4, 12, 30, 0, tzinfo=UTC)


def row(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    values: dict[str, Any] = {
        "id": FILE,
        "tenant_id": TENANT,
        "status": "ready",
        "scan_status": "pending",
        "scan_note": "",
        "scan_attempts": 0,
        "scan_attempted_at": None,
        "scan_failure": None,
        "scan_object_etag": None,
        "checksum_sha256": None,
        "checksum_verified_at": None,
        "size_bytes": 100,
        "storage_key": f"tenants/{TENANT}/imports/{FILE}/a.csv",
    }
    values.update(overrides)
    return values


class _Mappings:
    def __init__(self, found: dict[str, Any] | None) -> None:
        self._found = found

    def first(self) -> dict[str, Any] | None:
        return self._found


class _Result:
    def __init__(self, found: dict[str, Any] | None = None, scalar: Any = None) -> None:  # noqa: ANN401
        self._found = found
        self._scalar = scalar

    def mappings(self) -> _Mappings:
        return _Mappings(self._found)

    def scalar_one(self) -> Any:  # noqa: ANN401
        return self._scalar


@dataclass
class FakeSession:
    rows: list[dict[str, Any]]
    #: Fail the nth audit insert (1-based) to prove state and audit are one transaction.
    fail_audit_insert: bool = False
    fail_update: bool = False
    tenant: str | None = None
    audit_rows: list[dict[str, Any]] = field(default_factory=list)
    commits: int = 0
    rollbacks: int = 0
    writes: int = 0
    _snapshot: tuple[list[dict[str, Any]], list[dict[str, Any]]] | None = None
    _locked: dict[str, Any] | None = None

    def _begin_write(self) -> None:
        if self._snapshot is None:
            self._snapshot = (copy.deepcopy(self.rows), copy.deepcopy(self.audit_rows))

    def _find(
        self, params: dict[str, Any], scan_states: tuple[str, ...] = ("pending",)
    ) -> dict[str, Any] | None:
        for candidate in self.rows:
            if (
                candidate["id"] == params["file_id"]
                and candidate["tenant_id"] == params["tenant_id"]
                and self.tenant == candidate["tenant_id"]  # RLS: the bound tenant only
                and candidate["status"] == "ready"
                and candidate["scan_status"] in scan_states
            ):
                return candidate
        return None

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Result:  # noqa: ANN401
        params = params or {}
        if statement is t._AS_TENANT:
            self.tenant = params["tenant_id"]
            return _Result()
        if "audit_events" in str(statement):
            if self.fail_audit_insert:
                raise RuntimeError("audit insert failed")
            self._begin_write()
            self.audit_rows.append(dict(params))
            return _Result()
        # The infected statements carry the wider guard; all others, pending only.
        wide = statement is t._LOCK_INFECTED or statement is t._INFECTED
        target = self._find(params, ("pending", "clean") if wide else ("pending",))
        if statement is t._LOCK_INFECTED:
            self._locked = target
            return _Result(copy.deepcopy(target) if target else None)
        if statement is t._LOCK:
            self._locked = target
            return _Result(copy.deepcopy(target) if target else None)
        if self.fail_update:
            raise RuntimeError("update failed")
        # Every write here carries the guard in its own predicate, as the real
        # statements do, so a row that left `pending` is not touched.
        if target is None:
            return _Result(scalar=None)
        self._begin_write()
        self.writes += 1
        if statement is t._ATTEMPT:
            target["scan_attempts"] = min(target["scan_attempts"] + 1, params["ceiling"])
            target["scan_attempted_at"] = params["now"]
            return _Result(scalar=target["scan_attempts"])
        if statement is t._FAILURE:
            target["scan_failure"] = params["failure"]
        elif statement is t._INFECTED:
            target.update(
                scan_status="infected",
                status="quarantined",
                scan_note=params["note"],
                scan_failure=None,
                scan_object_etag=None,
            )
        elif statement is t._CLEAN:
            target.update(
                scan_status="clean",
                scan_note=params["note"],
                scan_failure=None,
                scan_object_etag=params["etag"],
            )
        else:  # pragma: no cover - a statement the transitions should not issue
            raise AssertionError(f"unexpected statement: {statement}")
        return _Result()

    async def commit(self) -> None:
        self.commits += 1
        self._snapshot = None
        self.tenant = None  # transaction-local, as `set_config(..., true)` is

    async def rollback(self) -> None:
        self.rollbacks += 1
        if self._snapshot is not None:
            self.rows, self.audit_rows = self._snapshot
            self._snapshot = None
        self.tenant = None

    def get(self, file_id: str = FILE) -> dict[str, Any]:
        return next(r for r in self.rows if r["id"] == file_id)

    @property
    def actions(self) -> list[str]:
        return [r["action"] for r in self.audit_rows]
