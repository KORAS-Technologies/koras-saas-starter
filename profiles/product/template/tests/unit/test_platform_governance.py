"""The governance contract: counts, and nothing that names anybody.

The route is an aggregate over every tenant, so the assertion that matters most
is negative: no key, no filename, no actor, no hold reason. A cross-tenant route
that leaked one of those would be the worst disclosure in the product, and it
would look exactly like a useful console feature.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_api.routers import platform_governance as governance  # noqa: E402

STATEMENTS = (
    str(governance._STORAGE),
    str(governance._AUDIT),
    str(governance._HOLDS),
    str(governance._EXPORTS),
)

#: Columns that identify a person, a file or a matter. None may be selected.
FORBIDDEN = (
    "storage_key",
    "name",
    "uploaded_by",
    "actor_id",
    "requested_by",
    "approved_by",
    "reason",
    "target_id",
    "details",
    "scan_note",
    "error",
)


@pytest.mark.parametrize("column", FORBIDDEN)
def test_no_statement_selects_anything_that_names_somebody(column: str) -> None:
    for statement in STATEMENTS:
        selected = statement.split("from")[0]
        assert column not in selected, f"{column} is selected by a cross-tenant route"


def test_every_statement_groups_rather_than_listing() -> None:
    """An aggregate cannot accidentally return a row. Each of these groups, so
    the shape is a count per tenant rather than a page of records."""
    for statement in STATEMENTS:
        assert "group by" in statement
        assert "count(" in statement


def test_the_storage_summary_counts_what_only_the_product_knows() -> None:
    storage = str(governance._STORAGE)
    # Integrity is two numbers, never one: a claim is not a measurement.
    assert "with_checksum" in storage
    assert "checksum_verified" in storage
    # The number that shows a stopped lifecycle sweep, which nothing else does.
    assert "retention_unresolved" in storage
    assert "quarantined" in storage
    assert "held" in storage


def test_it_does_not_ask_for_what_the_platform_already_owns() -> None:
    """The provider and the quota come from the Control Plane's own policy and
    catalogue. Asking a product for them would be asking it to echo the
    platform's own records -- and it could not answer honestly anyway, because
    it reads both with the customer's token and a collector has none."""
    everything = " ".join(STATEMENTS)
    assert "provider" not in everything
    assert "quota" not in everything
    assert "limit_bytes" not in everything


def test_the_audit_summary_carries_the_oldest_row_per_class() -> None:
    """A class whose oldest row predates its retention is a sweep that stopped,
    and the log is the only other place that would say so."""
    audit = str(governance._AUDIT)
    assert "min(created_at)" in audit
    assert "classification" in audit


def test_holds_are_counted_by_scope_and_status_without_their_reason() -> None:
    holds = str(governance._HOLDS)
    assert "scope" in holds
    assert "status" in holds
    # A reason names a matter, and a matter usually names a person.
    assert "reason" not in holds


def test_the_window_bounds_exports_and_nothing_else() -> None:
    """Objects and holds are current state, not a window: how many exist now.
    Only the export counts are asked for since a date."""
    assert ":since" in str(governance._EXPORTS)
    assert ":since" not in str(governance._STORAGE)
    assert ":since" not in str(governance._AUDIT)
    assert ":since" not in str(governance._HOLDS)


def test_the_window_is_the_one_the_activity_half_uses() -> None:
    assert governance.WINDOW_DAYS == 92
