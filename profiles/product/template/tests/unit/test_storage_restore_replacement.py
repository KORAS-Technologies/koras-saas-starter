"""The rules of a restore that replaces a file's bytes, with no database (ADR 0013, layer 5).

What these hold, and what only the real-PostgreSQL module can: here the *decision* (which file
states may be replaced), the *shape* of a replacement key, what is written and read back before
a row may name it, and the statements' text (the object is never written at the old key). The
behaviour against the row, the locks and row-level security is
`tests/integration/test_restore_replacement_real.py`; against a real store and a real scanner,
`test_restore_orchestration_real.py`.
"""

from __future__ import annotations

import inspect
import os
import re
import sys
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

sys.path.insert(0, str(Path(__file__).resolve().parent))
pytest.importorskip("koras_worker")
from koras_api.core.upload_window import is_final_key, is_incoming_key  # noqa: E402
from koras_storage import Category  # noqa: E402
from koras_worker.scanning.objects import ObjectReference  # noqa: E402
from koras_worker.tasks import storage_restore  # noqa: E402
from koras_worker.tasks.storage_restore import (  # noqa: E402
    REFUSALS,
    REPLACEABLE_STATUSES,
    UNVERIFIED,
    replacement_key,
    replacement_refusal,
)
from restore_support import FILE, NEW, NEW_DIGEST, OLD, TENANT, MemStore  # noqa: E402

STATUSES = ("pending", "ready", "quarantined", "archived", "deleted", "purged")
SCANS = ("pending", "clean", "infected", "skipped")


def _decide(status: str, scan: str, recent: bool = False) -> str | None:
    return replacement_refusal(status=status, scan_status=scan, scan_recent=recent)


# -- who may be replaced -----------------------------------------------------------


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("scan", SCANS)
def test_every_combination_has_an_answer_and_only_the_safe_ones_are_replaceable(
    status: str, scan: str
) -> None:
    answer = _decide(status, scan)
    allowed = status in {"ready", "archived", "deleted", "purged"} and scan == "clean"
    if answer is None:
        assert allowed, f"{status}/{scan} must not be replaceable"
    else:
        assert answer in REFUSALS


def test_a_condemned_file_is_never_replaced_in_place() -> None:
    for status in STATUSES:
        assert _decide(status, "infected") == "condemned"
    assert _decide("quarantined", "clean") == "condemned"
    assert _decide("quarantined", "pending") == "condemned"


def test_a_file_whose_scan_may_be_running_is_not_replaced() -> None:
    """The scanner commits its verdict to the row, not to the object. A scan that read the old
    object and is still running would give its answer to the replacement."""
    assert _decide("ready", "pending") == "scan_unresolved"
    assert _decide("ready", "skipped") == "scan_unresolved"
    assert _decide("purged", "skipped") == "scan_unresolved"
    for status in ("archived", "deleted", "purged"):
        # A scan reads the row while `ready` + `pending`, and counts its attempt only after a
        # HEAD call; a file deleted in that moment and restored would take its stale verdict.
        assert _decide(status, "pending") == "scan_unresolved"


def test_a_recent_attempt_blocks_a_replacement_whatever_the_state() -> None:
    for status in REPLACEABLE_STATUSES:
        for scan in ("clean", "pending"):
            assert _decide(status, scan, recent=True) in {"scan_recent", "scan_unresolved"}


def test_the_replaceable_set_is_clean_ready_and_the_lifecycle_states_restore_exists_for() -> None:
    assert _decide("ready", "clean") is None
    for status in ("archived", "deleted", "purged"):
        assert _decide(status, "clean") is None
    assert _decide("pending", "clean") == "not_replaceable"


def test_a_refusal_sentence_carries_no_identifier() -> None:
    for sentence in (*REFUSALS.values(), UNVERIFIED):
        assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", sentence)
        assert "tenants/" not in sentence and "sha256" not in sentence.lower()


# -- the key -----------------------------------------------------------------------


def test_a_replacement_key_is_new_each_time_and_never_the_original() -> None:
    old = f"tenants/{TENANT}/documents/{FILE}/a.pdf"
    first = replacement_key(TENANT, FILE, "a.pdf", Category.DOCUMENTS)
    second = replacement_key(TENANT, FILE, "a.pdf", Category.DOCUMENTS)
    assert first != old and second != old and first != second


def test_a_replacement_key_is_exactly_the_shape_of_a_finalized_upload() -> None:
    """The one rule that says which key the scanner reads and the release rule accepts also
    covers a restore. A key of any other shape would be refused by both."""
    key = replacement_key(TENANT, FILE, "report.pdf", Category.DOCUMENTS)
    assert is_final_key(key)
    assert not is_incoming_key(key), "no ticket was ever, or could be, signed for it"
    assert key.startswith(f"tenants/{TENANT}/documents/{FILE}/final/")
    assert key.endswith("/report.pdf")
    parts = key.split("/")
    assert str(uuid.UUID(parts[5])) == parts[5], "the generation is a canonical UUID"


def test_a_replacement_key_is_one_the_scanner_will_read() -> None:
    key = replacement_key(TENANT, FILE, "Quarterly report (final).pdf", Category.DOCUMENTS)
    assert key.endswith("/Quarterly_report__final_.pdf")
    # Constructing it is the validation the scanner applies before reading anything.
    ObjectReference(TENANT, FILE, key)


def test_a_replacement_key_keeps_the_names_sanitising() -> None:
    key = replacement_key(TENANT, FILE, "../../etc/passwd", Category.DOCUMENTS)
    assert ".." not in key.split("/")
    assert is_final_key(key)
    ObjectReference(TENANT, FILE, key)


@pytest.mark.parametrize("category", list(Category))
def test_every_category_gives_a_final_key_of_its_own_tenant_and_file(category: Category) -> None:
    key = replacement_key(TENANT, FILE, "a.pdf", category)
    assert is_final_key(key)
    assert key.split("/")[:4] == ["tenants", TENANT, str(category), FILE]


def test_a_key_is_built_only_for_canonical_ids() -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - a bad id is refused whatever the wording
        replacement_key("not-a-uuid", FILE, "a.pdf", Category.DOCUMENTS)
    with pytest.raises(ValueError, match="not canonical"):
        replacement_key(TENANT, str(uuid.uuid4()).upper(), "a.pdf", Category.DOCUMENTS)


# -- what is written, and read back before a row may name it ------------------------


def test_the_write_asks_the_provider_to_verify_the_digest_and_reads_the_object_back() -> None:
    store = MemStore()
    key = f"tenants/{TENANT}/documents/{FILE}/final/{uuid.uuid4()}/a.pdf"

    assert storage_restore._write_verified(store, key, NEW, "application/pdf", NEW_DIGEST) is True

    assert store.objects[key] == NEW and store.deletes == []
    assert store.asked_digest[key] == NEW_DIGEST, "the provider is asked to check the bytes too"


def test_an_object_that_does_not_read_back_as_the_bytes_is_removed_and_refused() -> None:
    store = MemStore()
    store.corrupt_reads = OLD
    key = f"tenants/{TENANT}/documents/{FILE}/final/{uuid.uuid4()}/a.pdf"

    assert storage_restore._write_verified(store, key, NEW, "application/pdf", NEW_DIGEST) is False

    assert store.deletes == [key] and key not in store.objects, "no row may be pointed at it"


def test_a_truncated_read_back_is_refused_even_when_the_prefix_matches() -> None:
    store = MemStore()
    store.corrupt_reads = NEW[:-1]
    key = f"tenants/{TENANT}/documents/{FILE}/final/{uuid.uuid4()}/a.pdf"

    assert not storage_restore._write_verified(store, key, NEW, "application/pdf", NEW_DIGEST)


def test_a_missing_object_after_the_write_is_refused() -> None:
    class Forgetful(MemStore):
        def get(self, key: str) -> bytes | None:
            return None

    store = Forgetful()
    key = f"tenants/{TENANT}/documents/{FILE}/final/{uuid.uuid4()}/a.pdf"

    assert not storage_restore._write_verified(store, key, NEW, "application/pdf", NEW_DIGEST)
    assert store.deletes == [key]


def test_a_write_that_raises_removes_what_it_may_have_left_and_lets_the_error_go_on() -> None:
    store = MemStore()
    store.fail_put = True
    key = f"tenants/{TENANT}/documents/{FILE}/final/{uuid.uuid4()}/a.pdf"

    with pytest.raises(RuntimeError, match="refused the write"):
        storage_restore._write_verified(store, key, NEW, "application/pdf", NEW_DIGEST)

    assert store.deletes == [key]


# -- what the replacement may write ------------------------------------------------


def test_the_overwrite_branch_never_writes_the_original_key() -> None:
    """The invariant in text: the one `put` in the restore is the verified write, and what it is
    handed is a freshly made key, never the row's current one."""
    source = inspect.getsource(storage_restore)
    assert "put(original.storage_key" not in source
    assert "put(locked.storage_key" not in source
    assert source.count(".put(") == 1
    assert "target.put(key, content, content_type, checksum_sha256=digest)" in source
    body = inspect.getsource(storage_restore._replace)
    assert ".put(" not in body and ".delete(" not in body
    assert "_write_verified(target, new_key," in body
    # The only objects it may ever remove are the one it just wrote.
    discards = re.findall(r"_discard\(target, ([^)]*)\)", body)
    assert discards and set(discards) == {"new_key"}


def test_the_replacement_statement_resets_every_piece_of_scan_and_index_evidence() -> None:
    sql = str(storage_restore._REPLACE_FILE)
    for needed in (
        "storage_key = :new_key",
        "scan_status = 'pending'",
        "scan_note = null",
        "scan_attempts = 0",
        "scan_attempted_at = null",
        "scan_failure = null",
        "scan_object_etag = null",
        "indexed_at = null",
        "index_note = null",
    ):
        assert needed in sql, needed
    # Guarded by the facts the decision was made on, and tenant-scoped.
    for guard in (
        "tenant_id = cast(:tenant_id as uuid)",
        "storage_key = :old_key",
        "status = :seen_status",
        "scan_status = :seen_scan",
    ):
        assert guard in sql, guard


def test_the_replacement_binds_its_digest_to_bytes_this_worker_hashed_and_read_back() -> None:
    """`checksum_verified_at` is what makes the scanner compare the digest of the bytes it
    streams with the row's. It is set here, and only because `_write_verified` read the object
    back; it is not the old object's timestamp carried over."""
    for statement in (storage_restore._REPLACE_FILE, storage_restore._INSERT_FILE):
        sql = str(statement)
        assert "checksum_verified_at" in sql and "now()" in sql
        assert "checksum_verified_at = null" not in sql


def test_the_replacement_does_not_copy_a_verdict_from_anywhere() -> None:
    sql = str(storage_restore._REPLACE_FILE)
    assert "scan_status = 'clean'" not in sql and "scan_status = scan_status" not in sql
    assert "scan_status = :" not in sql.split("where")[0]
    assert "scan_object_etag = :" not in sql and "scan_object_etag = scan_object_etag" not in sql


def test_a_new_object_restore_names_no_scan_column() -> None:
    """It takes the table's defaults, which are `pending` and no evidence."""
    sql = str(storage_restore._INSERT_FILE)
    assert "scan_" not in sql and "indexed_at" not in sql


def test_the_backup_is_joined_on_the_requests_own_tenant_and_file() -> None:
    """The sweep reads on the provisioning context, which sees every tenant."""
    sql = str(storage_restore._APPROVED)
    assert "b.tenant_id = r.tenant_id" in sql and "b.file_id = r.file_id" in sql


def test_the_restore_reaches_the_window_only_by_name() -> None:
    """The worker image carries `koras_api/core/upload_window.py` and a restore must not need
    anything else of the API to name a key."""
    source = inspect.getsource(storage_restore)
    assert 'import_module("koras_api.core.upload_window")' in source
    assert "from koras_api" not in source and "import koras_api" not in source
