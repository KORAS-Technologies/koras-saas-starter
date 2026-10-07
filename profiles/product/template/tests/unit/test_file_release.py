"""The release rule for stored content, in both modes (ADR 0013, `secure_files`).

`core/file_release.py` is generated in every product and dispatches on one constant. These
assert it for **both** values of that constant, whichever one this product was generated with
(the module's constant is switched for the duration of a test, which is what the generator
would have rendered):

* with the capability, only `scan_status = 'clean'` on a `ready` file of the caller's own
  tenant, on a final key of that tenant, stamped by the scanner, releases -- and nothing else
  does, for every state the column can hold and for values it cannot;
* without it, the rule is exactly the platform's: `withheld()` for a download, the narrower
  deny-list an import always had, and no identity consulted;
* the same stored row is decided differently by the two, and each answer is stated.

`test_release_bypass_guards.py` is the static half: that nothing routes around this module.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_api.core import file_release, file_scan, secure_files  # noqa: E402
from koras_api.core.file_release import (  # noqa: E402
    LEGACY_IMPORT_REFUSED,
    LEGACY_WITHHELD,
    RELEASABLE_SCAN_STATUSES,
    RELEASABLE_SQL,
    refusal_reason,
    releasable,
)

REPO = Path(__file__).resolve().parents[2]
TENANT = "00000000-0000-0000-0000-00000000000a"
OTHER = "00000000-0000-0000-0000-00000000000b"
FILE_ID = "11111111-1111-1111-1111-111111111111"
GENERATION = "2222222a-2222-4222-8222-22222222222b"
FINAL = f"tenants/{TENANT}/documents/{FILE_ID}/final/{GENERATION}/a.pdf"


@pytest.fixture
def secure(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(file_release, "SECURE_FILES", True)
    yield


@pytest.fixture
def legacy(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(file_release, "SECURE_FILES", False)
    yield


def _asks(scan_status: object, status: object = "ready", **identity: object) -> bool:
    arguments: dict[str, Any] = {
        "tenant_id": TENANT,
        "row_tenant_id": TENANT,
        "storage_key": FINAL,
        "scan_object_etag": "etag-1",
    }
    arguments.update(identity)
    return releasable(status=status, scan_status=scan_status, **arguments)


def test_the_module_constant_is_the_generated_one() -> None:
    """One constant, rendered by the generator; the rule has no other source of the mode."""
    assert file_release.SECURE_FILES is secure_files.SECURE_FILES


# -- with the capability ---------------------------------------------------------------------


def test_only_clean_is_a_releasing_verdict() -> None:
    assert frozenset({"clean"}) == RELEASABLE_SCAN_STATUSES


@pytest.mark.usefixtures("secure")
@pytest.mark.parametrize(
    ("scan_status", "expected"),
    [
        ("clean", True),
        ("pending", False),
        ("infected", False),
        ("skipped", False),
        (None, False),
        ("", False),
        ("CLEAN", False),
        (" clean", False),
        ("clean ", False),
        ("cleaned", False),
        ("quarantined", False),
        ("unknown", False),
        (b"clean", False),
        (1, False),
        (True, False),
        (["clean"], False),
        ({"clean"}, False),
    ],
)
def test_the_verdict_decides_on_a_ready_file(scan_status: object, expected: bool) -> None:
    assert _asks(scan_status) is expected


@pytest.mark.usefixtures("secure")
@pytest.mark.parametrize(
    "status",
    ["pending", "quarantined", "deleted", "failed", "", "READY", " ready", None, b"ready", 1],
)
def test_a_clean_verdict_does_not_release_a_file_that_is_not_ready(status: object) -> None:
    assert _asks("clean", status) is False


@pytest.mark.usefixtures("secure")
def test_a_missing_or_wrongly_typed_row_value_never_releases() -> None:
    assert releasable(status=None, scan_status=None) is False
    assert releasable(status=object(), scan_status=object()) is False


@pytest.mark.usefixtures("secure")
def test_a_clean_ready_file_with_no_identity_is_not_released() -> None:
    """The identity is required in effect: a consumer that cannot supply it gets False."""
    assert releasable(status="ready", scan_status="clean") is False
    assert releasable(status="ready", scan_status="clean", consumer="import") is False
    assert releasable(status="ready", scan_status="clean", consumer="indexing") is False


@pytest.mark.usefixtures("secure")
@pytest.mark.parametrize("consumer", ["download", "indexing", "import", "listing"])
def test_every_consumer_gets_the_same_strict_answer(consumer: Any) -> None:  # noqa: ANN401
    verdicts = {
        scan: releasable(
            status="ready",
            scan_status=scan,
            consumer=consumer,
            tenant_id=TENANT,
            row_tenant_id=TENANT,
            storage_key=FINAL,
            scan_object_etag="etag-1",
        )
        for scan in ("clean", "pending", "skipped", "infected", None)
    }
    assert verdicts == {
        "clean": True,
        "pending": False,
        "skipped": False,
        "infected": False,
        None: False,
    }


# -- identity: the verdict is about this tenant's own object ----------------------------------


@pytest.mark.usefixtures("secure")
@pytest.mark.parametrize(
    "identity",
    [
        # Tenant against tenant.
        {"row_tenant_id": OTHER},
        {"tenant_id": OTHER},
        {"row_tenant_id": None},
        {"tenant_id": None},
        {"tenant_id": ""},
        {"row_tenant_id": "", "tenant_id": ""},
        {"row_tenant_id": TENANT.upper()},
        {"tenant_id": 7, "row_tenant_id": 7},
        # The key's own tenant segment against the row's tenant.
        {"storage_key": f"tenants/{OTHER}/documents/{FILE_ID}/final/{GENERATION}/a.pdf"},
        {"storage_key": f"tenants/{TENANT.upper()}/documents/{FILE_ID}/final/{GENERATION}/a.pdf"},
        {"storage_key": f"tenants//documents/{FILE_ID}/final/{GENERATION}/a.pdf"},
        # The key is not a final key: a ticket could have written it, or it is from before.
        {"storage_key": f"tenants/{TENANT}/documents/{FILE_ID}/incoming/{GENERATION}/a.pdf"},
        {"storage_key": f"tenants/{TENANT}/documents/{FILE_ID}/a.pdf"},
        {"storage_key": f"tenants/{TENANT}/documents/{FILE_ID}/final/{GENERATION}/x/a.pdf"},
        {"storage_key": f"tenants/{TENANT}/documents/{FILE_ID}/final/{GENERATION}/"},
        {"storage_key": f"tenants/{TENANT}/documents/{FILE_ID}/final/{GENERATION.upper()}/a.pdf"},
        {"storage_key": f"tenants/{TENANT}/documents/{FILE_ID}/final/g/a.pdf"},
        {"storage_key": f"other/{TENANT}/documents/{FILE_ID}/final/{GENERATION}/a.pdf"},
        {"storage_key": f"tenants/{TENANT}//{FILE_ID}/final/{GENERATION}/a.pdf"},
        {"storage_key": None},
        {"storage_key": b"x"},
        {"storage_key": ""},
        # The scanner's stamp.
        {"scan_object_etag": None},
        {"scan_object_etag": ""},
        {"scan_object_etag": b"etag"},
        {"scan_object_etag": 5},
    ],
)
def test_a_clean_ready_file_whose_identity_does_not_hold_is_not_released(
    identity: dict[str, object],
) -> None:
    assert _asks("clean", **identity) is False


@pytest.mark.usefixtures("secure")
def test_another_tenants_object_can_never_become_releasable() -> None:
    """Whatever the row says about itself, the caller's tenant has to be the key's tenant too."""
    theirs = f"tenants/{OTHER}/documents/{FILE_ID}/final/{GENERATION}/a.pdf"
    for tenant, row_tenant, key in (
        (TENANT, TENANT, theirs),  # this tenant's row, pointed at their object
        (TENANT, OTHER, theirs),  # their row, their object, asked by this tenant
        (OTHER, OTHER, FINAL),  # their row, this tenant's object
        (TENANT, OTHER, FINAL),  # their row, this tenant's object, asked by this tenant
        (OTHER, TENANT, FINAL),  # this tenant's row, asked by them
    ):
        assert not _asks(
            "clean", tenant_id=tenant, row_tenant_id=row_tenant, storage_key=key
        ), (tenant, row_tenant, key)
    assert _asks("clean") is True


@pytest.mark.usefixtures("secure")
@pytest.mark.parametrize(
    ("status", "scan_status", "reason"),
    [
        ("ready", "pending", "pending"),
        ("ready", "skipped", "skipped"),
        ("ready", "infected", "infected"),
        ("quarantined", "infected", "infected"),
        ("quarantined", "clean", "infected"),
        ("ready", None, "unknown"),
        ("ready", "mystery", "unknown"),
        ("ready", 7, "unknown"),
        # A clean row with a failed identity has no reason a person can act on.
        ("ready", "clean", "unknown"),
    ],
)
def test_the_refusal_reason_is_a_closed_word(
    status: object, scan_status: object, reason: str
) -> None:
    assert refusal_reason(status=status, scan_status=scan_status) == reason


def test_the_sql_spelling_says_the_same_thing() -> None:
    assert "f.status = 'ready'" in RELEASABLE_SQL
    assert "f.scan_status = 'clean'" in RELEASABLE_SQL
    assert "f.scan_object_etag is not null" in RELEASABLE_SQL
    assert "f.tenant_id::text" in RELEASABLE_SQL
    assert "/final/" in RELEASABLE_SQL
    assert " or " not in RELEASABLE_SQL.lower()
    assert " in " not in RELEASABLE_SQL.lower()


# -- without the capability --------------------------------------------------------------------


@pytest.mark.usefixtures("legacy")
@pytest.mark.parametrize(
    "scan_status",
    ["clean", "pending", "skipped", "infected", None, "", "CLEAN", "weird", "quarantined"],
)
def test_without_the_capability_a_download_is_withheld_exactly_as_the_platform_seam_does(
    scan_status: object,
) -> None:
    for status in ("ready", "pending", None, "quarantined"):
        assert releasable(status=status, scan_status=scan_status) is (
            not file_scan.withheld(scan_status)  # type: ignore[arg-type]
        )
    assert releasable(status="ready", scan_status="pending") is True
    assert releasable(status="ready", scan_status="skipped") is True
    assert releasable(status="ready", scan_status="infected") is False


@pytest.mark.usefixtures("legacy")
@pytest.mark.parametrize(
    "scan_status", ["clean", "pending", "skipped", "infected", None, "", "weird"]
)
def test_without_the_capability_an_import_source_keeps_its_narrower_rule(
    scan_status: object,
) -> None:
    expected = (scan_status or "pending") not in LEGACY_IMPORT_REFUSED
    assert releasable(status="ready", scan_status=scan_status, consumer="import") is expected
    assert releasable(status="ready", scan_status="pending", consumer="import") is False
    assert releasable(status="ready", scan_status="clean", consumer="import") is True


@pytest.mark.usefixtures("legacy")
def test_without_the_capability_no_identity_is_consulted() -> None:
    """A product that never had the scanner has no stamp and no final key: and still serves."""
    assert releasable(status="ready", scan_status="clean") is True
    assert (
        releasable(
            status="ready",
            scan_status="clean",
            tenant_id=OTHER,
            row_tenant_id=TENANT,
            storage_key="legacy/key",
            scan_object_etag=None,
        )
        is True
    )


def test_the_legacy_constants_are_the_platform_seams_own() -> None:
    assert LEGACY_WITHHELD == file_scan.WITHHELD
    if importlib.util.find_spec("koras_api.core.imports") is not None:
        imports = importlib.import_module("koras_api.core.imports")
        deny_list = getattr(imports, "UNPARSEABLE_SCANS", None)
        # A product with the capability has no deny-list to agree with; one without keeps its own.
        assert deny_list is None or deny_list == LEGACY_IMPORT_REFUSED


# -- both modes, the same row ------------------------------------------------------------------

#: `scan_status` -> (what `secure_files` off releases, what it on releases), for a row that is
#: `ready` and, for the second, carries a full identity.
_SAME_ROW = {
    "clean": (True, True),
    "pending": (True, False),
    "skipped": (True, False),
    "infected": (False, False),
    None: (True, False),
}


@pytest.mark.parametrize("scan_status", list(_SAME_ROW))
def test_the_same_row_is_released_by_legacy_and_by_secure_as_stated(
    scan_status: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    for mode, expected in zip((False, True), _SAME_ROW[scan_status], strict=True):
        monkeypatch.setattr(file_release, "SECURE_FILES", mode)
        assert _asks(scan_status) is expected, (mode, scan_status)


def test_secure_never_releases_what_legacy_refuses() -> None:
    """The strict rule is a subset of the legacy one, for any row and any consumer."""
    for scan_status in ("clean", "pending", "skipped", "infected", None, "x"):
        for consumer in ("download", "import"):
            outcomes = []
            for mode in (False, True):
                file_release.SECURE_FILES = mode
                try:
                    outcomes.append(_asks(scan_status, consumer=consumer))
                finally:
                    file_release.SECURE_FILES = secure_files.SECURE_FILES
            legacy_releases, secure_releases = outcomes
            assert not (secure_releases and not legacy_releases), (scan_status, consumer)


# -- the module itself --------------------------------------------------------------------------


def test_the_module_exports_the_rule_and_no_deny_list_under_the_platforms_names() -> None:
    assert not hasattr(file_release, "WITHHELD")
    assert not hasattr(file_release, "withheld")
    assert not hasattr(file_release, "UNPARSEABLE_SCANS")


def test_the_rule_module_carries_no_dependency_the_worker_image_lacks() -> None:
    """The worker copies `file_release.py` and `secure_files.py`; the HTTP gate is API-only."""
    tree = ast.parse(
        (REPO / "services/api/koras_api/core/file_release.py").read_text(encoding="utf-8")
    )
    imported = [
        ("." * node.level) + (node.module or "")
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert set(imported) <= {"__future__", "typing", "uuid", ".secure_files"}, imported
