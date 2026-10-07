# ruff: noqa: S101
"""The stream digest, the integrity gate, the structural gate and their composition.

What is asserted is an *assessment*: whether the four gates compose to
`CLEAN_ELIGIBLE`, and why not when they do not. Nothing here writes a row, calls
`commit_clean` or marks a file anything; a test that did would be the accident
the last section guards against. Time is frozen, storage is a scripted source,
and the bytes are real archives, some written by the standard library's own
writer and some packed by hand so that a hostile one can be stated exactly.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import os
import re
import zlib
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

pytest.importorskip("koras_worker")
from koras_worker import scanning  # noqa: E402
from koras_worker.scanning import (  # noqa: E402
    ContainerProbe,
    IncompleteKind,
    IntegrityBasis,
    IntegrityOutcome,
    ObjectGate,
    ObjectIdentity,
    ObjectReader,
    ReleaseOutcome,
    RowIntegrity,
    ScanFailure,
    ScanOutcome,
    ScanResult,
    StructuralOutcome,
    StructuralReason,
    assess_integrity,
    assess_release,
    inspect_container,
)
from koras_worker.scanning import structure as structure_module  # noqa: E402
from koras_worker.scanning.structure import (  # noqa: E402
    LOCAL_CAPTURE_BYTES,
    MAX_COMPRESSION_RATIO,
    MAX_ENTRIES,
    MAX_ENTRY_BYTES,
    MAX_EXPANDED_BYTES,
    MAX_LOCAL_CANDIDATES,
    MAX_NAME_BYTES,
    MAX_RECURSION,
    NESTED_ARCHIVE_DEPTH_INSPECTED,
    TAIL_BYTES,
    ProbeSealed,
)
from object_support import (  # noqa: E402
    FILE,
    ISSUED,
    KEY,
    TENANT,
    FakeObjectSource,
    FirstChunkScanner,
    identity,
)
from scanner_support import FakeScanner  # noqa: E402
from zip_support import (  # noqa: E402
    DOCX_TYPE,
    MIB,
    XLSX_TYPE,
    Member,
    build_zip,
    real_docx,
    real_xlsx,
    real_zip,
    streamed_zip,
    streamed_zip64_deflated,
)

SCANNING_DIR = Path(scanning.__file__).parent
REPO = SCANNING_DIR.parents[3]
ZIP = "application/zip"
CHUNK = 64
NO_ROW = RowIntegrity()


def ref() -> scanning.ObjectReference:
    return scanning.ObjectReference(TENANT, FILE, KEY)


def probe_of(body: bytes, *, chunk: int = CHUNK, tail_bytes: int | None = None) -> ContainerProbe:
    probe = ContainerProbe() if tail_bytes is None else ContainerProbe(tail_bytes=tail_bytes)
    for start in range(0, len(body), chunk):
        probe.feed(body[start : start + chunk])
    return probe


def inspect(body: bytes, content_type: str | None, **kwargs: Any) -> scanning.StructuralResult:  # noqa: ANN401
    return inspect_container(probe_of(body, **kwargs), content_type)


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


async def stream_and_check(
    body: bytes,
    *,
    scanner: Any = None,  # noqa: ANN401
    ident: ObjectIdentity | None = None,
    stats: list[Any] | None = None,
    chunk_bytes: int = CHUNK,
) -> tuple[FakeObjectSource, scanning.ObjectCheck, ScanResult | None]:
    """Admit, stream into a scanner, verify: what a worker will run."""
    base = ident or identity(len(body))
    source = FakeObjectSource(stats=stats or [base], body=body)
    reader = ObjectReader(
        source,
        max_bytes=max(len(body), 1) + 1_000,
        chunk_bytes=chunk_bytes,
        clock=lambda: ISSUED + timedelta(minutes=16),
    )
    admission = await reader.admit(ref(), ISSUED)
    assert admission.ready, admission.gate
    stream = reader.stream(ref(), admission)
    result = await (scanner or FakeScanner.candidate_clean()).scan(stream)
    return source, await reader.verify(ref(), admission, stream), result


async def assess(
    body: bytes,
    content_type: str | None = ZIP,
    *,
    scanner: Any = None,  # noqa: ANN401
    row: RowIntegrity = NO_ROW,
    ident: ObjectIdentity | None = None,
    stats: list[Any] | None = None,
) -> scanning.ReleaseAssessment:
    _, check, result = await stream_and_check(body, scanner=scanner, ident=ident, stats=stats)
    assert result is not None
    return assess_release(
        object_check=check, scan_result=result, content_type=content_type, row=row
    )


# =========================================================================================
# 1. SHA-256 during the one bounded stream
# =========================================================================================


async def test_the_stream_digest_is_the_sha256_of_the_bytes_and_comes_from_one_read() -> None:
    body = bytes(range(256)) * 20  # 5120 bytes, many chunks
    source, check, _ = await stream_and_check(body, chunk_bytes=CHUNK)
    assert check.passed
    assert check.content_sha256 == sha(body)
    # One read: stat, one open, stat. No second download for hashing.
    assert source.verbs == ["stat", "open", "stat"]
    assert len(source.opened) == 1
    # The 64 KiB bound is preserved (here the test chunk): no request exceeds it.
    requested = source.opened[0].requested
    assert max(requested) <= CHUNK
    assert sum(len(body[i : i + CHUNK]) for i in range(0, len(body), CHUNK)) == len(body)


def test_the_default_chunk_is_still_64_kib_and_the_ceiling_still_100_mib() -> None:
    from koras_worker.scanning import objects

    assert objects.DEFAULT_CHUNK_BYTES == 64 * 1024
    assert scanning.MAX_SCAN_BYTES == 100 * MIB


async def test_the_digest_is_not_available_unless_the_stream_completed() -> None:
    body = b"x" * 5000
    source = FakeObjectSource(stats=[identity(len(body))], body=body)
    reader = ObjectReader(
        source,
        max_bytes=10_000,
        chunk_bytes=64,
        clock=lambda: ISSUED + timedelta(minutes=16),
    )
    admission = await reader.admit(ref(), ISSUED)
    stream = reader.stream(ref(), admission)
    await FirstChunkScanner().scan(stream)  # stopped after one chunk
    assert stream.content_sha256 is None
    check = await reader.verify(ref(), admission, stream)
    assert not check.passed
    assert check.content_sha256 is None
    assert check.probe is None


async def test_the_etag_never_becomes_the_digest() -> None:
    body = b"payload " * 100
    # An ETag that happens to be the body's SHA-256: still only identity.
    ident = identity(len(body), etag=sha(body))
    _, check, _ = await stream_and_check(body, ident=ident)
    assert check.content_sha256 == sha(body)
    assert check.identity is not None
    assert check.identity.provider_sha256 is None
    result = assess_integrity(check, NO_ROW)
    assert result.outcome is IntegrityOutcome.NOT_APPLICABLE
    assert result.basis is IntegrityBasis.NONE
    # And an ETag that differs from the digest is no mismatch.
    other = identity(len(body), etag="d41d8cd98f00b204e9800998ecf8427e")
    _, check2, _ = await stream_and_check(body, ident=other)
    assert assess_integrity(check2, NO_ROW).outcome is IntegrityOutcome.NOT_APPLICABLE


async def test_an_object_over_the_ceiling_is_cut_off_and_has_no_digest() -> None:
    body = b"y" * 3000
    source = FakeObjectSource(stats=[identity(len(body))], body=body)
    reader = ObjectReader(
        source, max_bytes=2000, chunk_bytes=64, clock=lambda: ISSUED + timedelta(minutes=16)
    )
    admission = await reader.admit(ref(), ISSUED)
    assert admission.gate is ObjectGate.OVERSIZED
    assert source.verbs == ["stat"]


# =========================================================================================
# 2. The integrity gate
# =========================================================================================


def check_with(digest: str | None, provider: str | None = None) -> scanning.ObjectCheck:
    return scanning.ObjectCheck(
        ObjectGate.READY,
        bytes_read=10,
        identity=identity(10, provider_sha256=provider),
        content_sha256=digest,
    )


GOOD = sha(b"the bytes")
OTHER = sha(b"other bytes")


@pytest.mark.parametrize(
    ("digest", "provider", "row", "outcome", "basis"),
    [
        # authoritative, matching
        (GOOD, GOOD, NO_ROW, IntegrityOutcome.VERIFIED, IntegrityBasis.PROVIDER),
        (
            GOOD,
            None,
            RowIntegrity(GOOD, True),
            IntegrityOutcome.VERIFIED,
            IntegrityBasis.ROW_CORROBORATED,
        ),
        (GOOD, GOOD, RowIntegrity(GOOD, True), IntegrityOutcome.VERIFIED, IntegrityBasis.PROVIDER),
        # authoritative, mismatching
        (GOOD, OTHER, NO_ROW, IntegrityOutcome.MISMATCH, IntegrityBasis.PROVIDER),
        (
            GOOD,
            None,
            RowIntegrity(OTHER, True),
            IntegrityOutcome.MISMATCH,
            IntegrityBasis.ROW_CORROBORATED,
        ),
        (
            GOOD,
            GOOD,
            RowIntegrity(OTHER, True),
            IntegrityOutcome.MISMATCH,
            IntegrityBasis.ROW_CORROBORATED,
        ),
        # a claim the bytes contradict
        (
            GOOD,
            None,
            RowIntegrity(OTHER, False),
            IntegrityOutcome.MISMATCH,
            IntegrityBasis.CLAIM_ONLY,
        ),
        # required evidence missing
        (
            GOOD,
            None,
            RowIntegrity(None, True),
            IntegrityOutcome.EVIDENCE_MISSING,
            IntegrityBasis.ROW_CORROBORATED,
        ),
        (None, GOOD, NO_ROW, IntegrityOutcome.EVIDENCE_MISSING, IntegrityBasis.NONE),
        (
            None,
            None,
            RowIntegrity(GOOD, True),
            IntegrityOutcome.EVIDENCE_MISSING,
            IntegrityBasis.NONE,
        ),
        (GOOD, "not-a-digest", NO_ROW, IntegrityOutcome.EVIDENCE_MISSING, IntegrityBasis.PROVIDER),
        # nothing was owed: explicit, and not a pass of a missing check
        (GOOD, None, NO_ROW, IntegrityOutcome.NOT_APPLICABLE, IntegrityBasis.NONE),
        (None, None, NO_ROW, IntegrityOutcome.NOT_APPLICABLE, IntegrityBasis.NONE),
        # a claim that agrees vouches for nothing
        (
            GOOD,
            None,
            RowIntegrity(GOOD, False),
            IntegrityOutcome.NOT_APPLICABLE,
            IntegrityBasis.CLAIM_ONLY,
        ),
    ],
)
def test_integrity_outcomes(
    digest: str | None,
    provider: str | None,
    row: RowIntegrity,
    outcome: IntegrityOutcome,
    basis: IntegrityBasis,
) -> None:
    result = assess_integrity(check_with(digest, provider), row)
    assert (result.outcome, result.basis) == (outcome, basis)
    assert result.passed == (
        outcome in {IntegrityOutcome.VERIFIED, IntegrityOutcome.NOT_APPLICABLE}
    )


def test_a_mismatch_and_missing_evidence_both_map_to_the_existing_integrity_failure() -> None:
    mismatch = assess_integrity(check_with(GOOD, OTHER), NO_ROW)
    missing = assess_integrity(check_with(GOOD), RowIntegrity(None, True))
    assert mismatch.failure is ScanFailure.INTEGRITY_MISMATCH
    assert missing.failure is ScanFailure.INTEGRITY_MISMATCH
    assert assess_integrity(check_with(GOOD, GOOD), NO_ROW).failure is None


def test_row_integrity_reads_the_two_columns_the_files_table_has() -> None:
    assert RowIntegrity.from_row({}) == RowIntegrity(None, False)
    assert RowIntegrity.from_row(
        {"checksum_sha256": GOOD.upper(), "checksum_verified_at": object()}
    ) == RowIntegrity(GOOD, True)
    assert RowIntegrity.from_row(
        {"checksum_sha256": GOOD, "checksum_verified_at": None}
    ) == RowIntegrity(GOOD, False)


# =========================================================================================
# 3. The structural gate: supported containers pass
# =========================================================================================


@pytest.mark.parametrize("chunk", [1, 7, 64, 4096, 1 << 20])
def test_a_valid_docx_passes_at_every_chunking(chunk: int) -> None:
    result = inspect(real_docx(), DOCX_TYPE, chunk=chunk)
    assert result.outcome is StructuralOutcome.PASS
    assert result.kind is scanning.ContainerKind.DOCX
    assert result.entries == 3


@pytest.mark.parametrize("chunk", [1, 61, 4096])
def test_a_valid_xlsx_passes_at_every_chunking(chunk: int) -> None:
    result = inspect(real_xlsx(), XLSX_TYPE, chunk=chunk)
    assert result.outcome is StructuralOutcome.PASS
    assert result.kind is scanning.ContainerKind.XLSX


def test_a_plain_zip_passes_and_an_unspecified_type_is_checked_as_a_zip() -> None:
    body = real_zip({"a.txt": b"alpha" * 100, "dir/b.txt": b"beta"})
    assert inspect(body, ZIP).outcome is StructuralOutcome.PASS
    assert inspect(body, "application/x-zip-compressed").outcome is StructuralOutcome.PASS
    assert inspect(body, "application/octet-stream").kind is scanning.ContainerKind.ZIP
    assert inspect(body, None).outcome is StructuralOutcome.PASS
    assert inspect(body, "APPLICATION/ZIP; charset=binary").outcome is StructuralOutcome.PASS


def test_a_stored_entry_and_an_empty_archive_pass_and_five_thousand_entries_are_allowed() -> None:
    assert inspect(real_zip({"s.txt": b"stored" * 10}, compression=0), ZIP).passed
    assert inspect(build_zip([]), ZIP).outcome is StructuralOutcome.PASS
    many = [Member.stored(b"f%d" % i, b"x") for i in range(MAX_ENTRIES)]
    assert inspect(build_zip(many), ZIP, chunk=65536).outcome is StructuralOutcome.PASS


def test_a_workbook_written_by_openpyxl_passes() -> None:
    openpyxl = pytest.importorskip("openpyxl")
    import io

    workbook = openpyxl.Workbook()
    for index in range(150):
        workbook.active.append([index, "cell " * 10, index * 1.5])
    buffer = io.BytesIO()
    workbook.save(buffer)
    assert inspect(buffer.getvalue(), XLSX_TYPE, chunk=65536).outcome is StructuralOutcome.PASS


# =========================================================================================
# 4. Non-ZIP formats: explicit NOT_REQUIRED, and mismatches fail closed
# =========================================================================================


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (b"a,b\n1,2\n" * 50, "text/csv"),
        (b"a\tb\n1\t2\n", "text/tab-separated-values"),
        (b"%PDF-1.7\n" + b"0" * 500 + b"\n%%EOF\n", "application/pdf"),
        (b"\x89PNG\r\n\x1a\n" + b"\0" * 100, "image/png"),
        (b"", "text/plain"),
        (b"plain bytes", "application/octet-stream"),
    ],
)
def test_a_non_container_under_a_non_container_type_is_explicitly_not_required(
    body: bytes, content_type: str
) -> None:
    result = inspect(body, content_type)
    assert result.outcome is StructuralOutcome.NOT_REQUIRED
    assert result.passed
    assert result.kind is None and result.reason is None
    assert result.outcome is not StructuralOutcome.PASS


@pytest.mark.parametrize(
    ("body", "content_type", "outcome", "reason"),
    [
        # a ZIP under a type that is not a ZIP type
        (
            real_docx(),
            "text/csv",
            StructuralOutcome.TYPE_MISMATCH,
            StructuralReason.CONTAINER_UNDER_OTHER_TYPE,
        ),
        (
            real_xlsx(),
            "application/pdf",
            StructuralOutcome.TYPE_MISMATCH,
            StructuralReason.CONTAINER_UNDER_OTHER_TYPE,
        ),
        # a ZIP type over bytes that are not a ZIP
        (
            b"just text",
            DOCX_TYPE,
            StructuralOutcome.TYPE_MISMATCH,
            StructuralReason.NOT_A_CONTAINER,
        ),
        (b"", XLSX_TYPE, StructuralOutcome.TYPE_MISMATCH, StructuralReason.NOT_A_CONTAINER),
        (b"%PDF-1.4 ...", ZIP, StructuralOutcome.TYPE_MISMATCH, StructuralReason.NOT_A_CONTAINER),
        # a container that is not the format it is declared as
        (
            real_zip({"a.txt": b"x"}),
            DOCX_TYPE,
            StructuralOutcome.TYPE_MISMATCH,
            StructuralReason.MISSING_REQUIRED_PART,
        ),
        (
            real_xlsx(),
            DOCX_TYPE,
            StructuralOutcome.TYPE_MISMATCH,
            StructuralReason.MISSING_REQUIRED_PART,
        ),
        (
            real_docx(),
            XLSX_TYPE,
            StructuralOutcome.TYPE_MISMATCH,
            StructuralReason.MISSING_REQUIRED_PART,
        ),
    ],
)
def test_a_type_and_container_that_disagree_fail_closed(
    body: bytes, content_type: str, outcome: StructuralOutcome, reason: StructuralReason
) -> None:
    result = inspect(body, content_type)
    assert (result.outcome, result.reason) == (outcome, reason)
    assert not result.passed


def test_a_zip_hidden_behind_leading_bytes_is_not_a_clean_csv() -> None:
    prefixed = b"id,name\n1,a\n" + real_zip({"a.txt": b"hello" * 50})
    result = inspect(prefixed, "text/csv")
    assert result.outcome is StructuralOutcome.TYPE_MISMATCH
    # And declared as a ZIP, data before the first entry is not tolerated.
    declared = inspect(prefixed, ZIP)
    assert not declared.passed
    assert declared.reason in {
        StructuralReason.DATA_BEFORE_FIRST_ENTRY,
        StructuralReason.CENTRAL_DIRECTORY_MISPLACED,
        StructuralReason.LOCAL_HEADER_MISSING,
    }


def test_the_filename_is_not_an_input() -> None:
    import inspect as stdlib_inspect

    params = stdlib_inspect.signature(inspect_container).parameters
    assert list(params) == ["probe", "content_type"]


# =========================================================================================
# 5. Malformed, truncated and ambiguous containers
# =========================================================================================


def test_a_truncated_archive_is_malformed() -> None:
    body = real_docx()
    for cut in (1, 10, 22, 60, len(body) // 2):
        result = inspect(body[:-cut], DOCX_TYPE)
        assert not result.passed, cut
        assert result.outcome in {StructuralOutcome.MALFORMED, StructuralOutcome.TYPE_MISMATCH}


def test_a_signature_with_no_central_directory_is_malformed() -> None:
    result = inspect(b"PK\x03\x04" + b"\x00" * 200, ZIP)
    assert (result.outcome, result.reason) == (
        StructuralOutcome.TYPE_MISMATCH,
        StructuralReason.NOT_A_CONTAINER,
    ) or result.outcome is StructuralOutcome.MALFORMED
    assert not result.passed


def test_a_directory_that_declares_more_entries_than_it_holds_is_malformed() -> None:
    body = build_zip([Member.stored(b"a", b"1")], entries_override=2)
    result = inspect(body, ZIP)
    assert result.outcome is StructuralOutcome.MALFORMED


def test_a_directory_that_holds_more_entries_than_declared_is_malformed() -> None:
    body = build_zip([Member.stored(b"a", b"1"), Member.stored(b"b", b"2")], entries_override=1)
    result = inspect(body, ZIP)
    assert (result.outcome, result.reason) == (
        StructuralOutcome.MALFORMED,
        StructuralReason.ENTRY_COUNT_MISMATCH,
    )


def test_two_end_records_that_both_fit_are_ambiguous_and_held() -> None:
    # An EOCD planted in the comment of a real one, with a comment that also ends the file.
    fake_eocd = b"PK\x05\x06" + b"\x00" * 16 + (0).to_bytes(2, "little")
    real = build_zip([Member.stored(b"a", b"1")], comment=fake_eocd)
    result = inspect(real, ZIP)
    assert (result.outcome, result.reason) == (
        StructuralOutcome.MALFORMED,
        StructuralReason.AMBIGUOUS_END_RECORD,
    )


def test_a_multi_disk_archive_is_malformed() -> None:
    result = inspect(build_zip([Member.stored(b"a", b"1")], disk=1), ZIP)
    assert (result.outcome, result.reason) == (
        StructuralOutcome.MALFORMED,
        StructuralReason.MULTI_DISK,
    )


def test_a_local_header_that_disagrees_with_the_directory_is_malformed() -> None:
    cases: list[tuple[Member, StructuralReason]] = [
        (
            Member.stored(b"a.txt", b"1", local_name=b"b.txt"),
            StructuralReason.LOCAL_HEADER_MISMATCH,
        ),
        (
            Member.deflated(b"a.txt", b"1" * 50, local_method=0),
            StructuralReason.LOCAL_HEADER_MISMATCH,
        ),
        (Member.stored(b"a.txt", b"1", local_flags=0x0001), StructuralReason.LOCAL_HEADER_MISMATCH),
        (Member.stored(b"a.txt", b"1", cd_offset=3), StructuralReason.LOCAL_HEADER_MISSING),
    ]
    for member, reason in cases:
        result = inspect(build_zip([member]), ZIP)
        assert (result.outcome, result.reason) == (StructuralOutcome.MALFORMED, reason), reason


def test_a_stored_entry_whose_sizes_differ_is_malformed() -> None:
    body = build_zip([Member(b"a", b"abcd", method=0, usize=9)])
    assert inspect(body, ZIP).reason is StructuralReason.STORED_SIZE_MISMATCH


def test_an_unsupported_compression_method_is_an_incomplete_inspection() -> None:
    body = build_zip([Member(b"a", b"zzzz", method=12, usize=4)])
    result = inspect(body, ZIP)
    assert (result.outcome, result.reason) == (
        StructuralOutcome.INCOMPLETE_INSPECTION,
        StructuralReason.UNSUPPORTED_METHOD,
    )


def test_a_malformed_extra_field_is_malformed() -> None:
    body = build_zip([Member.stored(b"a", b"1", cd_extra=b"\x99\x99\xff\xff")])
    assert inspect(body, ZIP).reason is StructuralReason.EXTRA_FIELD_INVALID
    twice = build_zip([Member.stored(b"a", b"1", local_extra=b"\x07\x07\x00\x00" * 2)])
    assert inspect(twice, ZIP).reason is StructuralReason.EXTRA_FIELD_INVALID


# =========================================================================================
# 6. Encrypted containers
# =========================================================================================


@pytest.mark.parametrize(
    "member",
    [
        Member.stored(b"secret.txt", b"cipher", flags=0x0001),
        Member.stored(b"secret.txt", b"cipher", flags=0x0001 | 0x0040),
        Member(b"aes.bin", b"cipher", method=99, usize=6),
        # Encryption with a data descriptor and ZIP64 is still encrypted, not "zip64".
        Member.deflated(b"s.bin", b"z" * 50, flags=0x0001, streamed=True, local_zip64=True),
    ],
)
def test_an_encrypted_entry_is_held_as_encrypted(member: Member) -> None:
    result = inspect(build_zip([Member.stored(b"ok.txt", b"fine"), member]), ZIP)
    assert (result.outcome, result.reason) == (
        StructuralOutcome.ENCRYPTED,
        StructuralReason.ENCRYPTED_ENTRY,
    )
    assert result.failure is ScanFailure.INSPECTION_INCOMPLETE


def test_an_encrypted_docx_is_held() -> None:
    parts = [
        Member.stored(b"[Content_Types].xml", b"<Types/>", flags=0x0001),
        Member.stored(b"word/document.xml", b"<d/>", flags=0x0001),
    ]
    assert inspect(build_zip(parts), DOCX_TYPE).outcome is StructuralOutcome.ENCRYPTED


# =========================================================================================
# 7. Limits
# =========================================================================================


def test_the_ratified_bounds_are_the_ones_in_use_and_none_was_raised() -> None:
    assert MAX_ENTRIES == 5000
    assert MAX_EXPANDED_BYTES == 500 * MIB
    assert MAX_ENTRY_BYTES == 500 * MIB
    assert MAX_RECURSION == 8
    assert scanning.MAX_SCAN_BYTES == 100 * MIB
    assert TAIL_BYTES == 4 * MIB
    assert MAX_NAME_BYTES == 1024
    assert MAX_COMPRESSION_RATIO == 100
    assert NESTED_ARCHIVE_DEPTH_INSPECTED == 0
    assert MAX_LOCAL_CANDIDATES == 2 * MAX_ENTRIES
    assert LOCAL_CAPTURE_BYTES == 30 + 1024 + 1024
    # A probe can narrow its tail window and can never widen it.
    with pytest.raises(ValueError):
        ContainerProbe(tail_bytes=TAIL_BYTES + 1)
    with pytest.raises(ValueError):
        ContainerProbe(tail_bytes=100)


def test_more_than_five_thousand_entries_is_over_the_limit() -> None:
    many = [Member.stored(b"f%d" % i, b"x") for i in range(MAX_ENTRIES + 1)]
    result = inspect(build_zip(many), ZIP, chunk=65536)
    assert (result.outcome, result.reason) == (
        StructuralOutcome.LIMIT_EXCEEDED,
        StructuralReason.ENTRY_COUNT,
    )
    assert result.failure is ScanFailure.SCAN_LIMIT_EXCEEDED


def test_the_entry_count_is_judged_before_any_entry_is_read() -> None:
    # The end record claims 60000 entries over an empty directory: refused on the claim.
    body = build_zip([Member.stored(b"a", b"1")], entries_override=60000)
    assert inspect(body, ZIP).reason is StructuralReason.ENTRY_COUNT


def test_cumulative_declared_size_over_500_mib_is_over_the_limit() -> None:
    # 300 MiB declared each, with the 3 MiB of data that keeps each at exactly 100:1.
    packed = b"\0" * (3 * MIB)
    body = build_zip(
        [
            Member(b"a.bin", packed, method=8, usize=300 * MIB),
            Member(b"b.bin", packed, method=8, usize=300 * MIB),
        ]
    )
    result = inspect(body, ZIP, chunk=65536)
    assert (result.outcome, result.reason) == (
        StructuralOutcome.LIMIT_EXCEEDED,
        StructuralReason.EXPANDED_TOTAL,
    )


def test_one_entry_over_the_per_entry_bound_is_over_the_limit() -> None:
    body = build_zip([Member(b"big.bin", b"\0" * (6 * MIB), method=8, usize=600 * MIB)])
    result = inspect(body, ZIP, chunk=65536)
    assert (result.outcome, result.reason) == (
        StructuralOutcome.LIMIT_EXCEEDED,
        StructuralReason.ENTRY_SIZE,
    )


def test_a_real_decompression_bomb_is_over_the_ratio() -> None:
    bomb = Member.deflated(b"zeros.bin", b"\0" * (40 * MIB))
    assert len(bomb.data) < 100 * 1024  # roughly 40,000:1
    result = inspect(build_zip([bomb]), ZIP, chunk=65536)
    assert (result.outcome, result.reason) == (
        StructuralOutcome.LIMIT_EXCEEDED,
        StructuralReason.COMPRESSION_RATIO,
    )
    assert result.failure is ScanFailure.SCAN_LIMIT_EXCEEDED


def test_a_highly_compressible_but_ordinary_entry_is_not_called_a_bomb() -> None:
    # Under the 1 MiB floor a high ratio is harmless, and 100:1 itself is allowed.
    small = Member.deflated(b"rows.csv", b"0,0,0\n" * 50_000)  # about 300 KiB
    assert inspect(build_zip([small]), ZIP, chunk=65536).passed
    packed = b"\0" * (2 * MIB)
    at_limit = Member(b"x.bin", packed, method=8, usize=200 * MIB)
    assert inspect(build_zip([at_limit]), ZIP, chunk=65536).passed


def test_a_name_over_the_bound_is_over_the_limit() -> None:
    body = build_zip([Member.stored(b"n" * (MAX_NAME_BYTES + 1), b"x")])
    assert inspect(body, ZIP).reason is StructuralReason.NAME_LENGTH


def test_a_directory_longer_than_the_window_is_over_the_limit_and_not_read() -> None:
    members = [Member.stored(b"d" * 1000 + b"%03d" % i, b"") for i in range(100)]
    body = build_zip(members)
    result = inspect(body, ZIP, chunk=4096, tail_bytes=65557)
    assert (result.outcome, result.reason) == (
        StructuralOutcome.LIMIT_EXCEEDED,
        StructuralReason.DIRECTORY_SIZE,
    )
    # With the ratified window the same archive is fine.
    assert inspect(body, ZIP, chunk=4096).outcome is StructuralOutcome.PASS


def test_too_many_local_header_signatures_is_over_the_limit() -> None:
    noise = Member.stored(b"noise.bin", b"PK\x03\x04" * (MAX_LOCAL_CANDIDATES + 10))
    result = inspect(build_zip([noise]), ZIP, chunk=65536)
    assert (result.outcome, result.reason) == (
        StructuralOutcome.LIMIT_EXCEEDED,
        StructuralReason.LOCAL_CANDIDATES,
    )


def test_a_local_header_with_an_oversized_name_or_extra_is_over_the_limit() -> None:
    body = build_zip(
        [Member.stored(b"a.txt", b"1", local_extra=b"\x07\x07\xff\x07" + b"\0" * 2047)]
    )
    assert inspect(body, ZIP).reason is StructuralReason.LOCAL_HEADER_SIZE


# =========================================================================================
# 8. The streamed/deflated ZIP64 form ClamAV may pass without inspecting
# =========================================================================================


def test_the_zip64_fixture_really_is_deflated_streamed_and_zip64() -> None:
    """A guard on the fixture: if the writer stopped producing the form, the test would lie."""
    body = streamed_zip64_deflated()
    flags = int.from_bytes(body[6:8], "little")
    method = int.from_bytes(body[8:10], "little")
    name_len = int.from_bytes(body[26:28], "little")
    extra_len = int.from_bytes(body[28:30], "little")
    extra = body[30 + name_len : 30 + name_len + extra_len]
    assert body[:4] == b"PK\x03\x04"
    assert flags & 0x08, "no data descriptor: not streamed"
    assert method == 8, "not deflated"
    assert int.from_bytes(extra[:2], "little") == 0x0001, "no zip64 extra in the local header"
    # The directory states no zip64 at all: only the local header gives the form away.
    cd = body.index(b"PK\x01\x02")
    assert int.from_bytes(body[cd + 30 : cd + 32], "little") == 0


@pytest.mark.parametrize("chunk", [1, 33, 64, 4096])
def test_regression_streamed_deflated_zip64_is_held_not_clean_not_infected_not_skipped(
    chunk: int,
) -> None:
    """PERMANENT. The documented ClamAV gap (`docs/CLAMD_SERVICE.md`): never clean-eligible."""
    result = inspect(streamed_zip64_deflated(), ZIP, chunk=chunk)
    assert result.outcome is StructuralOutcome.INCOMPLETE_INSPECTION
    assert result.reason is StructuralReason.ZIP64_STREAMED_DEFLATED
    assert not result.passed
    assert result.outcome is not StructuralOutcome.PASS
    assert result.failure is ScanFailure.INSPECTION_INCOMPLETE
    # Held: a hold, not a detection and not a skip. Neither word is a structural outcome.
    assert "infected" not in {o.value for o in StructuralOutcome}
    assert "skipped" not in {o.value for o in StructuralOutcome}
    assert "clean" not in {o.value for o in StructuralOutcome}


@pytest.mark.parametrize(
    "declared_type", [ZIP, "application/octet-stream", None, XLSX_TYPE, DOCX_TYPE]
)
def test_regression_the_zip64_form_is_held_under_every_declared_type(
    declared_type: str | None,
) -> None:
    result = inspect(streamed_zip64_deflated(), declared_type)
    assert not result.passed


def test_the_zip64_form_is_held_wherever_the_header_states_it() -> None:
    packed = Member.deflated(b"p.txt", b"payload " * 100)
    for member in (
        Member.deflated(b"p.txt", b"payload " * 100, streamed=True, local_zip64=True),
        Member.deflated(b"p.txt", b"payload " * 100, streamed=True, cd_zip64=True),
        Member.deflated(
            b"p.txt", b"payload " * 100, streamed=True, local_zip64=True, cd_zip64=True
        ),
    ):
        result = inspect(build_zip([member]), ZIP)
        assert result.reason is StructuralReason.ZIP64_STREAMED_DEFLATED, member
    assert packed.method == 8


def test_the_zip64_form_inside_a_docx_or_after_good_entries_is_still_held() -> None:
    good = Member.deflated(b"word/document.xml", b"<d/>" * 40)
    parts = [
        Member.deflated(b"[Content_Types].xml", b"<Types/>" * 20),
        good,
        Member.deflated(b"word/media/late.bin", b"x" * 400, streamed=True, local_zip64=True),
    ]
    result = inspect(build_zip(parts), DOCX_TYPE)
    assert result.reason is StructuralReason.ZIP64_STREAMED_DEFLATED


def test_the_controls_ordinary_streaming_and_ordinary_zip64_are_not_held() -> None:
    # Streamed but not ZIP64: a normal writer to a pipe.
    assert inspect(streamed_zip(force_zip64=False), ZIP).outcome is StructuralOutcome.PASS
    # ZIP64 but not streamed: sizes are in the local header.
    seekable = Member.deflated(b"p.txt", b"payload " * 100, local_zip64=True)
    assert inspect(build_zip([seekable]), ZIP).outcome is StructuralOutcome.PASS
    # Streamed + ZIP64 but stored, not deflated: not the form ClamAV skips.
    stored = Member.stored(b"p.txt", b"payload " * 100, streamed=True, local_zip64=True)
    assert inspect(build_zip([stored]), ZIP).outcome is StructuralOutcome.PASS


def test_a_zip64_end_record_is_read_and_a_bad_one_is_malformed() -> None:
    members = [Member.deflated(b"a.txt", b"alpha " * 50), Member.stored(b"b.txt", b"beta")]
    assert inspect(build_zip(members, zip64_end=True), ZIP).outcome is StructuralOutcome.PASS
    bad = inspect(build_zip(members, zip64_end=True, zip64_end_bad_offset=True), ZIP)
    assert (bad.outcome, bad.reason) == (
        StructuralOutcome.MALFORMED,
        StructuralReason.ZIP64_RECORD_INVALID,
    )


# =========================================================================================
# 9. Unsafe structure: overlap, names, nesting
# =========================================================================================


def test_overlapping_entries_are_unsafe() -> None:
    first = Member.stored(b"a.bin", b"A" * 100)
    second = Member.stored(b"b.bin", b"B" * 100)
    # `a` declares more bytes than it holds, reaching into `b`'s header.
    first.csize = first.usize = 160
    result = inspect(build_zip([first, second]), ZIP)
    assert (result.outcome, result.reason) == (
        StructuralOutcome.UNSAFE_STRUCTURE,
        StructuralReason.OVERLAPPING_ENTRIES,
    )
    assert result.failure is ScanFailure.INSPECTION_INCOMPLETE


def test_duplicate_names_are_unsafe() -> None:
    body = build_zip([Member.stored(b"a.txt", b"1"), Member.stored(b"a.txt", b"2")])
    assert inspect(body, ZIP).reason is StructuralReason.DUPLICATE_NAME


@pytest.mark.parametrize(
    "name",
    [
        b"../evil.txt",
        b"a/../../evil.txt",
        b"/etc/passwd",
        b"\\windows\\system32",
        b"C:\\boot.ini",
        b"c:/boot.ini",
        b"a\\b.txt",
        b"bad\x00name.txt",
        b"bad\nname.txt",
        b"",
    ],
)
def test_path_traversal_and_unsafe_names_are_held(name: bytes) -> None:
    result = inspect(build_zip([Member.stored(name, b"x")]), ZIP)
    assert result.outcome is StructuralOutcome.UNSAFE_STRUCTURE
    assert result.reason is StructuralReason.UNSAFE_NAME
    assert result.outcome is not StructuralOutcome.PASS


def docx_with(extra: dict[str, bytes]) -> bytes:
    parts = {
        "[Content_Types].xml": b"<Types/>",
        "_rels/.rels": b"<Relationships/>",
        "word/document.xml": b"<w:document>" + b"hello world " * 200 + b"</w:document>",
    }
    return real_zip({**parts, **extra})


def test_a_docx_with_a_legitimate_embedded_xlsx_passes_the_outer_gate() -> None:
    body = docx_with({"word/embeddings/Microsoft_Excel_Sheet1.xlsx": real_xlsx()})
    result = inspect(body, DOCX_TYPE)
    assert result.outcome is StructuralOutcome.PASS
    assert result.kind is scanning.ContainerKind.DOCX


@pytest.mark.parametrize(
    "name",
    [b"inner.zip", b"x/inner.DOCX", b"data.jar", b"a.xlsx", b"b.pptx", b"c.odt", b"d.epub"],
)
def test_a_nested_filename_alone_never_decides_unsafe(name: bytes) -> None:
    result = inspect(build_zip([Member.stored(name, b"PK\x05\x06" + b"\0" * 18)]), ZIP)
    assert result.outcome is StructuralOutcome.PASS
    assert not hasattr(StructuralReason, "NESTED_ARCHIVE")


def test_a_nested_name_does_not_excuse_a_malformed_outer_container() -> None:
    # Overlapping extents, duplicate names, unsafe names and a missing required part are
    # still held when the entry that carries them is named like an embedded document.
    nested = Member.stored(b"word/embeddings/a.xlsx", b"x" * 40)
    unsafe = inspect(build_zip([nested, Member.stored(b"../evil.xlsx", b"x")]), ZIP)
    assert unsafe.outcome is StructuralOutcome.UNSAFE_STRUCTURE
    assert unsafe.reason is StructuralReason.UNSAFE_NAME
    duplicate = inspect(build_zip([nested, nested]), ZIP)
    assert duplicate.outcome is StructuralOutcome.UNSAFE_STRUCTURE
    assert duplicate.reason is StructuralReason.DUPLICATE_NAME
    no_parts = inspect(real_zip({"word/embeddings/a.xlsx": real_xlsx()}), DOCX_TYPE)
    assert no_parts.outcome is StructuralOutcome.TYPE_MISMATCH
    assert no_parts.reason is StructuralReason.MISSING_REQUIRED_PART


def test_a_top_level_streamed_deflated_zip64_is_still_held_beside_an_embedded_xlsx() -> None:
    body = build_zip(
        [
            Member.stored(b"[Content_Types].xml", b"<Types/>"),
            Member.stored(b"word/document.xml", b"<w:document/>"),
            Member.stored(b"word/embeddings/a.xlsx", real_xlsx()),
            Member.deflated(b"word/media/late.bin", b"x" * 400, streamed=True, local_zip64=True),
        ]
    )
    result = inspect(body, DOCX_TYPE)
    assert (result.outcome, result.reason) == (
        StructuralOutcome.INCOMPLETE_INSPECTION,
        StructuralReason.ZIP64_STREAMED_DEFLATED,
    )


def test_an_ordinary_entry_with_zip_in_its_name_is_not_a_nested_archive() -> None:
    body = real_zip({"notes/zipcode.txt": b"12345", "archive.zipped.txt": b"x"})
    assert inspect(body, ZIP).outcome is StructuralOutcome.PASS


# =========================================================================================
# 10. The probe: bounded, sealed, chunking-independent
# =========================================================================================


def test_the_probe_is_bounded_by_its_windows_and_not_by_the_object() -> None:
    probe = ContainerProbe()
    chunk = b"\x07" * 65536
    peak = 0
    for _ in range(400):  # 25 MiB of non-ZIP bytes
        probe.feed(chunk)
        peak = max(peak, len(probe._tail) + len(probe._window))  # noqa: SLF001
    probe.finish()
    assert probe.total_bytes == 400 * 65536
    assert peak <= TAIL_BYTES + 65536 + LOCAL_CAPTURE_BYTES + 65536
    assert len(probe.tail) <= TAIL_BYTES
    assert probe.local_candidates == {}


def test_the_probe_cannot_be_fed_after_it_finishes_nor_read_before() -> None:
    probe = ContainerProbe()
    probe.feed(b"abc")
    with pytest.raises(ProbeSealed):
        _ = probe.tail
    probe.finish()
    probe.finish()  # idempotent
    with pytest.raises(ProbeSealed):
        probe.feed(b"more")


def test_the_verdict_does_not_depend_on_how_the_stream_was_chunked() -> None:
    bodies = [
        (real_docx(), DOCX_TYPE),
        (streamed_zip64_deflated(), ZIP),
        (build_zip([Member.stored(b"../x", b"1")]), ZIP),
        (b"id,name\n1,a\n", "text/csv"),
    ]
    for body, content_type in bodies:
        outcomes = {
            (r.outcome, r.reason)
            for r in (inspect(body, content_type, chunk=c) for c in (1, 5, 64, 4096, 1 << 20))
        }
        assert len(outcomes) == 1


def test_a_probe_over_a_partial_stream_cannot_pass_the_release_assessment() -> None:
    # No probe on the check: the structural gate does not run, and it is not "fine".
    check = scanning.ObjectCheck(
        ObjectGate.READY, bytes_read=1, identity=identity(1), content_sha256=GOOD, probe=None
    )
    assessment = assess_release(
        object_check=check,
        scan_result=ScanResult(ScanOutcome.CANDIDATE_CLEAN),
        content_type=ZIP,
        row=NO_ROW,
    )
    assert assessment.structural is not None
    assert assessment.structural.reason is StructuralReason.PROBE_UNAVAILABLE
    assert not assessment.eligible


def test_the_structural_result_cannot_carry_a_name_or_a_hold_without_a_reason() -> None:
    with pytest.raises(ValueError):
        scanning.StructuralResult(StructuralOutcome.MALFORMED)
    with pytest.raises(ValueError):
        scanning.StructuralResult(StructuralOutcome.PASS, reason=StructuralReason.UNSAFE_NAME)
    with pytest.raises(ValueError):
        scanning.StructuralResult(StructuralOutcome.PASS)  # a pass names its container
    names = {f.name for f in dataclasses.fields(scanning.StructuralResult)}
    assert not names & {"name", "names", "filename", "entry_names", "path"}


# =========================================================================================
# 11. Composition: the release assessment
# =========================================================================================


async def test_1_every_gate_passing_is_clean_eligible_and_only_internal() -> None:
    body = real_docx()
    assessment = await assess(body, DOCX_TYPE)
    assert assessment.outcome is ReleaseOutcome.CLEAN_ELIGIBLE
    assert assessment.eligible
    assert assessment.failure is None
    assert assessment.object_check.passed
    assert assessment.scan_result.candidate_clean
    assert assessment.integrity.outcome is IntegrityOutcome.NOT_APPLICABLE
    assert assessment.structural is not None
    assert assessment.structural.outcome is StructuralOutcome.PASS
    # The evidence a later slice would hand to `commit_clean`: built, not used.
    evidence = assessment.clean_evidence(tenant_id=TENANT, file_id=FILE, storage_key=KEY)
    assert evidence.content_sha256 == sha(body)
    assert evidence.structural_gate_passed is True


async def test_1b_a_verified_digest_is_carried_into_the_evidence() -> None:
    body = real_xlsx()
    ident = identity(len(body), provider_sha256=sha(body))
    assessment = await assess(body, XLSX_TYPE, ident=ident, row=RowIntegrity(sha(body), True))
    assert assessment.eligible
    assert assessment.integrity.outcome is IntegrityOutcome.VERIFIED
    assert assessment.integrity.basis is IntegrityBasis.PROVIDER


async def test_2_an_infected_scan_is_never_clean_eligible() -> None:
    assessment = await assess(real_docx(), DOCX_TYPE, scanner=FakeScanner.infected())
    assert assessment.outcome is ReleaseOutcome.INFECTED
    assert not assessment.eligible
    assert assessment.failure is None
    with pytest.raises(ValueError):
        assessment.clean_evidence(tenant_id=TENANT, file_id=FILE, storage_key=KEY)


@pytest.mark.parametrize(
    "result",
    [
        ScanResult(ScanOutcome.INCOMPLETE_INSPECTION, IncompleteKind.UNSUPPORTED),
        ScanResult(ScanOutcome.INCOMPLETE_INSPECTION, IncompleteKind.ENCRYPTED),
        ScanResult(ScanOutcome.INCOMPLETE_INSPECTION, IncompleteKind.INCOMPLETE),
        ScanResult(ScanOutcome.LIMIT_EXCEEDED),
        ScanResult(ScanOutcome.TIMEOUT),
        ScanResult(ScanOutcome.UNAVAILABLE),
        ScanResult(ScanOutcome.MALFORMED_RESPONSE),
        ScanResult(ScanOutcome.SCANNER_ERROR),
        ScanResult(ScanOutcome.READ_FAILURE),
        ScanResult(ScanOutcome.MISCONFIGURED),
    ],
)
async def test_3_a_scanner_that_did_not_say_candidate_clean_is_never_eligible(
    result: ScanResult,
) -> None:
    assessment = await assess(real_docx(), DOCX_TYPE, scanner=FakeScanner(result))
    assert assessment.outcome is ReleaseOutcome.HELD
    assert not assessment.eligible
    assert assessment.failure is result.failure


async def test_4_an_object_that_changed_is_never_clean_eligible() -> None:
    body = real_docx()
    changed = [identity(len(body)), identity(len(body), etag="replaced")]
    assessment = await assess(body, DOCX_TYPE, stats=changed)
    assert assessment.object_check.gate is ObjectGate.CHANGED
    assert assessment.structural is None  # nothing was inspected: not a verified read
    assert assessment.outcome is ReleaseOutcome.HELD
    assert assessment.failure is ScanFailure.OBJECT_CHANGED
    assert assessment.object_check.probe is None


async def test_5_a_checksum_mismatch_is_never_clean_eligible() -> None:
    body = real_docx()
    for ident, row in (
        (identity(len(body), provider_sha256=sha(b"other")), NO_ROW),
        (identity(len(body)), RowIntegrity(sha(b"other"), True)),
        (identity(len(body)), RowIntegrity(sha(b"other"), False)),
    ):
        assessment = await assess(body, DOCX_TYPE, ident=ident, row=row)
        assert assessment.structural is not None and assessment.structural.passed
        assert assessment.integrity.outcome is IntegrityOutcome.MISMATCH
        assert not assessment.eligible
        assert assessment.failure is ScanFailure.INTEGRITY_MISMATCH


async def test_6_a_required_checksum_that_is_missing_is_never_clean_eligible() -> None:
    body = real_docx()
    # The row says it was corroborated, and holds no digest to compare.
    assessment = await assess(body, DOCX_TYPE, row=RowIntegrity(None, True))
    assert assessment.integrity.outcome is IntegrityOutcome.EVIDENCE_MISSING
    assert not assessment.eligible
    assert assessment.failure is ScanFailure.INTEGRITY_MISMATCH


@pytest.mark.parametrize(
    ("body", "content_type", "failure"),
    [
        # 7 malformed
        (real_docx()[:-30], DOCX_TYPE, ScanFailure.INSPECTION_INCOMPLETE),
        (
            build_zip([Member.stored(b"a", b"1")], entries_override=3),
            ZIP,
            ScanFailure.INSPECTION_INCOMPLETE,
        ),
        # 8 encrypted
        (build_zip([Member.stored(b"s", b"c", flags=1)]), ZIP, ScanFailure.INSPECTION_INCOMPLETE),
        # 9 limit exceeded
        (
            build_zip([Member.deflated(b"z.bin", b"\0" * (30 * MIB))]),
            ZIP,
            ScanFailure.SCAN_LIMIT_EXCEEDED,
        ),
        # 10 the streamed/deflated ZIP64 form
        (streamed_zip64_deflated(), ZIP, ScanFailure.INSPECTION_INCOMPLETE),
        # 14 type/container mismatch, both ways
        (real_docx(), "text/csv", ScanFailure.INSPECTION_INCOMPLETE),
        (b"plain text", DOCX_TYPE, ScanFailure.INSPECTION_INCOMPLETE),
        # unsafe structure
        (build_zip([Member.stored(b"../x", b"1")]), ZIP, ScanFailure.INSPECTION_INCOMPLETE),
    ],
    ids=[
        "truncated",
        "entry-count-mismatch",
        "encrypted",
        "bomb",
        "zip64-streamed-deflated",
        "zip-under-csv",
        "text-under-docx",
        "path-traversal",
    ],
)
async def test_7_to_14_a_structural_hold_is_never_clean_eligible(
    body: bytes, content_type: str, failure: ScanFailure
) -> None:
    assessment = await assess(body, content_type)
    assert assessment.object_check.passed
    assert assessment.scan_result.candidate_clean  # the scanner alone said clean
    assert assessment.structural is not None and not assessment.structural.passed
    assert assessment.outcome is ReleaseOutcome.HELD
    assert not assessment.eligible
    assert assessment.failure is failure
    with pytest.raises(ValueError):
        assessment.clean_evidence(tenant_id=TENANT, file_id=FILE, storage_key=KEY)


async def test_11_12_valid_office_files_pass_the_structural_gate_in_composition() -> None:
    docx = await assess(real_docx(), DOCX_TYPE)
    xlsx = await assess(real_xlsx(), XLSX_TYPE)
    assert docx.structural is not None and docx.structural.outcome is StructuralOutcome.PASS
    assert xlsx.structural is not None and xlsx.structural.outcome is StructuralOutcome.PASS
    assert docx.eligible and xlsx.eligible


async def test_13_a_non_zip_format_is_explicitly_not_required_and_still_needs_the_other_gates() -> (
    None
):
    body = b"id,name\n1,Acme\n2,Initech\n" * 40
    assessment = await assess(body, "text/csv")
    assert assessment.structural is not None
    assert assessment.structural.outcome is StructuralOutcome.NOT_REQUIRED
    assert assessment.eligible
    # NOT_REQUIRED does not waive malware or integrity.
    infected = await assess(body, "text/csv", scanner=FakeScanner.infected())
    assert not infected.eligible
    mismatch = await assess(body, "text/csv", row=RowIntegrity(sha(b"other"), True))
    assert not mismatch.eligible
    unscanned = await assess(body, "text/csv", scanner=FakeScanner.timeout())
    assert not unscanned.eligible


async def test_15_infected_dominates_every_other_gate() -> None:
    body = streamed_zip64_deflated()
    # Infected + object changed + digest mismatch + structural hold: still infected.
    changed = [identity(len(body)), identity(len(body), etag="replaced")]
    a = await assess(body, ZIP, scanner=FakeScanner.infected(), stats=changed)
    b = await assess(
        body,
        ZIP,
        scanner=FakeScanner.infected(),
        row=RowIntegrity(sha(b"other"), True),
    )
    for assessment in (a, b):
        assert assessment.outcome is ReleaseOutcome.INFECTED
        assert not assessment.eligible
    # And with every other gate passing it is still infected, never eligible.
    clean_everything = await assess(real_docx(), DOCX_TYPE, scanner=FakeScanner.infected())
    assert clean_everything.outcome is ReleaseOutcome.INFECTED


async def test_the_assessment_computes_its_outcome_and_cannot_be_set() -> None:
    assessment = await assess(streamed_zip64_deflated(), ZIP)
    assert not assessment.eligible
    with pytest.raises((AttributeError, TypeError)):
        assessment.outcome = ReleaseOutcome.CLEAN_ELIGIBLE  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        assessment.eligible = True  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        assessment.scan_result = ScanResult(ScanOutcome.CANDIDATE_CLEAN)  # type: ignore[misc]
    # Forging one from parts that did not pass still does not release.
    forged = scanning.ReleaseAssessment(
        object_check=assessment.object_check,
        scan_result=ScanResult(ScanOutcome.CANDIDATE_CLEAN),
        integrity=scanning.IntegrityResult(IntegrityOutcome.VERIFIED),
        structural=assessment.structural,
    )
    assert not forged.eligible
    no_structure = scanning.ReleaseAssessment(
        object_check=assessment.object_check,
        scan_result=ScanResult(ScanOutcome.CANDIDATE_CLEAN),
        integrity=scanning.IntegrityResult(IntegrityOutcome.VERIFIED),
        structural=None,
    )
    assert not no_structure.eligible


async def test_scanner_candidate_clean_alone_is_never_sufficient() -> None:
    body = real_docx()
    cases = {
        "integrity": await assess(body, DOCX_TYPE, row=RowIntegrity(sha(b"x"), True)),
        "structure": await assess(streamed_zip64_deflated(), ZIP),
        "object": await assess(
            body, DOCX_TYPE, stats=[identity(len(body)), identity(len(body), etag="other")]
        ),
    }
    for name, assessment in cases.items():
        assert assessment.scan_result.candidate_clean, name
        assert not assessment.eligible, name
    assert ScanResult(ScanOutcome.CANDIDATE_CLEAN).candidate_clean
    assert ScanResult(ScanOutcome.CANDIDATE_CLEAN).requires_structural_gate


async def test_the_first_hold_in_gate_order_is_the_one_reported() -> None:
    body = streamed_zip64_deflated()
    # Scanner hold outranks integrity and structure.
    a = await assess(body, ZIP, scanner=FakeScanner.timeout(), row=RowIntegrity(sha(b"x"), True))
    assert a.failure is ScanFailure.SCAN_TIMEOUT
    # Integrity outranks structure.
    b = await assess(body, ZIP, row=RowIntegrity(sha(b"x"), True))
    assert b.failure is ScanFailure.INTEGRITY_MISMATCH
    # Structure when nothing earlier failed.
    c = await assess(body, ZIP)
    assert c.failure is ScanFailure.INSPECTION_INCOMPLETE


# =========================================================================================
# 12. Safety: no extraction, no network, no XML, no new vocabulary, no accidental transition
# =========================================================================================

_FORBIDDEN_IMPORTS = {
    "zipfile", "tarfile", "shutil", "tempfile", "os", "pathlib", "io", "glob", "fnmatch",
    "socket", "ssl", "http", "urllib", "httpx", "requests", "aiohttp", "ftplib", "smtplib",
    "subprocess", "multiprocessing", "ctypes", "pickle", "marshal", "importlib", "runpy",
    "xml", "lxml", "defusedxml", "html", "xmlrpc", "asyncio", "logging", "sqlalchemy",
}  # fmt: skip
_FORBIDDEN_CALLS = {"open", "eval", "exec", "compile", "__import__", "input", "getattr"}


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


@pytest.mark.parametrize("module", ["structure.py", "release.py"])
def test_the_gates_import_no_filesystem_network_xml_or_process_facility(module: str) -> None:
    path = SCANNING_DIR / module
    assert not _imports(path) & _FORBIDDEN_IMPORTS, _imports(path) & _FORBIDDEN_IMPORTS
    calls = {
        n.func.id
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert not calls & _FORBIDDEN_CALLS, calls & _FORBIDDEN_CALLS


def test_structure_has_no_name_that_reads_storage_or_extracts() -> None:
    tree = ast.parse((SCANNING_DIR / "structure.py").read_text(encoding="utf-8"))
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    for word in ("extract", "extractall", "unzip", "decompress", "decompressobj", "ObjectSource"):
        assert word not in used, word


def test_the_integrity_gate_never_consults_an_etag() -> None:
    tree = ast.parse((SCANNING_DIR / "release.py").read_text(encoding="utf-8"))
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "etag" not in attributes | names
    assert "scan_object_etag" not in attributes | names


def test_the_digest_is_standard_sha256_and_not_md5_or_sha1() -> None:
    source = (SCANNING_DIR / "objects.py").read_text(encoding="utf-8")
    assert "hashlib.sha256()" in source
    assert not re.search(r"hashlib\.(md5|sha1)\b", source)


def test_no_persisted_failure_vocabulary_was_added() -> None:
    # 00040 added `scan_interrupted` to the twelve of 00039 and nothing else.
    migration = (REPO / "supabase" / "migrations" / "00040_file_scan_interrupted.sql").read_text(
        encoding="utf-8"
    )
    check = migration[migration.rindex("files_scan_failure_check") :]
    persisted = set(re.findall(r"'([a-z_]+)'", check.split(");")[0]))
    assert {f.value for f in ScanFailure} == persisted
    assert len(persisted) == 13
    # Every structural and integrity hold maps into that set.
    for outcome in StructuralOutcome:
        result = scanning.StructuralResult(
            outcome,
            reason=None if outcome.passed else StructuralReason.UNSAFE_NAME,
            kind=scanning.ContainerKind.ZIP if outcome is StructuralOutcome.PASS else None,
        )
        assert result.failure is None or result.failure.value in persisted


def test_a_later_migration_never_writes_a_scan_verdict() -> None:
    # The scanner's schema ends at 00041. What follows (the release layer's trigger and
    # gate) reacts to a verdict and writes none: `transition.py` is the only writer.
    names = sorted(p.name for p in (REPO / "supabase" / "migrations").glob("*.sql"))
    for name in names[names.index("00041_file_scan_due_indexes.sql") + 1 :]:
        text = (REPO / "supabase" / "migrations" / name).read_text(encoding="utf-8")
        assert not re.search(r"set\s+scan_status\s*=", text, re.I), name


def test_only_the_transition_module_and_the_runtime_name_commit_clean() -> None:
    """`runtime.py` is the one caller, and only with `assessment.clean_evidence(...)`."""
    offenders = []
    for path in SCANNING_DIR.glob("*.py"):
        if path.name in {"transition.py", "__init__.py", "runtime.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Name) and node.id == "commit_clean") or (
                isinstance(node, ast.Attribute) and node.attr == "commit_clean"
            ):
                offenders.append(path.name)
    assert offenders == []


def test_this_test_file_never_calls_a_production_status_transition() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    banned = {"commit_clean", "commit_infected", "begin_attempt", "record_failure", "record_scan"}
    called = {
        (n.func.id if isinstance(n.func, ast.Name) else n.func.attr)
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))
    }
    assert not called & banned


def test_the_gates_have_one_caller_and_no_retry_no_sweep_and_no_trigger() -> None:
    """`file.scan` exists (tasks/scan.py), the finalizer hands off to it through that module,
    the sweep re-enqueues it (tasks/scan_sweep.py) and the gates are called only by the scanning
    package's own runtime. No other worker file names the task or the package."""
    worker = REPO / "services" / "worker" / "koras_worker"
    allowed = {"scan.py", "scan_sweep.py"}
    for path in worker.rglob("*.py"):
        if "scanning" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        assert "assess_release" not in text, path
        assert "inspect_container" not in text, path
        if path.parent.name == "tasks" and path.name in allowed:
            continue
        if path.name == "worker.py":  # binds the task and schedules the sweep
            continue
        assert "file.scan" not in text, path
        assert "koras_worker.scanning" not in text and "from .scanning" not in text, path
        assert "from ..scanning" not in text, path
    api = REPO / "services" / "api"
    for path in api.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "assess_release" not in text and "inspect_container" not in text, path


def test_a_zlib_bomb_is_never_inflated_by_the_gate() -> None:
    # The gate sees only sizes: a 1 GiB declared expansion costs the same as a 1 KiB one.
    import time

    bomb = Member(b"b.bin", zlib.compress(b"\0" * 1000)[2:-4], method=8, usize=450 * MIB)
    started = time.perf_counter()
    result = inspect(build_zip([bomb]), ZIP)
    assert time.perf_counter() - started < 2
    assert result.outcome is StructuralOutcome.LIMIT_EXCEEDED
    assert structure_module.MAX_EXPANDED_BYTES == 500 * MIB
