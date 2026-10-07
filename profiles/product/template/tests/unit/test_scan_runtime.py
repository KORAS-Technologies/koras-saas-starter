# ruff: noqa: ANN001, ANN201, ANN202, ANN401, E501, S101
"""One `file.scan` run, through the four layers (`secure_files`).

Deterministic: a fake object source, a fake scanner (or the real ClamAV client
against a scripted fake `clamd`), an injected clock, and an in-memory `files`
table with the transitions' own statements. What is asserted is the outcome a
run reaches and the state and audit it leaves; what is *not* asserted here is any
rule the layers own, because those are proved where they live (the client, the
object reader, the transitions, the release assessment). This file proves the composition: the order, the branch each assessment
takes, and that nothing but the assessment can release a file.

The SQL runs against a real PostgreSQL, with RLS, in
`tests/integration/test_scan_runtime_real.py`.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

pytest.importorskip("koras_worker")
from eicar_support import materialize  # noqa: E402
from koras_worker import scanning  # noqa: E402
from koras_worker.scanning import (  # noqa: E402
    ClamdScanner,
    ObjectReader,
    ObjectSourceError,
    ScanDisposition,
    ScanFailure,
    ScanOutcome,
    ScanResult,
    ScanRun,
    scan_file,
)
from koras_worker.scanning import runtime as runtime_module  # noqa: E402
from object_support import (  # noqa: E402
    FILE,
    ISSUED,
    KEY,
    OTHER_TENANT,
    TENANT,
    FakeObjectSource,
    FirstChunkScanner,
    identity,
)
from scan_transition_support import (  # noqa: E402
    OTHER_FILE,
    FakeSession,
    _Result,
    row,
)
from scanner_support import FakeScanner, replying, serving  # noqa: E402
from zip_support import (  # noqa: E402
    DOCX_TYPE,
    XLSX_TYPE,
    Member,
    build_zip,
    real_docx,
    real_xlsx,
    streamed_zip64_deflated,
)

SCANNING_DIR = Path(scanning.__file__).parent
CSV = b"name,amount\nacme,10\nglobex,20\n"
CSV_TYPE = "text/csv"
#: Past the 15 minute ticket and the 60 second margin, as the gate requires.
AFTER_WINDOW = ISSUED + timedelta(minutes=17)
BEFORE_WINDOW = ISSUED + timedelta(minutes=10)
SIGNATURE = b"Win.Test.EICAR_HDB-1"


class RuntimeSession(FakeSession):
    """The transitions' table plus the one read the runtime makes, under the same tenant binding."""

    reads: int = 0

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Result:
        params = params or {}
        if statement is runtime_module._AS_TENANT:
            self.tenant = params["tenant_id"]
            return _Result()
        if statement is runtime_module._ROW:
            self.reads += 1
            found = self._find(params)
            return _Result(copy.deepcopy(found) if found else None)
        return await super().execute(statement, params)


def files(body: bytes = CSV, **overrides: Any) -> list[dict[str, Any]]:
    values: dict[str, Any] = {
        "storage_key": KEY,
        "content_type": CSV_TYPE,
        "created_at": ISSUED,
        "size_bytes": len(body),
    }
    values.update(overrides)
    return [row(**values)]


def source_for(body: bytes = CSV, **kwargs: Any) -> FakeObjectSource:
    return FakeObjectSource(stats=[identity(len(body))], body=body, **kwargs)


def reader_for(source: FakeObjectSource, *, at=AFTER_WINDOW, **kwargs: Any) -> ObjectReader:
    return ObjectReader(source, chunk_bytes=64, clock=lambda: at, **kwargs)


async def run(
    session: RuntimeSession,
    source: FakeObjectSource,
    scanner: Any,
    *,
    at=AFTER_WINDOW,
    tenant: str = TENANT,
    file_id: str = FILE,
    max_attempts: int = 12,
    **kwargs: Any,
) -> ScanRun:
    return await scan_file(
        session,
        tenant_id=tenant,
        file_id=file_id,
        reader=reader_for(source, at=at, **kwargs),
        scanner=scanner,
        max_attempts=max_attempts,
        now=at,
    )


def session_for(body: bytes = CSV, **overrides: Any) -> RuntimeSession:
    return RuntimeSession(files(body, **overrides))


# =========================================================================================
# 1-2. The two verdicts
# =========================================================================================


async def test_a_benign_file_with_every_gate_passing_is_released_clean() -> None:
    session, source = session_for(), source_for()
    result = await run(session, source, FakeScanner.candidate_clean())

    assert result.disposition is ScanDisposition.CLEAN
    final = session.get()
    assert (final["scan_status"], final["status"]) == ("clean", "ready")
    assert final["scan_object_etag"] == "etag-1"
    assert final["scan_failure"] is None
    assert final["scan_attempts"] == 1
    assert session.actions == ["storage.object.scanned"]


async def test_ordinary_malware_quarantines_the_file() -> None:
    eicar = materialize()
    session, source = session_for(eicar), source_for(eicar)
    result = await run(session, source, FakeScanner.infected())

    assert result.disposition is ScanDisposition.INFECTED
    final = session.get()
    assert (final["scan_status"], final["status"]) == ("infected", "quarantined")
    assert final["scan_object_etag"] is None
    assert session.actions == ["storage.object.quarantined"]


async def test_the_real_clamav_client_finding_eicar_quarantines_it_and_persists_no_signature() -> (
    None
):
    """Test 22 against the actual client and a scripted `clamd`, not a stub of it."""
    eicar = materialize()
    session, source = session_for(eicar), source_for(eicar)
    async with serving(lambda fake: replying(fake, b"stream: " + SIGNATURE + b" FOUND\0")) as fake:
        scanner = ClamdScanner(
            host="127.0.0.1",
            port=fake.port,
            connect_timeout=2.0,
            scan_timeout=5.0,
            max_bytes=1 << 20,
        )
        result = await run(session, source, scanner)

    assert result.disposition is ScanDisposition.INFECTED
    stored = repr((session.rows, session.audit_rows, result))
    assert SIGNATURE.decode() not in stored
    assert "EICAR_HDB" not in stored


# =========================================================================================
# 3-14. Everything that is not a verdict holds the file pending, with a reason
# =========================================================================================


async def assert_held(
    session: RuntimeSession, result: ScanRun, failure: ScanFailure, *, attempts: int = 1
) -> None:
    assert result.disposition is ScanDisposition.HELD
    assert result.failure is failure
    final = session.get()
    assert (final["scan_status"], final["status"]) == ("pending", "ready")
    assert final["scan_failure"] == failure.value
    assert final["scan_attempts"] == attempts
    assert final["scan_object_etag"] is None


async def test_a_candidate_clean_with_a_structural_hold_stays_pending() -> None:
    body = streamed_zip64_deflated()
    session = session_for(body, content_type="application/zip")
    result = await run(session, source_for(body), FakeScanner.candidate_clean())
    await assert_held(session, result, ScanFailure.INSPECTION_INCOMPLETE)
    assert session.actions == ["storage.object.scan_failed"]


async def test_a_claimed_digest_the_bytes_contradict_stays_pending() -> None:
    session = session_for(checksum_sha256="0" * 64)
    result = await run(session, source_for(), FakeScanner.candidate_clean())
    await assert_held(session, result, ScanFailure.INTEGRITY_MISMATCH)


async def test_a_corroborated_digest_the_bytes_contradict_stays_pending() -> None:
    from datetime import UTC, datetime

    session = session_for(checksum_sha256="0" * 64, checksum_verified_at=datetime.now(UTC))
    result = await run(session, source_for(), FakeScanner.candidate_clean())
    await assert_held(session, result, ScanFailure.INTEGRITY_MISMATCH)


async def test_a_corroborated_digest_with_no_digest_on_the_row_stays_pending() -> None:
    """Required integrity evidence that is missing is a hold, not a pass."""
    from datetime import UTC, datetime

    session = session_for(checksum_sha256=None, checksum_verified_at=datetime.now(UTC))
    result = await run(session, source_for(), FakeScanner.candidate_clean())
    await assert_held(session, result, ScanFailure.INTEGRITY_MISMATCH)


async def test_a_corroborated_matching_digest_is_released() -> None:
    from datetime import UTC, datetime

    digest = hashlib.sha256(CSV).hexdigest()
    session = session_for(checksum_sha256=digest, checksum_verified_at=datetime.now(UTC))
    result = await run(session, source_for(), FakeScanner.candidate_clean())
    assert result.disposition is ScanDisposition.CLEAN


async def test_an_object_that_changed_during_the_scan_stays_pending() -> None:
    source = FakeObjectSource(
        stats=[identity(len(CSV)), identity(len(CSV), etag="replaced")], body=CSV
    )
    session = session_for()
    result = await run(session, source, FakeScanner.candidate_clean())
    await assert_held(session, result, ScanFailure.OBJECT_CHANGED)


async def test_an_object_of_the_wrong_size_stays_pending() -> None:
    session = session_for(size_bytes=len(CSV) + 5)
    result = await run(session, source_for(), FakeScanner.candidate_clean())
    await assert_held(session, result, ScanFailure.OBJECT_CHANGED)


async def test_an_object_the_store_cannot_find_stays_pending() -> None:
    source = FakeObjectSource(stats=[None])
    session = session_for()
    result = await run(session, source, FakeScanner.candidate_clean())
    await assert_held(session, result, ScanFailure.OBJECT_UNREACHABLE)
    assert source.verbs == ["stat"]


async def test_an_object_store_that_cannot_be_asked_stays_pending() -> None:
    source = FakeObjectSource(stats=[ObjectSourceError("down")])
    session = session_for()
    result = await run(session, source, FakeScanner.candidate_clean())
    await assert_held(session, result, ScanFailure.OBJECT_UNREACHABLE)


async def test_an_object_that_fails_mid_read_stays_pending() -> None:
    source = source_for(fail_after=10)
    session = session_for()
    result = await run(session, source, FakeScanner.candidate_clean())
    await assert_held(session, result, ScanFailure.OBJECT_UNREACHABLE)


class _NonReading:
    """A scanner that answers without consuming the stream, as an outage does."""

    def __init__(self, result: ScanResult | Exception) -> None:
        self._result = result

    async def scan(self, source):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    async def ping(self) -> bool:
        return False


@pytest.mark.parametrize(
    ("outcome", "failure"),
    [
        (ScanOutcome.UNAVAILABLE, ScanFailure.SCANNER_UNAVAILABLE),
        (ScanOutcome.TIMEOUT, ScanFailure.SCAN_TIMEOUT),
        (ScanOutcome.MALFORMED_RESPONSE, ScanFailure.MALFORMED_RESPONSE),
        (ScanOutcome.SCANNER_ERROR, ScanFailure.SCANNER_ERROR),
        (ScanOutcome.MISCONFIGURED, ScanFailure.MISCONFIGURED),
        (ScanOutcome.LIMIT_EXCEEDED, ScanFailure.SCAN_LIMIT_EXCEEDED),
    ],
)
async def test_a_scanner_that_never_took_the_stream_is_recorded_as_the_scanner_not_the_object(
    outcome: ScanOutcome, failure: ScanFailure
) -> None:
    """Without the refinement the object gate's incomplete read would label an outage `object_unreachable`."""
    session = session_for()
    result = await run(session, source_for(), _NonReading(ScanResult(outcome)))
    await assert_held(session, result, failure)


async def test_a_scanner_that_raises_is_a_hold_never_a_pass() -> None:
    session = session_for()
    result = await run(session, source_for(), _NonReading(RuntimeError("boom")))
    await assert_held(session, result, ScanFailure.SCANNER_ERROR)


@pytest.mark.parametrize(
    "builder", [FakeScanner.unavailable, FakeScanner.timeout, FakeScanner.malformed]
)
async def test_a_scanner_that_read_everything_and_failed_is_held_by_the_scanner_class(
    builder,
) -> None:
    session = session_for()
    result = await run(session, source_for(), builder())
    assert result.disposition is ScanDisposition.HELD
    assert session.get()["scan_status"] == "pending"


async def test_an_incomplete_inspection_is_held_not_released() -> None:
    session = session_for()
    scanner = FakeScanner(
        ScanResult(ScanOutcome.INCOMPLETE_INSPECTION, scanning.IncompleteKind.INCOMPLETE)
    )
    result = await run(session, source_for(), scanner)
    await assert_held(session, result, ScanFailure.INSPECTION_INCOMPLETE)


async def test_a_scanner_ok_that_stopped_reading_is_not_a_release() -> None:
    """The scanner said OK after one chunk; the object gate says the read was incomplete."""
    session = session_for()
    result = await run(session, source_for(), FirstChunkScanner())
    await assert_held(session, result, ScanFailure.OBJECT_UNREACHABLE)


async def test_an_encrypted_archive_is_held() -> None:
    body = build_zip(
        [Member.stored(b"ok.txt", b"fine"), Member.stored(b"s.txt", b"x", flags=0x0001)]
    )
    session = session_for(body, content_type="application/zip")
    result = await run(session, source_for(body), FakeScanner.candidate_clean())
    await assert_held(session, result, ScanFailure.INSPECTION_INCOMPLETE)


async def test_a_top_level_streamed_deflated_zip64_archive_is_held() -> None:
    for declared in ("application/zip", DOCX_TYPE, XLSX_TYPE):
        body = streamed_zip64_deflated()
        session = session_for(body, content_type=declared)
        result = await run(session, source_for(body), FakeScanner.candidate_clean())
        await assert_held(session, result, ScanFailure.INSPECTION_INCOMPLETE)


async def test_a_declared_type_the_container_contradicts_is_held() -> None:
    cases = [
        (real_docx(), XLSX_TYPE),
        (real_xlsx(), DOCX_TYPE),
        (b"%PDF-1.4 not a zip", "application/zip"),
        (real_docx(), "application/zip-but-not"),
    ]
    for body, declared in cases:
        session = session_for(body, content_type=declared)
        result = await run(session, source_for(body), FakeScanner.candidate_clean())
        assert result.disposition is ScanDisposition.HELD, declared
        assert session.get()["scan_status"] == "pending"


async def test_genuine_office_documents_are_released() -> None:
    for body, declared in [(real_docx(), DOCX_TYPE), (real_xlsx(), XLSX_TYPE)]:
        session = session_for(body, content_type=declared)
        result = await run(session, source_for(body), FakeScanner.candidate_clean())
        assert result.disposition is ScanDisposition.CLEAN, declared


# =========================================================================================
# The window and the ceiling: deferred or held without an attempt
# =========================================================================================


async def test_a_file_inside_the_upload_window_is_deferred_and_nothing_is_touched() -> None:
    session, source = session_for(), source_for()
    result = await run(session, source, FakeScanner.candidate_clean(), at=BEFORE_WINDOW)

    assert result.disposition is ScanDisposition.POSTPONED
    assert result.opens_at == ISSUED + timedelta(minutes=16)
    assert source.calls == []  # not even metadata
    assert session.writes == 0
    assert session.get()["scan_attempts"] == 0
    assert session.audit_rows == []


async def test_the_window_is_the_issue_time_plus_sixteen_minutes_to_the_second() -> None:
    just_before = ISSUED + timedelta(minutes=16) - timedelta(seconds=1)
    exactly = ISSUED + timedelta(minutes=16)
    assert (
        await run(session_for(), source_for(), FakeScanner.candidate_clean(), at=just_before)
    ).disposition is ScanDisposition.POSTPONED
    assert (
        await run(session_for(), source_for(), FakeScanner.candidate_clean(), at=exactly)
    ).disposition is ScanDisposition.CLEAN


async def test_an_oversized_object_is_held_without_an_attempt_and_is_never_read() -> None:
    source = FakeObjectSource(stats=[identity(len(CSV))], body=CSV)
    session = session_for()
    result = await run(session, source, FakeScanner.candidate_clean(), max_bytes=len(CSV) - 1)

    assert result.disposition is ScanDisposition.HELD
    assert result.failure is ScanFailure.OVER_CEILING
    final = session.get()
    assert (final["scan_attempts"], final["scan_status"]) == (0, "pending")
    assert final["scan_failure"] == "over_ceiling"
    assert "open" not in source.verbs


async def test_a_key_that_does_not_belong_to_the_file_is_held_and_never_read() -> None:
    source = source_for()
    session = session_for(
        storage_key=f"tenants/{OTHER_TENANT}/documents/{FILE}/final/{OTHER_FILE}/a.csv"
    )
    result = await run(session, source, FakeScanner.candidate_clean())
    await assert_held(session, result, ScanFailure.OBJECT_UNREACHABLE)
    assert source.calls == []


# =========================================================================================
# 15-17. Duplicates, races and other tenants
# =========================================================================================


async def test_a_duplicate_invocation_is_safe() -> None:
    session = session_for()
    first = await run(session, source_for(), FakeScanner.candidate_clean())
    second = await run(session, source_for(), FakeScanner.candidate_clean())

    assert first.disposition is ScanDisposition.CLEAN
    assert second.disposition is ScanDisposition.NOT_ELIGIBLE
    assert session.get()["scan_attempts"] == 1
    assert session.actions == ["storage.object.scanned"]


async def test_a_duplicate_infected_run_leaves_one_quarantine_event() -> None:
    session = session_for()
    await run(session, source_for(), FakeScanner.infected())
    again = await run(session, source_for(), FakeScanner.infected())
    assert again.disposition is ScanDisposition.NOT_ELIGIBLE
    assert session.actions == ["storage.object.quarantined"]


async def test_a_run_whose_file_left_pending_during_the_scan_changes_nothing() -> None:
    session = session_for()

    class Quarantines(FakeScanner):
        async def scan(self, source):
            result = await super().scan(source)
            session.get().update(scan_status="infected", status="quarantined")
            return result

    result = await run(session, source_for(), Quarantines(ScanResult(ScanOutcome.CANDIDATE_CLEAN)))
    assert result.disposition is ScanDisposition.NOT_ELIGIBLE
    final = session.get()
    assert (final["scan_status"], final["status"]) == ("infected", "quarantined")
    assert session.audit_rows == []


class _After(FakeScanner):
    """Answers only once the other run's verdict is committed, so the commit order is chosen."""

    def __init__(self, result: ScanResult, session: RuntimeSession, seen: str) -> None:
        super().__init__(result)
        self._session, self._seen = session, seen

    async def scan(self, source):
        verdict = await super().scan(source)
        for _ in range(400):
            if self._session.get()["scan_status"] == self._seen:
                return verdict
            await asyncio.sleep(0.01)
        raise AssertionError("the other run never committed")


async def test_concurrent_clean_and_infected_ends_infected_in_either_commit_order() -> None:
    """Both runs read the row while it is pending; whichever commits first, infected wins (6b)."""
    for infected_commits_first in (True, False):
        session = session_for()
        clean = FakeScanner(ScanResult(ScanOutcome.CANDIDATE_CLEAN))
        infected = FakeScanner(ScanResult(ScanOutcome.INFECTED))
        if infected_commits_first:
            clean = _After(clean._result, session, "infected")
        else:
            infected = _After(infected._result, session, "clean")
        results = await asyncio.gather(
            run(session, source_for(), clean), run(session, source_for(), infected)
        )
        final = session.get()
        assert (final["scan_status"], final["status"]) == ("infected", "quarantined")
        assert session.reads == 2
        assert session.actions.count("storage.object.quarantined") == 1
        assert ScanDisposition.INFECTED in {r.disposition for r in results}
        if infected_commits_first:
            assert "storage.object.scanned" not in session.actions
        else:
            assert session.actions == ["storage.object.scanned", "storage.object.quarantined"]


async def test_a_job_naming_another_tenants_file_finds_nothing_and_writes_nothing() -> None:
    session = session_for()
    source = source_for()
    result = await run(session, source, FakeScanner.candidate_clean(), tenant=OTHER_TENANT)

    assert result.disposition is ScanDisposition.NOT_ELIGIBLE
    assert source.calls == []
    assert session.writes == 0
    assert session.audit_rows == []
    assert session.get()["scan_attempts"] == 0


async def test_a_file_that_does_not_exist_is_not_eligible() -> None:
    session = session_for()
    result = await run(session, source_for(), FakeScanner.candidate_clean(), file_id=OTHER_FILE)
    assert result.disposition is ScanDisposition.NOT_ELIGIBLE


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "quarantined", "scan_status": "infected"},
        {"scan_status": "clean"},
        {"scan_status": "skipped"},
        {"status": "pending"},
    ],
)
async def test_a_file_that_is_not_pending_and_ready_is_left_alone(
    overrides: dict[str, Any],
) -> None:
    session = session_for(**overrides)
    source = source_for()
    result = await run(session, source, FakeScanner.candidate_clean())
    assert result.disposition is ScanDisposition.NOT_ELIGIBLE
    assert source.calls == []
    assert session.writes == 0


@pytest.mark.parametrize(
    "bad", ["not-a-uuid", "", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", "{" + FILE + "}"]
)
async def test_a_malformed_identifier_is_refused_before_anything_is_read(bad: str) -> None:
    session = session_for()
    with pytest.raises(ValueError, match="canonical UUID"):
        await run(session, source_for(), FakeScanner.candidate_clean(), file_id=bad)
    with pytest.raises(ValueError, match="canonical UUID"):
        await run(session, source_for(), FakeScanner.candidate_clean(), tenant=bad)
    assert session.reads == 0


# =========================================================================================
# 18-21. Audit and accounting
# =========================================================================================


async def test_clean_emits_the_scanned_audit_event_with_the_release_in_one_transaction() -> None:
    session = session_for()
    await run(session, source_for(), FakeScanner.candidate_clean())
    assert session.actions == ["storage.object.scanned"]
    assert session.audit_rows[0]["tenant_id"] == TENANT


async def test_an_infected_verdict_and_its_quarantine_event_commit_together_or_not_at_all() -> None:
    session = session_for()
    session.fail_audit_insert = True
    with pytest.raises(RuntimeError, match="audit insert failed"):
        await run(session, source_for(), FakeScanner.infected())
    final = session.get()
    assert (final["scan_status"], final["status"]) == ("pending", "ready")
    assert session.audit_rows == []


async def test_a_failure_writes_one_failure_event_and_the_same_failure_again_writes_none() -> None:
    session = session_for()
    for attempt in (1, 2, 3):
        result = await run(session, source_for(), FakeScanner.unavailable())
        assert result.attempts == attempt
    assert session.actions.count("storage.object.scan_failed") == 1
    assert session.get()["scan_attempts"] == 3


async def test_a_changed_failure_class_writes_a_new_event() -> None:
    session = session_for()
    await run(session, source_for(), FakeScanner.unavailable())
    await run(session, source_for(), FakeScanner.timeout())
    assert session.actions.count("storage.object.scan_failed") == 2


async def test_reaching_the_threshold_writes_scan_exhausted_once_and_the_file_stays_pending() -> (
    None
):
    session = session_for()
    for _ in range(6):
        await run(session, source_for(), FakeScanner.unavailable(), max_attempts=3)
    assert session.actions.count("storage.object.scan_exhausted") == 1
    final = session.get()
    assert (final["scan_status"], final["status"]) == ("pending", "ready")
    assert final["scan_attempts"] == 6


async def test_a_file_past_the_threshold_is_still_scanned_and_can_still_be_released() -> None:
    """Exhaustion is a signal. It does not exclude the file from a later reconciliation."""
    session = session_for()
    for _ in range(4):
        await run(session, source_for(), FakeScanner.unavailable(), max_attempts=3)
    result = await run(session, source_for(), FakeScanner.candidate_clean(), max_attempts=3)
    assert result.disposition is ScanDisposition.CLEAN
    assert session.get()["scan_status"] == "clean"


async def test_an_infected_verdict_on_an_exhausted_file_still_quarantines() -> None:
    session = session_for(scan_attempts=50)
    result = await run(session, source_for(), FakeScanner.infected(), max_attempts=3)
    assert result.disposition is ScanDisposition.INFECTED


# =========================================================================================
# Nothing can release a file by failing, and the module holds no write and no rule
# =========================================================================================


@pytest.mark.parametrize(
    "scanner",
    [
        FakeScanner.unavailable,
        FakeScanner.timeout,
        FakeScanner.malformed,
        FakeScanner.limit_exceeded,
        lambda: _NonReading(RuntimeError("x")),
        lambda: FirstChunkScanner(),
    ],
)
async def test_no_scanner_failure_can_release_a_file(scanner) -> None:
    session = session_for()
    result = await run(session, source_for(), scanner())
    assert result.disposition is ScanDisposition.HELD
    assert session.get()["scan_status"] == "pending"
    assert "storage.object.scanned" not in session.actions


async def test_the_unavailable_scanner_resolved_for_backend_none_holds_and_never_reads() -> None:
    from koras_worker.scanning import ScannerSettings, resolve_scanner

    scanner = resolve_scanner(ScannerSettings(file_scan_backend="none"))
    session, source = session_for(), source_for()
    result = await run(session, source, scanner)
    await assert_held(session, result, ScanFailure.MISCONFIGURED)
    assert "open" not in source.verbs


INCOMING = f"tenants/{TENANT}/documents/{FILE}/incoming/{OTHER_FILE}/report.pdf"
LEGACY = f"tenants/{TENANT}/documents/{FILE}/report.pdf"


@pytest.mark.parametrize("key", [INCOMING, LEGACY], ids=["incoming", "legacy-shaped"])
async def test_only_a_final_key_is_scanned_anything_else_is_held_with_no_write_and_no_read(
    key: str, caplog: pytest.LogCaptureFixture
) -> None:
    """No verdict, no attempt, no store call; a log line says why. The finalizer owns the rest."""
    session, source = session_for(storage_key=key), source_for()
    before = copy.deepcopy(session.rows)
    with caplog.at_level("WARNING", logger="koras_worker.scanning.runtime"):
        result = await run(session, source, FakeScanner.candidate_clean())

    assert result == ScanRun(ScanDisposition.NOT_ELIGIBLE)
    assert session.rows == before and session.audit_rows == []
    assert (session.writes, session.commits) == (0, 0)
    assert source.verbs == [] and "open" not in source.verbs
    assert any("not on a final key" in record.getMessage() for record in caplog.records)


def test_the_runtime_has_no_finalizer_and_no_restore_provenance_read() -> None:
    code = re.sub(r'""".*?"""', "", _runtime_source(), flags=re.S)
    assert "uploads" not in code and "Finalizer" not in code and "finalizer" not in code.split("#")[0]
    assert "restore" not in code.lower() and "legacy" not in code.lower()


def _runtime_source() -> str:
    return (SCANNING_DIR / "runtime.py").read_text(encoding="utf-8")


def test_the_runtime_writes_no_scan_state_itself() -> None:
    """Every write is a transition's. The only SQL here is one read."""
    source = _runtime_source()
    statements = [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    # A statement starts with its verb; the module docstring merely mentions them.
    sql = " ".join(
        s for s in statements if re.match(r"\s*(select|update|insert|delete)\b", s, re.I)
    )
    assert sql.lower().startswith("select"), "the one statement is the read"
    assert not re.search(r"\b(update|insert|delete|truncate|alter|drop)\b", sql, re.I)
    assert not re.search(r"for\s+update", sql, re.I)
    for column in ("scan_status", "scan_failure", "scan_attempts", "scan_object_etag", "scan_note"):
        assert not re.search(rf"set\s+{column}|{column}\s*=\s*:", sql), column
    assert "update public.files" not in source.lower()


def test_the_release_call_takes_only_the_assessments_own_evidence() -> None:
    source = _runtime_source()
    assert source.count("commit_clean(") == 1
    assert "assessment.clean_evidence(" in source
    assert "CleanEvidence(" not in source
    # Nothing decides eligibility here: the assessment's outcome is the only branch.
    for forbidden in ("candidate_clean", "structural", "integrity.passed", ".passed"):
        assert forbidden not in re.sub(r'""".*?"""', "", source, flags=re.S), forbidden


def test_the_runtime_reaches_no_network_and_no_signed_url() -> None:
    source = re.sub(r'""".*?"""', "", _runtime_source(), flags=re.S)
    for forbidden in ("presign", "boto", "httpx", "urllib", "socket", "http://", "https://"):
        assert forbidden not in source, forbidden
