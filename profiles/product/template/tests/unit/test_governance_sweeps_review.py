"""The sweep defects two independent reviews found, and the tests that missed it.

The other half of that pass is `test_governance_review.py`, which covers the
routes and the storage seam. These three are here because they need the worker's
sweeps, and the sweeps arrive with the storage governance capability -- a test
importing `koras_worker.tasks.storage_reconcile` in a product generated without
it fails at import, which is the leak this repository has now had four times.
"""

from __future__ import annotations

import inspect
import os

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402

pytest.importorskip("koras_worker")


from koras_worker.tasks import (  # noqa: E402
    governance_expiry,
    storage_lifecycle,
    storage_reconcile,
)

# -- an export artifact is not an orphan ---------------------------------------


def test_reconciliation_counts_export_artifacts_as_claimed() -> None:
    """Export artifacts are stored objects with a row in their own table and
    none in `files`. A sweep that asked `files` alone reported every export a
    customer had ever produced as an orphan, so the headline number grew with
    ordinary use of the product."""
    claimed = str(storage_reconcile._CLAIMED_ELSEWHERE)
    assert "claimed_storage_keys" in claimed
    # Through the function, never the tables. A report export row carries the
    # report, the filename and who asked for it, and the RLS suite asserts the
    # worker sees none of that; keys are what a reconciliation needs.
    assert "report_exports" not in claimed
    assert "from public.audit_exports" not in claimed


def test_a_stranded_purge_is_retried_rather_than_left_to_reconciliation() -> None:
    """`_DUE` excludes `status = 'purged'`, so a row that stranded once
    stranded forever -- and reconciliation could not find it either, because it
    reads every `files` row into its claimed set."""
    assert "status = 'purged'" in str(storage_lifecycle._STRANDED)
    assert "retry_stranded" in inspect.getsource(storage_lifecycle.purge_expired)


def test_export_artifacts_expire_without_anybody_opening_a_page() -> None:
    """The only thing that retired an expired export was the exports list
    route. A tenant that stopped opening it kept every artifact indefinitely,
    while the product went on showing an expiry date on each."""
    assert callable(governance_expiry.expire_audit_exports)
    assert governance_expiry.expiry.audit_export_expiry_enabled is True
    source = inspect.getsource(governance_expiry.expire_audit_exports)
    # Object first, then row: the reverse leaves bytes nobody has a record of.
    assert source.index("store.delete") < source.index("_DELETE")
