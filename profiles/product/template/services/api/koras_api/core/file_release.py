"""The one rule for releasing a stored file's content (ADR 0013, `secure_files`).

**Every consumer that hands out, reads or derives from a file's bytes asks this
module, and nothing else.** There are two modes, selected by the one generated
constant `core.secure_files.SECURE_FILES`, and this module is generated in both:

* `SECURE_FILES = True`: **only a canonical `clean` verdict on a `ready` file
  releases**, and only when the verdict is about *this* tenant's *own* object.
  Every other state -- `pending`, `infected`, `skipped`, a missing value, an
  unrecognised value, a value of the wrong type -- withholds. There is no
  trusted-source exception, no `skipped` bypass, and `FILE_SCAN_BACKEND=none` is
  not one either: the product does not start without a scanner. There is no
  implicit fallback to the legacy rule: the branch below is chosen by the
  generated constant and by nothing at run time.
* `SECURE_FILES = False`: exactly what a product had before the capability
  existed. A download is withheld by `core/file_scan.py`'s deny-list
  (`withheld()`: only `infected`), and an import source by its own, narrower
  rule (a file nobody has looked at is not parsed). Both are reproduced here, not
  reinterpreted, and `tests/unit/test_file_release.py` holds them to the platform
  seam's own constants.

**Identity binding (secure mode).** A verdict is a statement about one object.
`releasable` therefore also requires, from the row the caller loaded:

* the row's tenant is the tenant the caller is acting for (a row of another
  tenant is not releasable, whatever it says about itself);
* `storage_key` is a *final* key -- the one shape only a worker writes after
  finalization, never one a ticket was signed for -- and its tenant segment is that
  same tenant, so a row cannot be pointed at another tenant's object;
* `scan_object_etag` is present: the scanner's `clean` transition writes it and
  nothing else does, so a `clean` row without it was not produced by the scanner.

A consumer that cannot supply an identity gets `False`. Two spellings of one
sentence, so a consumer that has to filter in the database does not write its own:
`releasable()` for a row in hand, and `RELEASABLE_SQL` for a statement.
A parity test runs both against a real PostgreSQL.

**Dependency-free on purpose.** The worker's image copies this file (the import
gate in `core/imports.py` asks the same question) beside `core/secure_files.py`,
which is standard library only. The HTTP gate that applies the rule to a request
and records the refusal is `core/file_release_gate.py`, which only the API loads.

What a refusal tells the caller is deliberately small: a state the person can act
on (still being checked, or not available) and nothing the scanner said.
"""

from __future__ import annotations

import uuid
from typing import Final, Literal

from .secure_files import SECURE_FILES

#: The only verdict that releases content when `SECURE_FILES` is on.
RELEASABLE_SCAN_STATUSES: Final[frozenset[str]] = frozenset({"clean"})

#: What `core/file_scan.py::withheld` refuses: the platform seam's deny-list, kept here so
#: the always-generated module needs nothing from a file that imports the database.
#: `tests/unit/test_file_release.py` asserts it is `file_scan.WITHHELD`, whatever the mode.
LEGACY_WITHHELD: Final[frozenset[str]] = frozenset({"infected"})

#: What an import refused before the capability: narrower than a download, because the
#: product reads the bytes itself and writes rows from them, unattended. This is the set
#: `core/imports.py` exports as `UNPARSEABLE_SCANS`.
LEGACY_IMPORT_REFUSED: Final[frozenset[str]] = frozenset({"pending", "skipped", "infected"})

_FINAL: Final = "final"

#: The final-key shape as a statement:
#: `tenants/<tenant>/<category>/<file>/final/<generation>/<name>`, with the generation a
#: canonical (lower-case, hyphenated) UUID. The tenant segment is the row's own `tenant_id`.
#: `[0-9a-f]` and `[^/]+` spell what `_is_final_key_of` checks segment by segment.
_FINAL_KEY_SQL: Final[str] = (
    "f.storage_key ~ ('^tenants/' || f.tenant_id::text || '/[^/]+/[^/]+/final/"
    "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[^/]+$')"
)

#: The secure rule for a statement. `f` is the alias of `public.files`.
RELEASABLE_SQL: Final[str] = (
    "(f.status = 'ready' and f.scan_status = 'clean' "
    "and f.scan_object_etag is not null and f.scan_object_etag <> '' "
    f"and {_FINAL_KEY_SQL})"
)

#: Every consumer that releases content names itself here, so a refusal can be
#: attributed. A closed set: a new consumer is added with its gate.
Consumer = Literal["download", "indexing", "import", "listing"]

#: Why a file is not releasable. A closed vocabulary; never free text.
Reason = Literal["pending", "infected", "skipped", "unknown"]


def _is_final_key_of(storage_key: object, tenant_id: str) -> bool:
    """`core/upload_window.py::is_final_key`, and the key's tenant is `tenant_id`.

    Spelled here because that module belongs to the capability and this one does not; a test
    holds the two to one answer over a corpus.
    """
    if not isinstance(storage_key, str):
        return False
    parts = storage_key.split("/")
    if len(parts) != 7 or parts[0] != "tenants" or parts[4] != _FINAL or parts[1] != tenant_id:
        return False
    if not all(parts[1:4]) or not parts[6]:
        return False
    try:
        return str(uuid.UUID(parts[5])) == parts[5]
    except ValueError:
        return False


def _identity_holds(
    tenant_id: object, row_tenant_id: object, storage_key: object, scan_object_etag: object
) -> bool:
    return (
        isinstance(tenant_id, str)
        and tenant_id != ""
        and row_tenant_id == tenant_id
        and _is_final_key_of(storage_key, tenant_id)
        and isinstance(scan_object_etag, str)
        and scan_object_etag != ""
    )


def releasable(
    *,
    status: object,
    scan_status: object,
    consumer: Consumer = "download",
    tenant_id: object = None,
    row_tenant_id: object = None,
    storage_key: object = None,
    scan_object_etag: object = None,
) -> bool:
    """Whether this file's stored content may be handed to anyone, for this consumer.

    With the capability: strict equality on both fields (so `None`, `"CLEAN"`, `"clean "`, a
    bytes value or a number is a refusal and not a coercion) **and** the identity above. The four
    identity arguments are required in effect: left out, the answer is `False`.

    Without it: the product's behaviour from before the capability, selected by `consumer`.
    The identity arguments are ignored; no column they name need exist.
    """
    if not SECURE_FILES:
        refused = LEGACY_IMPORT_REFUSED if consumer == "import" else LEGACY_WITHHELD
        return (scan_status or "pending") not in refused
    return (
        isinstance(status, str)
        and isinstance(scan_status, str)
        and status == "ready"
        and scan_status in RELEASABLE_SCAN_STATUSES
        and _identity_holds(tenant_id, row_tenant_id, storage_key, scan_object_etag)
    )


def refusal_reason(*, status: object, scan_status: object) -> Reason:
    """The closed-vocabulary reason a file is not releasable.

    Only meaningful when `releasable()` is false; for a releasable file it
    still answers `unknown`, so a caller cannot mistake it for a grant. An identity
    failure on an otherwise clean row is `unknown`: nothing the person can act on.
    """
    if scan_status == "infected" or status == "quarantined":
        return "infected"
    if scan_status == "pending":
        return "pending"
    if scan_status == "skipped":
        return "skipped"
    return "unknown"


__all__ = [
    "LEGACY_IMPORT_REFUSED",
    "LEGACY_WITHHELD",
    "RELEASABLE_SCAN_STATUSES",
    "RELEASABLE_SQL",
    "Consumer",
    "Reason",
    "refusal_reason",
    "releasable",
]
