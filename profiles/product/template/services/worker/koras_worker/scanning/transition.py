"""The guarded transitions out of `pending`.

**One caller:** `runtime.scan_file`, run by the `file.scan` task. No hook, sweep or route
reaches it.

This is the only module that is meant to write `files.scan_status` from a scan
(a static test holds that). It is a guarded wrapper and not an edit of the legacy
`core/file_scan.record_scan`, which writes unconditionally and cannot be made safe by a
caller's care; the worker never calls it.

**Every operation is one transaction, in this order:** bind the tenant, then
`select ... for update` the row **where `scan_status = 'pending'` and
`status = 'ready'`**, then write, then commit. A row that is not in that state,
or is not this tenant's, or does not exist, is `NOT_ELIGIBLE` and nothing is
written. So a late or duplicate result cannot move `infected -> clean`, cannot
overwrite a quarantine, and a payload naming another tenant's file finds no row.
**The one exception:** `commit_infected` also accepts a `clean` row, so a
later authoritative infected verdict is not lost to an earlier clean commit.
Two concurrent calls on one file queue on the row lock; the second sees what the
first committed.

**State and audit commit together.** The audit sink writes its rows on the same
session and commits once, so a verdict cannot exist without its event or the
reverse. (The starter's `record_scan` commits the status and then audits.)

**The operations, and the only things they can do to a row**

| Operation | `scan_status` | `status` | Other columns |
|---|---|---|---|
| `begin_attempt` | stays `pending` | unchanged | `scan_attempts` +1 (saturating), time |
| `record_failure` | stays `pending` | unchanged | `scan_failure` |
| `commit_infected` | `infected` (from `pending`, `clean`) | `quarantined` | failure, ETag cleared |
| `commit_clean` | `clean` | unchanged | `scan_object_etag`, `scan_failure` cleared, fixed note |

**`clean` takes proof, not a flag.** `CleanEvidence` cannot be constructed unless
the object gate passed, the scanner said candidate-clean and the structural gate
passed; and `commit_clean` additionally refuses an object
with no ETag to bind the verdict to, and a digest that does not match a
provider-corroborated one. **No structural gate exists yet**, so nothing can
honestly construct the evidence outside a test; that is deliberate.

**Caller contract.** Each operation commits or rolls back the session it is
given, so pass one with no other uncommitted work. Each binds the tenant itself
and the commit ends that binding: a caller's own query between operations must
bind it again, or it sees no rows under RLS. A cancelled task may leave a commit
of unknown outcome; every operation is safe to retry (an attempt may over-count,
never under-count). `FILE_SCAN_MAX_ATTEMPTS` must be the same on every worker,
or `scan_exhausted` can be written twice, or never, for one file.

**An ETag is identity evidence only.** It is stored in `scan_object_etag` and is
never compared with `checksum_sha256`. The only digest comparison is the SHA-256
the caller computed during the stream against the row's `checksum_sha256`, and
only when `checksum_verified_at` is set.

**No scanner text, signature name or filename** reaches a column, a log line or
an audit detail. Notes are fixed sentences; audit details are a closed
vocabulary, a count and a boolean.
"""

from __future__ import annotations

import importlib
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import ModuleType
from typing import Any

from koras_audit import AuditEvent
from sqlalchemy import text

from .config import MAX_RECORDED_ATTEMPTS
from .objects import ObjectCheck
from .result import ScanFailure, ScanResult

logger = logging.getLogger(__name__)

ACTOR = "system"

SCANNED = "storage.object.scanned"
SCAN_FAILED = "storage.object.scan_failed"
SCAN_EXHAUSTED = "storage.object.scan_exhausted"
QUARANTINED = "storage.object.quarantined"

#: Fixed sentences. The scanner's own words are never stored (`record_scan`).
NOTE_CLEAN = "No known signature was found by this engine in this object."
NOTE_INFECTED = "A scan found a known signature; the file is withheld."

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)

#: The guard. `tenant_id` is named in the predicate as well as enforced by RLS,
#: so the answer does not depend on the session having been bound correctly.
_LOCK = text(
    "select scan_attempts, scan_failure, checksum_sha256, checksum_verified_at, size_bytes, "
    "storage_key "
    "from public.files "
    "where id = cast(:file_id as uuid) and tenant_id = cast(:tenant_id as uuid) "
    "and status = 'ready' and scan_status = 'pending' "
    "for update"
)
#: The one wider guard: a verdict of `infected` may also act on a `clean`
#: row. `skipped`, `infected` and every non-`ready` status stay ineligible.
_LOCK_INFECTED = text(
    "select scan_status from public.files "
    "where id = cast(:file_id as uuid) and tenant_id = cast(:tenant_id as uuid) "
    "and status = 'ready' and scan_status in ('pending', 'clean') "
    "for update"
)
_ATTEMPT = text(
    "update public.files "
    "set scan_attempts = least(scan_attempts + 1, :ceiling), scan_attempted_at = :now "
    "where id = cast(:file_id as uuid) and tenant_id = cast(:tenant_id as uuid) "
    "and status = 'ready' and scan_status = 'pending' "
    "returning scan_attempts"
)
_FAILURE = text(
    "update public.files set scan_failure = :failure "
    "where id = cast(:file_id as uuid) and tenant_id = cast(:tenant_id as uuid) "
    "and status = 'ready' and scan_status = 'pending'"
)
_INFECTED = text(
    "update public.files set scan_status = 'infected', status = 'quarantined', "
    "scan_note = :note, scan_failure = null, scan_object_etag = null "
    "where id = cast(:file_id as uuid) and tenant_id = cast(:tenant_id as uuid) "
    "and status = 'ready' and scan_status in ('pending', 'clean')"
)
_CLEAN = text(
    "update public.files set scan_status = 'clean', scan_note = :note, "
    "scan_failure = null, scan_object_etag = :etag "
    "where id = cast(:file_id as uuid) and tenant_id = cast(:tenant_id as uuid) "
    "and status = 'ready' and scan_status = 'pending'"
)


class TransitionKind(StrEnum):
    """What a call did. A release is `APPLIED` on `commit_clean`, and nothing else."""

    #: The row moved (or the counter advanced) and the event, if any, committed with it.
    APPLIED = "applied"
    #: The row already says this; nothing was written.
    UNCHANGED = "unchanged"
    #: No such pending, ready row for this tenant. Nothing was written. Covers a
    #: late duplicate, an already-final file, another tenant's file and no file.
    NOT_ELIGIBLE = "not_eligible"
    #: `commit_clean` refused on the row's own evidence and recorded `failure`
    #: instead. The file is still `pending`.
    HELD = "held"


@dataclass(frozen=True, slots=True)
class TransitionResult:
    kind: TransitionKind
    #: `scan_attempts` after the call, for `begin_attempt`.
    attempts: int | None = None
    #: The failure class the row now carries, for a hold.
    failure: ScanFailure | None = None
    #: The audit actions committed with the change, in order.
    audited: tuple[str, ...] = ()


class TransitionUnavailable(RuntimeError):
    """The audit sink is not on this worker's path, so a change that needs it was not made."""


@dataclass(frozen=True, slots=True)
class CleanEvidence:
    """Everything `clean` requires, checked when it is built.

    Not a flag a caller can set to get a verdict: constructing it with any of
    the three conditions missing raises. The digest is the SHA-256 the caller
    computed over the bytes it streamed to the scanner, as lowercase hex; it is
    only consulted when the row's own digest was provider-corroborated.
    """

    #: The file this evidence was gathered for. `commit_clean` refuses evidence
    #: for any other file or tenant, so a stale or mispaired value cannot
    #: release a different file.
    tenant_id: str
    file_id: str
    #: The key the verdict is about: the one the scanner read. `commit_clean` writes `clean`
    #: only while the row still references exactly this key, so a verdict
    #: about one object can never land on a row that has since moved to another (a restore's
    #: replacement, a finalization), and it is never an incoming key, which a ticket could
    #: still write.
    storage_key: str
    object_check: ObjectCheck
    scan_result: ScanResult
    structural_gate_passed: bool
    content_sha256: str | None = None

    def __post_init__(self) -> None:
        _ids(self.tenant_id, self.file_id)
        if not self.storage_key:
            raise ValueError("clean needs the key the verdict was gathered for")
        if _is_incoming(self.storage_key):
            raise ValueError("clean is never about a key a signed upload could write")
        if not self.object_check.passed or self.object_check.identity is None:
            raise ValueError("clean needs an object gate that passed, with its identity")
        if not self.scan_result.candidate_clean:
            raise ValueError("clean needs a scanner result of candidate-clean")
        if self.structural_gate_passed is not True:
            raise ValueError("clean needs the structural gate to have passed")
        if self.content_sha256 is not None and not _SHA256.match(self.content_sha256):
            raise ValueError("content_sha256 must be 64 lowercase hex characters")


def _is_incoming(key: str) -> bool:
    """Whether a ticket was signed for this key; the one rule is in the shared window module."""
    window = importlib.import_module("koras_api.core.upload_window")
    return bool(window.is_incoming_key(key))


def _ids(tenant_id: str, file_id: str) -> dict[str, str]:
    for value in (tenant_id, file_id):
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError("tenant_id and file_id must be canonical UUIDs")
    return {"tenant_id": tenant_id, "file_id": file_id}


def _audit_module() -> ModuleType | None:
    """The API's sink, reached by name as the import task reaches it. `None` if absent."""
    try:
        # The scanner's actions are registered by their own module; the sink refuses an
        # action nobody registered.
        importlib.import_module("koras_api.core.scan_audit")
        return importlib.import_module("koras_api.core.audit")
    except ImportError:
        logger.error("scan transition: the audit sink is not on this worker's path")
        return None


def _event(
    tenant_id: str, file_id: str, action: str, outcome: str, **details: str | int | bool
) -> AuditEvent:
    return AuditEvent(
        action=action,
        actor_id=ACTOR,
        tenant_id=tenant_id,
        target_type="file",
        target_id=file_id,
        outcome=outcome,  # type: ignore[arg-type]
        details=details,
    )


async def _finish(
    session: Any,  # noqa: ANN401 - the caller's open session
    audit: ModuleType | None,
    tenant_id: str,
    events: list[AuditEvent],
) -> None:
    """Commit the change with its events in one transaction."""
    if events:
        if audit is None:
            raise TransitionUnavailable("the audit sink is required for this change")
        sink = audit.SqlAuditSink(session, tenant_id)
        for event in events:
            sink.emit(event)
        await sink.flush()  # writes the rows and commits once
    else:
        await session.commit()


async def _lock(session: Any, ids: dict[str, str]) -> Any:  # noqa: ANN401
    await session.execute(_AS_TENANT, {"tenant_id": ids["tenant_id"]})
    return (await session.execute(_LOCK, ids)).mappings().first()


def _failure_events(row: Any, ids: dict[str, str], failure: ScanFailure) -> list[AuditEvent]:  # noqa: ANN401
    """One `scan_failed` when a failure begins or its class changes, else none."""
    if row["scan_failure"] == failure.value:
        return []
    return [_event(ids["tenant_id"], ids["file_id"], SCAN_FAILED, "failed", reason=failure.value)]


def _known(value: str) -> ScanFailure | None:
    """The closed-vocabulary class a row carries, or `None` for a value this code does not know."""
    try:
        return ScanFailure(value)
    except ValueError:
        return None


async def begin_attempt(
    session: Any,  # noqa: ANN401 - an open session with no uncommitted work
    *,
    tenant_id: str,
    file_id: str,
    now: datetime,
    max_attempts: int,
) -> TransitionResult:
    """Count one attempt, before the object is read, so a crash still counts it.

    Call it only for an execution that is about to read or scan the object; the
    deferrals the object gate reports (`WINDOW_NOT_ELAPSED`, `OVERSIZED`) are not
    attempts and must not reach here. The counter saturates at the column's
    ceiling and never wraps. The attempt that takes it from below `max_attempts`
    to `max_attempts` writes one `scan_exhausted`, in the same transaction; an
    equal-or-higher previous count cannot write another, so it is once per file.
    It is a signal for a person. The file stays `pending`.
    """
    ids = _ids(tenant_id, file_id)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not 1 <= max_attempts <= MAX_RECORDED_ATTEMPTS:
        raise ValueError("max_attempts is out of range")
    audit = _audit_module()
    try:
        row = await _lock(session, ids)
        if row is None:
            await session.rollback()
            return TransitionResult(TransitionKind.NOT_ELIGIBLE)
        before = int(row["scan_attempts"])
        after = int(
            (
                await session.execute(
                    _ATTEMPT, {**ids, "ceiling": MAX_RECORDED_ATTEMPTS, "now": now}
                )
            ).scalar_one()
        )
        events: list[AuditEvent] = []
        if before < max_attempts <= after:
            events.append(
                _event(
                    tenant_id,
                    file_id,
                    SCAN_EXHAUSTED,
                    "failed",
                    attempts=after,
                    threshold=max_attempts,
                )
            )
        await _finish(session, audit, tenant_id, events)
    except BaseException:
        await session.rollback()
        raise
    return TransitionResult(
        TransitionKind.APPLIED, attempts=after, audited=tuple(e.action for e in events)
    )


async def record_failure(
    session: Any,  # noqa: ANN401
    *,
    tenant_id: str,
    file_id: str,
    failure: ScanFailure,
    keep_existing: bool = False,
) -> TransitionResult:
    """Record why a pending file has no releasable verdict. The file stays `pending`.

    Writes `scan_failed` only when no failure was recorded or the class changed,
    so an outage is one event however many attempts it spans. The same class
    again writes nothing at all.

    `keep_existing` is for a reason that is only the best available label, such as
    `scan_interrupted`: it writes only to a file that carries no failure, decided
    under the row lock, so it can never replace a more specific one that another
    step (or an earlier attempt) established, however the two race. The answer is
    `UNCHANGED` with the class the row actually carries.
    """
    if not isinstance(failure, ScanFailure):
        raise TypeError("failure must be a ScanFailure")
    ids = _ids(tenant_id, file_id)
    audit = _audit_module()
    try:
        row = await _lock(session, ids)
        if row is None:
            await session.rollback()
            return TransitionResult(TransitionKind.NOT_ELIGIBLE)
        if keep_existing and row["scan_failure"] is not None:
            await session.rollback()
            return TransitionResult(TransitionKind.UNCHANGED, failure=_known(row["scan_failure"]))
        events = _failure_events(row, ids, failure)
        if not events:
            await session.rollback()
            return TransitionResult(TransitionKind.UNCHANGED, failure=failure)
        await session.execute(_FAILURE, {**ids, "failure": failure.value})
        await _finish(session, audit, tenant_id, events)
    except BaseException:
        await session.rollback()
        raise
    return TransitionResult(
        TransitionKind.APPLIED, failure=failure, audited=tuple(e.action for e in events)
    )


async def commit_infected(
    session: Any,  # noqa: ANN401
    *,
    tenant_id: str,
    file_id: str,
) -> TransitionResult:
    """Quarantine a file a scanner matched. Reached from `pending` and from `clean`.

    **Infected dominates clean.** A later authoritative infected verdict is
    not discarded because an earlier scan committed clean: `clean -> infected`
    is the one transition out of a final state, and `infected` is never
    overwritten by anything. Whichever of a racing clean and infected takes the
    row lock first, the file ends `infected`/`quarantined` with one quarantine
    event; a duplicate infected finds no `pending`/`clean` row and is a no-op.
    `skipped`, any non-`ready` status and another tenant's file stay ineligible.
    The audit detail carries `overrode_clean` when it replaced a clean verdict,
    and `scan_object_etag` (identity evidence for a verdict that no longer
    holds) is cleared.

    Committed even if the object changed during the scan: quarantine is the safe
    direction, so no identity is asked for. The object is kept. One statement
    sets `scan_status` and `status`, so there is no moment a known-infected file
    is listed as ready. If the audit sink module is missing the call raises
    `TransitionUnavailable` and quarantines nothing (fail-closed). If the sink is present but
    its write fails, the whole transaction rolls back and the exception
    propagates: the file stays as it was (`pending`, or `clean` on an override) and the caller
    retries, so a SECURITY event is never lost silently.
    """
    ids = _ids(tenant_id, file_id)
    audit = _audit_module()
    if audit is None:
        await session.rollback()
        raise TransitionUnavailable("the audit sink is required for this change")
    try:
        await session.execute(_AS_TENANT, {"tenant_id": tenant_id})
        row = (await session.execute(_LOCK_INFECTED, ids)).mappings().first()
        if row is None:
            await session.rollback()
            return TransitionResult(TransitionKind.NOT_ELIGIBLE)
        overrides_clean = row["scan_status"] == "clean"
        await session.execute(_INFECTED, {**ids, "note": NOTE_INFECTED})
        details: dict[str, bool | str] = {"scan_status": "infected"}
        if overrides_clean:
            details["overrode_clean"] = True
        events = [_event(tenant_id, file_id, QUARANTINED, "denied", **details)]
        await _finish(session, audit, tenant_id, events)
    except BaseException:
        await session.rollback()
        raise
    logger.warning("a scan withheld file %s for tenant %s", file_id, tenant_id)
    return TransitionResult(TransitionKind.APPLIED, audited=tuple(e.action for e in events))


async def commit_clean(
    session: Any,  # noqa: ANN401
    *,
    tenant_id: str,
    file_id: str,
    evidence: CleanEvidence,
) -> TransitionResult:
    """Release a file as `clean`. Reached only from `pending`, and only on evidence.

    Refused, and recorded as a hold on the row's own evidence, when:

    - the verified object has no ETag: the verdict could not be bound to one
      object (`identity_insufficient`); or
    - the object's size is not the row's recorded size (`object_changed`); or
    - the stream digest differs from the provider's own SHA-256 for the object
      (`integrity_mismatch`); or
    - the row's digest was provider-corroborated (`checksum_verified_at` set) and
      the digest computed during the stream is absent or different
      (`integrity_mismatch`).

    Otherwise one transaction writes `clean` with the accepted ETag and the
    `scanned` event. The ETag is stored as identity evidence only and is never
    compared with `checksum_sha256`.
    """
    if not isinstance(evidence, CleanEvidence):
        raise TypeError("commit_clean needs CleanEvidence")
    ids = _ids(tenant_id, file_id)
    if (evidence.tenant_id, evidence.file_id) != (tenant_id, file_id):
        raise ValueError("the evidence was not gathered for this file")
    audit = _audit_module()
    if audit is None:
        raise TransitionUnavailable("the audit sink is required for this change")
    identity = evidence.object_check.identity
    assert identity is not None  # CleanEvidence guarantees it  # noqa: S101
    try:
        row = await _lock(session, ids)
        if row is None:
            await session.rollback()
            return TransitionResult(TransitionKind.NOT_ELIGIBLE)
        if row["storage_key"] != evidence.storage_key:
            # The row moved to another object while this one was being scanned. The
            # verdict is about bytes the row no longer names, and says nothing about the
            # ones it does: nothing is written, and the new object is scanned on its own.
            await session.rollback()
            return TransitionResult(TransitionKind.NOT_ELIGIBLE)

        refusal: ScanFailure | None = None
        if not identity.etag:
            refusal = ScanFailure.IDENTITY_INSUFFICIENT
        elif identity.size != row["size_bytes"]:
            refusal = ScanFailure.OBJECT_CHANGED
        elif (
            evidence.content_sha256 is not None
            and identity.provider_sha256 is not None
            and evidence.content_sha256 != identity.provider_sha256.lower()
        ):
            refusal = ScanFailure.INTEGRITY_MISMATCH
        elif row["checksum_verified_at"] is not None and (
            evidence.content_sha256 is None
            or evidence.content_sha256 != str(row["checksum_sha256"] or "").lower()
        ):
            refusal = ScanFailure.INTEGRITY_MISMATCH

        if refusal is not None:
            events = _failure_events(row, ids, refusal)
            if events:
                await session.execute(_FAILURE, {**ids, "failure": refusal.value})
                await _finish(session, audit, tenant_id, events)
            else:
                await session.rollback()
            return TransitionResult(
                TransitionKind.HELD, failure=refusal, audited=tuple(e.action for e in events)
            )

        await session.execute(_CLEAN, {**ids, "note": NOTE_CLEAN, "etag": identity.etag})
        events = [_event(tenant_id, file_id, SCANNED, "ok", scan_status="clean")]
        await _finish(session, audit, tenant_id, events)
    except BaseException:
        await session.rollback()
        raise
    return TransitionResult(TransitionKind.APPLIED, audited=(SCANNED,))
