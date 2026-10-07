# ruff: noqa: ANN401, E501, S101
"""The guarded transitions out of `pending`.

Deterministic, no network, no clock. What is asserted is state and audit: every
transition the module can make, every refusal, and that nothing outside the
guard (`scan_status = 'pending'` and `status = 'ready'`, this tenant) is ever
written. The SQL is run against a real PostgreSQL in
`tests/integration/test_scan_transition_real.py`.
"""

from __future__ import annotations

import os
import re
from collections.abc import Awaitable
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

pytest.importorskip("koras_worker")
from koras_audit import Classification, actions  # noqa: E402
from koras_worker import scanning  # noqa: E402
from koras_worker.scanning import (  # noqa: E402
    CleanEvidence,
    ObjectCheck,
    ObjectGate,
    ScanFailure,
    ScanOutcome,
    ScanResult,
    TransitionKind,
    TransitionResult,
    TransitionUnavailable,
    begin_attempt,
    commit_clean,
    commit_infected,
    record_failure,
)
from koras_worker.scanning import transition as transition_module  # noqa: E402
from koras_worker.scanning.config import MAX_RECORDED_ATTEMPTS, ScannerSettings  # noqa: E402
from object_support import identity  # noqa: E402
from scan_transition_support import (  # noqa: E402
    FILE,
    NOW,
    OTHER_FILE,
    OTHER_TENANT,
    TENANT,
    FakeSession,
    row,
)

SCANNING_DIR = Path(scanning.__file__).parent
REPO = SCANNING_DIR.parents[3]
DIGEST = "ab" * 32
OTHER_DIGEST = "cd" * 32


def evidence(**overrides: Any) -> CleanEvidence:
    values: dict[str, Any] = {
        "tenant_id": TENANT,
        "file_id": FILE,
        "storage_key": f"tenants/{TENANT}/imports/{FILE}/a.csv",
        "object_check": ObjectCheck(ObjectGate.READY, bytes_read=100, identity=identity(100)),
        "scan_result": ScanResult(ScanOutcome.CANDIDATE_CLEAN),
        "structural_gate_passed": True,
    }
    values.update(overrides)
    return CleanEvidence(**values)


def attempt(
    session: FakeSession, *, maximum: int = 12, file: str = FILE, tenant: str = TENANT
) -> Awaitable[TransitionResult]:
    return begin_attempt(session, tenant_id=tenant, file_id=file, now=NOW, max_attempts=maximum)


# --- evidence: clean cannot be asked for without its three conditions -------------


@pytest.mark.parametrize("gate", [g for g in ObjectGate if g is not ObjectGate.READY])
def test_clean_evidence_refuses_every_object_gate_that_did_not_pass(gate: ObjectGate) -> None:
    with pytest.raises(ValueError, match="object gate"):
        evidence(object_check=ObjectCheck(gate, identity=identity(1)))


def test_clean_evidence_refuses_a_passed_gate_with_no_identity() -> None:
    with pytest.raises(ValueError, match="object gate"):
        evidence(object_check=ObjectCheck(ObjectGate.READY))


@pytest.mark.parametrize(
    "outcome", [o for o in ScanOutcome if o is not ScanOutcome.CANDIDATE_CLEAN]
)
def test_clean_evidence_refuses_every_scanner_result_but_candidate_clean(
    outcome: ScanOutcome,
) -> None:
    from koras_worker.scanning import IncompleteKind

    kind = IncompleteKind.ENCRYPTED if outcome is ScanOutcome.INCOMPLETE_INSPECTION else None
    with pytest.raises(ValueError, match="candidate-clean"):
        evidence(scan_result=ScanResult(outcome, incomplete_kind=kind))


@pytest.mark.parametrize("passed", [False, None, 1, "yes"])
def test_clean_evidence_needs_the_structural_gate_to_be_exactly_true(passed: Any) -> None:
    with pytest.raises(ValueError, match="structural gate"):
        evidence(structural_gate_passed=passed)


@pytest.mark.parametrize("digest", ["", "AB" * 32, "ab" * 31, "zz" * 32])
def test_clean_evidence_refuses_a_malformed_digest(digest: str) -> None:
    with pytest.raises(ValueError, match="content_sha256"):
        evidence(content_sha256=digest)


async def test_commit_clean_refuses_anything_but_evidence() -> None:
    session = FakeSession([row()])
    with pytest.raises(TypeError):
        await commit_clean(session, tenant_id=TENANT, file_id=FILE, evidence=True)  # type: ignore[arg-type]
    assert session.writes == 0 and session.commits == 0


# --- begin_attempt ----------------------------------------------------------------


async def test_an_attempt_is_counted_and_stamped_and_nothing_else_moves() -> None:
    session = FakeSession([row()])
    result = await attempt(session)
    assert result.kind is TransitionKind.APPLIED and result.attempts == 1
    stored = session.get()
    assert (stored["scan_attempts"], stored["scan_attempted_at"]) == (1, NOW)
    assert (stored["scan_status"], stored["status"]) == ("pending", "ready")
    assert stored["scan_failure"] is None and stored["scan_object_etag"] is None
    assert session.audit_rows == [] and session.commits == 1


async def test_exhaustion_is_written_once_on_the_attempt_that_reaches_the_threshold() -> None:
    session = FakeSession([row()])
    results = [await attempt(session, maximum=3) for _ in range(6)]
    assert [r.attempts for r in results] == [1, 2, 3, 4, 5, 6]
    assert [r.audited for r in results] == [(), (), ("storage.object.scan_exhausted",), (), (), ()]
    assert session.actions == ["storage.object.scan_exhausted"]
    event = session.audit_rows[0]
    assert event["outcome"] == "failed" and event["actor_id"] == "system"
    assert event["target_type"] == "file" and event["target_id"] == FILE
    assert event["tenant_id"] == TENANT
    assert event["details"] == '{"attempts": 3, "threshold": 3}'
    assert event["classification"] == "security"


async def test_exhaustion_does_not_release_or_exclude_the_file() -> None:
    """Past the threshold the file is still pending, still ready, still attempted."""
    session = FakeSession([row()])
    for _ in range(5):
        await attempt(session, maximum=2)
    stored = session.get()
    assert (stored["scan_status"], stored["status"]) == ("pending", "ready")
    assert stored["scan_attempts"] == 5
    assert (await attempt(session, maximum=2)).kind is TransitionKind.APPLIED


async def test_the_first_attempt_is_the_exhaustion_when_the_threshold_is_one() -> None:
    session = FakeSession([row()])
    first = await attempt(session, maximum=1)
    assert first.audited == ("storage.object.scan_exhausted",)
    assert (await attempt(session, maximum=1)).audited == ()


async def test_the_counter_saturates_and_saturation_cannot_repeat_the_exhaustion() -> None:
    session = FakeSession([row(scan_attempts=MAX_RECORDED_ATTEMPTS - 1)])
    reached = await attempt(session, maximum=MAX_RECORDED_ATTEMPTS)
    assert reached.attempts == MAX_RECORDED_ATTEMPTS
    assert reached.audited == ("storage.object.scan_exhausted",)
    again = await attempt(session, maximum=MAX_RECORDED_ATTEMPTS)
    assert again.attempts == MAX_RECORDED_ATTEMPTS and again.audited == ()
    assert session.actions == ["storage.object.scan_exhausted"]


async def test_raising_the_threshold_above_a_count_already_passed_writes_nothing() -> None:
    session = FakeSession([row(scan_attempts=20)])
    assert (await attempt(session, maximum=12)).audited == ()
    assert session.audit_rows == []


@pytest.mark.parametrize("maximum", [0, -1, MAX_RECORDED_ATTEMPTS + 1])
async def test_an_attempt_refuses_a_threshold_outside_the_column(maximum: int) -> None:
    session = FakeSession([row()])
    with pytest.raises(ValueError, match="max_attempts"):
        await attempt(session, maximum=maximum)
    assert session.writes == 0


async def test_an_attempt_refuses_a_naive_time() -> None:
    session = FakeSession([row()])
    with pytest.raises(ValueError, match="timezone"):
        await begin_attempt(
            session, tenant_id=TENANT, file_id=FILE, now=NOW.replace(tzinfo=None), max_attempts=3
        )


# --- record_failure ---------------------------------------------------------------


@pytest.mark.parametrize("failure", list(ScanFailure))
async def test_every_failure_class_is_recorded_and_leaves_the_file_pending(
    failure: ScanFailure,
) -> None:
    session = FakeSession([row()])
    result = await record_failure(session, tenant_id=TENANT, file_id=FILE, failure=failure)
    assert result.kind is TransitionKind.APPLIED and result.audited == (
        "storage.object.scan_failed",
    )
    stored = session.get()
    assert stored["scan_failure"] == failure.value
    assert (stored["scan_status"], stored["status"]) == ("pending", "ready")
    assert stored["scan_attempts"] == 0
    assert session.audit_rows[0]["details"] == f'{{"reason": "{failure.value}"}}'
    assert session.audit_rows[0]["outcome"] == "failed"


async def test_an_outage_is_one_event_however_many_attempts_it_spans() -> None:
    session = FakeSession([row()])
    kinds = []
    for _ in range(5):
        await attempt(session)
        kinds.append(
            (
                await record_failure(
                    session,
                    tenant_id=TENANT,
                    file_id=FILE,
                    failure=ScanFailure.SCANNER_UNAVAILABLE,
                )
            ).kind
        )
    assert kinds == [TransitionKind.APPLIED] + [TransitionKind.UNCHANGED] * 4
    assert session.actions == ["storage.object.scan_failed"]


async def test_the_same_failure_again_writes_nothing_and_commits_nothing() -> None:
    session = FakeSession([row(scan_failure="scan_timeout")])
    before = session.commits
    result = await record_failure(
        session, tenant_id=TENANT, file_id=FILE, failure=ScanFailure.SCAN_TIMEOUT
    )
    assert result.kind is TransitionKind.UNCHANGED
    assert session.writes == 0 and session.audit_rows == [] and session.commits == before


async def test_a_change_of_class_writes_a_new_event_and_a_return_to_a_class_writes_again() -> None:
    session = FakeSession([row()])
    for failure in (
        ScanFailure.SCANNER_UNAVAILABLE,
        ScanFailure.SCAN_TIMEOUT,
        ScanFailure.SCANNER_UNAVAILABLE,
    ):
        await record_failure(session, tenant_id=TENANT, file_id=FILE, failure=failure)
    assert session.actions == ["storage.object.scan_failed"] * 3


async def test_a_failure_must_be_a_scan_failure_value_not_a_string() -> None:
    session = FakeSession([row()])
    with pytest.raises(TypeError):
        await record_failure(
            session,
            tenant_id=TENANT,
            file_id=FILE,
            failure="scan_exhausted",  # type: ignore[arg-type]
        )
    assert session.writes == 0


def test_scan_exhausted_is_not_a_failure_value() -> None:
    assert "scan_exhausted" not in {f.value for f in ScanFailure}
    assert "skipped" not in {f.value for f in ScanFailure}


def test_the_failure_vocabulary_is_exactly_the_database_check() -> None:
    sql = (REPO / "supabase" / "migrations" / "00040_file_scan_interrupted.sql").read_text("utf-8")
    block = sql.split("files_scan_failure_check\n  check (scan_failure in (")[1].split("));")[0]
    in_database = set(re.findall(r"'([a-z_]+)'", block))
    assert {f.value for f in ScanFailure} == in_database
    assert len(in_database) == 13


# --- commit_infected --------------------------------------------------------------


async def test_infected_quarantines_in_one_write_and_clears_the_failure() -> None:
    session = FakeSession([row(scan_failure="scanner_unavailable", scan_attempts=4)])
    result = await commit_infected(session, tenant_id=TENANT, file_id=FILE)
    assert result.kind is TransitionKind.APPLIED
    assert result.audited == ("storage.object.quarantined",)
    stored = session.get()
    assert (stored["scan_status"], stored["status"]) == ("infected", "quarantined")
    assert stored["scan_failure"] is None and stored["scan_object_etag"] is None
    assert stored["scan_note"] == transition_module.NOTE_INFECTED
    assert stored["scan_attempts"] == 4
    event = session.audit_rows[0]
    assert (event["outcome"], event["classification"]) == ("denied", "security")
    assert event["details"] == '{"scan_status": "infected"}'
    assert session.commits == 1  # state and event are one commit


async def test_infected_needs_no_object_identity() -> None:
    """Quarantine is the safe direction: it is committed whatever the object did."""
    import inspect

    assert "evidence" not in inspect.signature(commit_infected).parameters
    session = FakeSession([row()])
    assert (await commit_infected(session, tenant_id=TENANT, file_id=FILE)).kind is (
        TransitionKind.APPLIED
    )


@pytest.mark.parametrize("state", ["pending", "clean"])
async def test_infected_fails_closed_when_the_audit_sink_is_not_on_the_path(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    """No SECURITY event available, no quarantine - from `pending` or over `clean`."""
    original = transition_module._audit_module()
    monkeypatch.setattr(transition_module, "_audit_module", lambda: None)
    session = FakeSession([row(scan_status=state, scan_object_etag="etag-1")])
    snapshot = dict(session.get())
    with pytest.raises(TransitionUnavailable):
        await commit_infected(session, tenant_id=TENANT, file_id=FILE)
    assert session.get() == snapshot
    assert session.audit_rows == [] and session.writes == 0
    # the dependency returns: the retry succeeds, with its event
    monkeypatch.setattr(transition_module, "_audit_module", lambda: original)
    result = await commit_infected(session, tenant_id=TENANT, file_id=FILE)
    assert result.kind is TransitionKind.APPLIED
    assert result.audited == ("storage.object.quarantined",)
    assert (session.get()["scan_status"], session.get()["status"]) == ("infected", "quarantined")
    assert len(session.audit_rows) == 1


async def test_a_late_clean_after_infected_changes_nothing() -> None:
    session = FakeSession([row()])
    await commit_infected(session, tenant_id=TENANT, file_id=FILE)
    snapshot = dict(session.get())
    result = await commit_clean(session, tenant_id=TENANT, file_id=FILE, evidence=evidence())
    assert result.kind is TransitionKind.NOT_ELIGIBLE
    assert session.get() == snapshot
    assert session.actions == ["storage.object.quarantined"]


async def test_a_second_infected_is_a_no_op_and_writes_no_second_event() -> None:
    session = FakeSession([row()])
    await commit_infected(session, tenant_id=TENANT, file_id=FILE)
    again = await commit_infected(session, tenant_id=TENANT, file_id=FILE)
    assert again.kind is TransitionKind.NOT_ELIGIBLE
    assert session.actions == ["storage.object.quarantined"]


# --- infected dominates clean --------------------------------------------------


async def test_a_late_infected_overrides_an_earlier_clean() -> None:
    session = FakeSession([row()])
    await commit_clean(session, tenant_id=TENANT, file_id=FILE, evidence=evidence())
    assert session.get()["scan_object_etag"] == "etag-1"
    result = await commit_infected(session, tenant_id=TENANT, file_id=FILE)
    assert result.kind is TransitionKind.APPLIED
    assert result.audited == ("storage.object.quarantined",)
    stored = session.get()
    assert (stored["scan_status"], stored["status"]) == ("infected", "quarantined")
    assert stored["scan_object_etag"] is None and stored["scan_failure"] is None
    assert stored["scan_note"] == transition_module.NOTE_INFECTED
    assert session.actions == ["storage.object.scanned", "storage.object.quarantined"]
    event = session.audit_rows[-1]
    assert (event["outcome"], event["classification"]) == ("denied", "security")
    assert event["details"] == '{"scan_status": "infected", "overrode_clean": true}'
    assert session.commits == 2  # each verdict is its own single commit


async def test_a_clean_row_is_not_touched_by_attempts_failures_or_a_second_clean() -> None:
    session = FakeSession([row(scan_status="clean", scan_object_etag="etag-1")])
    snapshot = dict(session.get())
    results = [
        await attempt(session),
        await record_failure(
            session, tenant_id=TENANT, file_id=FILE, failure=ScanFailure.SCAN_TIMEOUT
        ),
        await commit_clean(session, tenant_id=TENANT, file_id=FILE, evidence=evidence()),
    ]
    assert {r.kind for r in results} == {TransitionKind.NOT_ELIGIBLE}
    assert session.get() == snapshot and session.audit_rows == [] and session.writes == 0


def test_only_the_infected_statements_carry_the_widened_guard() -> None:
    """The fake picks its guard by statement identity; this pins the real SQL text."""

    def sql(statement: Any) -> str:
        return " ".join(str(statement).split())

    wide = "status = 'ready' and scan_status in ('pending', 'clean')"
    narrow = "status = 'ready' and scan_status = 'pending'"
    for widened in (transition_module._LOCK_INFECTED, transition_module._INFECTED):
        assert wide in sql(widened) and "tenant_id = cast(:tenant_id" in sql(widened)
    for pending_only in (
        transition_module._LOCK,
        transition_module._ATTEMPT,
        transition_module._FAILURE,
        transition_module._CLEAN,
    ):
        assert narrow in sql(pending_only) and "'clean')" not in sql(pending_only)


async def test_a_clean_after_that_override_cannot_undo_it() -> None:
    session = FakeSession([row(scan_status="clean", scan_object_etag="etag-1")])
    await commit_infected(session, tenant_id=TENANT, file_id=FILE)
    snapshot = dict(session.get())
    late = await commit_clean(session, tenant_id=TENANT, file_id=FILE, evidence=evidence())
    assert late.kind is TransitionKind.NOT_ELIGIBLE
    assert session.get() == snapshot


async def test_a_duplicate_infected_after_the_override_is_a_no_op() -> None:
    session = FakeSession([row(scan_status="clean", scan_object_etag="etag-1")])
    assert (await commit_infected(session, tenant_id=TENANT, file_id=FILE)).kind is (
        TransitionKind.APPLIED
    )
    snapshot, commits = dict(session.get()), session.commits
    again = await commit_infected(session, tenant_id=TENANT, file_id=FILE)
    assert again.kind is TransitionKind.NOT_ELIGIBLE
    assert session.get() == snapshot
    assert session.actions == ["storage.object.quarantined"]  # exactly one event
    assert session.commits == commits


@pytest.mark.parametrize(
    "state",
    [
        {"scan_status": "skipped"},
        {"scan_status": "clean", "status": "pending"},
        {"scan_status": "clean", "status": "quarantined"},
        {"scan_status": "clean", "status": "archived"},
        {"scan_status": "clean", "status": "deleted"},
        {"scan_status": "clean", "status": "purged"},
    ],
)
async def test_infected_does_not_reopen_any_other_state(state: dict[str, str]) -> None:
    """The override is `clean -> infected` only: no generalised reopening."""
    session = FakeSession([row(**state)])
    snapshot = dict(session.get())
    result = await commit_infected(session, tenant_id=TENANT, file_id=FILE)
    assert result.kind is TransitionKind.NOT_ELIGIBLE
    assert session.get() == snapshot and session.audit_rows == []


async def test_a_late_infected_for_another_tenants_clean_file_is_refused() -> None:
    session = FakeSession(
        [row(id=OTHER_FILE, tenant_id=OTHER_TENANT, scan_status="clean", scan_object_etag="e")]
    )
    snapshot = dict(session.get(OTHER_FILE))
    result = await commit_infected(session, tenant_id=TENANT, file_id=OTHER_FILE)
    assert result.kind is TransitionKind.NOT_ELIGIBLE
    assert session.get(OTHER_FILE) == snapshot and session.audit_rows == []


async def test_a_failed_audit_on_the_override_leaves_the_file_clean() -> None:
    """The override too: no quarantine without its SECURITY event."""
    session = FakeSession(
        [row(scan_status="clean", scan_object_etag="etag-1")], fail_audit_insert=True
    )
    with pytest.raises(RuntimeError):
        await commit_infected(session, tenant_id=TENANT, file_id=FILE)
    stored = session.get()
    assert (stored["scan_status"], stored["status"], stored["scan_object_etag"]) == (
        "clean",
        "ready",
        "etag-1",
    )
    assert session.audit_rows == [] and session.rollbacks >= 1


# --- commit_clean -----------------------------------------------------------------


async def test_clean_is_written_with_the_etag_and_one_scanned_event() -> None:
    session = FakeSession([row(scan_failure="scan_timeout", scan_attempts=2)])
    result = await commit_clean(session, tenant_id=TENANT, file_id=FILE, evidence=evidence())
    assert result.kind is TransitionKind.APPLIED and result.audited == ("storage.object.scanned",)
    stored = session.get()
    assert (stored["scan_status"], stored["status"]) == ("clean", "ready")
    assert stored["scan_object_etag"] == "etag-1" and stored["scan_failure"] is None
    assert stored["scan_note"] == transition_module.NOTE_CLEAN
    event = session.audit_rows[0]
    assert (event["outcome"], event["classification"]) == ("ok", "audit")
    assert event["details"] == '{"scan_status": "clean"}'
    assert session.commits == 1


async def test_a_second_clean_is_a_no_op_with_no_second_event() -> None:
    session = FakeSession([row()])
    await commit_clean(session, tenant_id=TENANT, file_id=FILE, evidence=evidence())
    again = await commit_clean(
        session,
        tenant_id=TENANT,
        file_id=FILE,
        evidence=evidence(
            object_check=ObjectCheck(ObjectGate.READY, identity=identity(9, etag="other"))
        ),
    )
    assert again.kind is TransitionKind.NOT_ELIGIBLE
    assert session.get()["scan_object_etag"] == "etag-1"
    assert session.actions == ["storage.object.scanned"]


async def test_clean_refuses_an_object_with_no_etag_and_records_why() -> None:
    no_etag = ObjectCheck(ObjectGate.READY, identity=identity(100, etag=None, version_id="v1"))
    session = FakeSession([row()])
    result = await commit_clean(
        session, tenant_id=TENANT, file_id=FILE, evidence=evidence(object_check=no_etag)
    )
    assert (
        result.kind is TransitionKind.HELD and result.failure is ScanFailure.IDENTITY_INSUFFICIENT
    )
    stored = session.get()
    assert (stored["scan_status"], stored["scan_object_etag"]) == ("pending", None)
    assert stored["scan_failure"] == "identity_insufficient"
    assert session.actions == ["storage.object.scan_failed"]
    # Repeating it is the same class: no second event.
    again = await commit_clean(
        session, tenant_id=TENANT, file_id=FILE, evidence=evidence(object_check=no_etag)
    )
    assert again.kind is TransitionKind.HELD and again.audited == ()
    assert session.actions == ["storage.object.scan_failed"]


async def test_a_corroborated_digest_must_match_the_one_computed_in_the_stream() -> None:
    corroborated = row(checksum_sha256=DIGEST, checksum_verified_at=NOW)
    for supplied in (OTHER_DIGEST, None):
        session = FakeSession([dict(corroborated)])
        result = await commit_clean(
            session,
            tenant_id=TENANT,
            file_id=FILE,
            evidence=evidence(content_sha256=supplied),
        )
        assert result.kind is TransitionKind.HELD
        assert result.failure is ScanFailure.INTEGRITY_MISMATCH
        stored = session.get()
        assert (stored["scan_status"], stored["scan_failure"]) == ("pending", "integrity_mismatch")
        assert stored["scan_object_etag"] is None

    session = FakeSession([dict(corroborated)])
    ok = await commit_clean(
        session, tenant_id=TENANT, file_id=FILE, evidence=evidence(content_sha256=DIGEST)
    )
    assert ok.kind is TransitionKind.APPLIED and session.get()["scan_status"] == "clean"


async def test_an_unverified_digest_claim_is_not_compared_at_all() -> None:
    """`checksum_verified_at` null means the digest is a client's claim; it is ignored."""
    for supplied in (None, OTHER_DIGEST):
        session = FakeSession([row(checksum_sha256=DIGEST, checksum_verified_at=None)])
        result = await commit_clean(
            session, tenant_id=TENANT, file_id=FILE, evidence=evidence(content_sha256=supplied)
        )
        assert result.kind is TransitionKind.APPLIED


async def test_the_etag_is_never_taken_for_the_digest() -> None:
    """An ETag that equals the row's digest is still not evidence of the content."""
    session = FakeSession([row(checksum_sha256=DIGEST, checksum_verified_at=NOW)])
    lookalike = ObjectCheck(ObjectGate.READY, identity=identity(100, etag=DIGEST))
    result = await commit_clean(
        session, tenant_id=TENANT, file_id=FILE, evidence=evidence(object_check=lookalike)
    )
    assert result.kind is TransitionKind.HELD
    assert result.failure is ScanFailure.INTEGRITY_MISMATCH
    sql = (SCANNING_DIR / "transition.py").read_text("utf-8")
    code = re.sub(r'""".*?"""', "", sql, flags=re.S)
    assert not re.search(r"etag[^\n]*checksum_sha256|checksum_sha256[^\n]*etag", code)


async def test_clean_without_the_audit_sink_is_refused_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(transition_module, "_audit_module", lambda: None)
    session = FakeSession([row()])
    with pytest.raises(TransitionUnavailable):
        await commit_clean(session, tenant_id=TENANT, file_id=FILE, evidence=evidence())
    assert session.writes == 0 and session.get()["scan_status"] == "pending"


# --- the guard: what is not pending and ready is never touched --------------------


@pytest.mark.parametrize(
    "state",
    [
        {"scan_status": "infected", "status": "quarantined"},
        {"scan_status": "skipped"},
        {"status": "pending"},
        {"status": "quarantined"},
        {"status": "archived"},
        {"status": "deleted"},
        {"status": "purged"},
    ],
)
async def test_no_operation_touches_a_row_that_is_not_pending_and_ready(
    state: dict[str, str],
) -> None:
    session = FakeSession([row(**state)])
    snapshot = dict(session.get())
    results = [
        await attempt(session),
        await record_failure(
            session, tenant_id=TENANT, file_id=FILE, failure=ScanFailure.SCAN_TIMEOUT
        ),
        await commit_infected(session, tenant_id=TENANT, file_id=FILE),
        await commit_clean(session, tenant_id=TENANT, file_id=FILE, evidence=evidence()),
    ]
    assert {r.kind for r in results} == {TransitionKind.NOT_ELIGIBLE}
    assert session.get() == snapshot
    assert session.writes == 0 and session.audit_rows == []


async def test_another_tenants_file_is_not_found_by_any_operation() -> None:
    """A payload naming tenant B's file under tenant A finds no row and writes nothing."""
    session = FakeSession([row(id=OTHER_FILE, tenant_id=OTHER_TENANT)])
    snapshot = dict(session.get(OTHER_FILE))
    results = [
        await attempt(session, file=OTHER_FILE),
        await record_failure(
            session, tenant_id=TENANT, file_id=OTHER_FILE, failure=ScanFailure.SCAN_TIMEOUT
        ),
        await commit_infected(session, tenant_id=TENANT, file_id=OTHER_FILE),
        await commit_clean(
            session, tenant_id=TENANT, file_id=OTHER_FILE, evidence=evidence(file_id=OTHER_FILE)
        ),
    ]
    assert {r.kind for r in results} == {TransitionKind.NOT_ELIGIBLE}
    assert session.get(OTHER_FILE) == snapshot and session.audit_rows == []


async def test_an_unknown_file_is_not_eligible() -> None:
    session = FakeSession([row()])
    assert (await attempt(session, file=OTHER_FILE)).kind is TransitionKind.NOT_ELIGIBLE


@pytest.mark.parametrize(
    "bad",
    ["", "not-a-uuid", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", FILE.replace("-", ""), FILE + " "],
)
async def test_identifiers_must_be_canonical_uuids(bad: str) -> None:
    session = FakeSession([row()])
    with pytest.raises(ValueError):
        await attempt(session, file=bad)
    with pytest.raises(ValueError):
        await attempt(session, tenant=bad)
    assert session.writes == 0 and session.commits == 0


# --- one transaction: state and audit stand or fall together ----------------------


async def test_a_failed_audit_write_leaves_the_state_unchanged() -> None:
    for call in (
        lambda s: commit_infected(s, tenant_id=TENANT, file_id=FILE),
        lambda s: commit_clean(s, tenant_id=TENANT, file_id=FILE, evidence=evidence()),
        lambda s: record_failure(
            s, tenant_id=TENANT, file_id=FILE, failure=ScanFailure.SCANNER_ERROR
        ),
    ):
        session = FakeSession([row()], fail_audit_insert=True)
        with pytest.raises(RuntimeError):
            await call(session)
        stored = session.get()
        assert (stored["scan_status"], stored["status"], stored["scan_failure"]) == (
            "pending",
            "ready",
            None,
        )
        assert session.audit_rows == [] and session.rollbacks >= 1


async def test_a_failed_exhaustion_event_does_not_count_the_attempt() -> None:
    session = FakeSession([row(scan_attempts=2)], fail_audit_insert=True)
    with pytest.raises(RuntimeError):
        await attempt(session, maximum=3)
    assert session.get()["scan_attempts"] == 2


async def test_a_failed_update_is_rolled_back_and_raised() -> None:
    session = FakeSession([row()], fail_update=True)
    with pytest.raises(RuntimeError):
        await commit_infected(session, tenant_id=TENANT, file_id=FILE)
    assert session.get()["scan_status"] == "pending" and session.rollbacks >= 1


async def test_a_refused_call_leaves_no_transaction_open() -> None:
    session = FakeSession([row(scan_status="clean")])
    await attempt(session)
    assert session.rollbacks == 1 and session.tenant is None


async def test_every_operation_binds_its_own_tenant_and_does_not_rely_on_the_caller() -> None:
    session = FakeSession([row()])
    assert session.tenant is None
    await record_failure(session, tenant_id=TENANT, file_id=FILE, failure=ScanFailure.SCAN_TIMEOUT)
    assert session.get()["scan_failure"] == "scan_timeout"
    # The sink committed, which drops the binding; the next call binds it again.
    assert session.tenant is None
    assert (await attempt(session)).kind is TransitionKind.APPLIED


# --- a full lifecycle -------------------------------------------------------------


async def test_a_lifecycle_through_an_outage_to_clean() -> None:
    session = FakeSession([row()])
    for _ in range(3):
        await attempt(session, maximum=3)
        await record_failure(
            session, tenant_id=TENANT, file_id=FILE, failure=ScanFailure.SCANNER_UNAVAILABLE
        )
    assert session.actions == [
        "storage.object.scan_failed",
        "storage.object.scan_exhausted",
    ]
    assert session.get()["scan_status"] == "pending"
    await attempt(session, maximum=3)
    done = await commit_clean(session, tenant_id=TENANT, file_id=FILE, evidence=evidence())
    assert done.kind is TransitionKind.APPLIED
    stored = session.get()
    assert (stored["scan_status"], stored["scan_failure"], stored["scan_attempts"]) == (
        "clean",
        None,
        4,
    )
    assert session.actions[-1] == "storage.object.scanned"
    assert session.actions.count("storage.object.scanned") == 1


# --- audit registration, settings and static properties ---------------------------


@pytest.mark.parametrize(
    ("key", "classification"),
    [
        ("storage.object.scanned", Classification.AUDIT),
        ("storage.object.scan_failed", Classification.AUDIT),
        ("storage.object.scan_exhausted", Classification.SECURITY),
        ("storage.object.quarantined", Classification.SECURITY),
    ],
)
def test_the_scan_audit_actions_are_registered_with_their_classes(
    key: str, classification: Classification
) -> None:
    from koras_api.core import audit  # noqa: F401 - registers on import

    assert actions.classification_of(key) is classification


def test_the_actions_not_to_be_registered_are_not() -> None:
    from koras_api.core import audit  # noqa: F401

    for key in ("storage.object.scan_skipped", "storage.object.rescan_requested"):
        assert key not in actions


def test_the_module_writes_no_signature_filename_or_scanner_text() -> None:
    source = (SCANNING_DIR / "transition.py").read_text("utf-8")
    code = re.sub(r'""".*?"""', "", source, flags=re.S)
    code = re.sub(r"#.*", "", code)
    for forbidden in ("filename", "signature_name", "raw_reply", "skipped"):
        assert forbidden not in code


def test_only_the_transition_module_writes_a_scan_status() -> None:
    for path in SCANNING_DIR.glob("*.py"):
        if path.name == "transition.py":
            continue
        assert "update public.files" not in path.read_text("utf-8"), path.name


def test_the_threshold_setting_defaults_to_twelve_and_is_bounded() -> None:
    assert ScannerSettings().file_scan_max_attempts == 12
    for bad in (0, MAX_RECORDED_ATTEMPTS + 1):
        with pytest.raises(ValueError):
            ScannerSettings(file_scan_max_attempts=bad)
    assert ScannerSettings(file_scan_max_attempts=MAX_RECORDED_ATTEMPTS)


def test_the_s4_surface_is_exported_and_a_default_worker_registers_nothing() -> None:
    for name in ("begin_attempt", "record_failure", "commit_infected", "commit_clean"):
        assert name in scanning.__all__
    worker_tasks = (
        REPO / "services" / "worker" / "koras_worker" / "tasks" / "product.py"
    ).read_text("utf-8")
    assert "scanning" not in worker_tasks


def test_nothing_in_the_worker_or_the_api_calls_the_transitions_yet() -> None:
    callers = []
    for base in (
        REPO / "services" / "worker" / "koras_worker",
        REPO / "services" / "api" / "koras_api",
    ):
        for path in base.rglob("*.py"):
            if path.parts[-2] == "scanning":
                continue
            text = path.read_text("utf-8")
            if re.search(r"\b(begin_attempt|commit_clean|commit_infected)\b", text):
                callers.append(str(path))
    assert callers == []


# --- evidence is bound to its file, its size and the provider's digest -------------


async def test_evidence_for_another_file_or_tenant_cannot_release_this_one() -> None:
    session = FakeSession([row(), row(id=OTHER_FILE)])
    for mispaired in (evidence(file_id=OTHER_FILE), evidence(tenant_id=OTHER_TENANT)):
        with pytest.raises(ValueError, match="not gathered for this file"):
            await commit_clean(session, tenant_id=TENANT, file_id=FILE, evidence=mispaired)
    assert session.writes == 0 and session.get()["scan_status"] == "pending"


def test_evidence_ids_must_be_canonical_uuids() -> None:
    with pytest.raises(ValueError):
        evidence(file_id="not-a-uuid")


async def test_an_object_of_another_size_than_the_row_is_held_as_changed() -> None:
    session = FakeSession([row(size_bytes=101)])
    result = await commit_clean(session, tenant_id=TENANT, file_id=FILE, evidence=evidence())
    assert (result.kind, result.failure) == (TransitionKind.HELD, ScanFailure.OBJECT_CHANGED)
    assert (session.get()["scan_status"], session.get()["scan_object_etag"]) == ("pending", None)


async def test_a_stream_digest_that_disagrees_with_the_providers_is_held() -> None:
    check = ObjectCheck(ObjectGate.READY, identity=identity(100, provider_sha256=DIGEST))
    session = FakeSession([row()])
    result = await commit_clean(
        session,
        tenant_id=TENANT,
        file_id=FILE,
        evidence=evidence(object_check=check, content_sha256=OTHER_DIGEST),
    )
    assert (result.kind, result.failure) == (TransitionKind.HELD, ScanFailure.INTEGRITY_MISMATCH)
    agree = await commit_clean(
        session,
        tenant_id=TENANT,
        file_id=FILE,
        evidence=evidence(object_check=check, content_sha256=DIGEST),
    )
    assert agree.kind is TransitionKind.APPLIED


def test_only_a_missing_module_is_treated_as_a_missing_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(name: str) -> None:
        raise RuntimeError("a defect inside the sink module")

    monkeypatch.setattr(transition_module.importlib, "import_module", broken)
    with pytest.raises(RuntimeError):
        transition_module._audit_module()

    def missing(name: str) -> None:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(transition_module.importlib, "import_module", missing)
    assert transition_module._audit_module() is None
