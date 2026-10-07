"""One `file.scan` run: orchestration only.

    object gate  ->  scanner  ->  release assessment  ->  guarded transition

This module **composes** those four and decides nothing they decide. It holds no
security rule: the upload window, the ceiling, identity, the digest, the
structural gate and the composition of all of them into `CLEAN_ELIGIBLE` are
`ObjectReader`, the `Scanner`, `assess_release` and the transitions. What is
here is the order they are called in, which branch of the assessment calls which
transition, and nothing that writes a column: **there is no `update`, `insert` or
`delete` in this file**, and a static test holds that. The single statement is a
read of the row, because the object key, the declared type, the size and the
digests have to come from somewhere, and they must come from the tenant's own row
and not from a job.

**Nothing here enqueues anything.** Two things put a `file.scan` job on the queue: the
upload finalizer, once a file is on its final key (`tasks/finalize.py`), and the
reconciliation sweep (`tasks/scan_sweep.py`). This module is the same one a job reaches
either way.

**Interruption.** Once the attempt is counted, a cancellation of the run --
the queue's job timeout, a worker shutting down -- records `scan_interrupted`
(shielded, best effort) and propagates. The file stays `pending` and the attempt
stays counted. `scan_interrupted` is the weakest label there is, so it is written
only to a file that carries no failure: a more specific one, from this run or an
earlier one, is never replaced (the check is under the row lock, in the transition).

**Only a final key is scanned.** A row whose key is an *incoming* key is one a signed PUT
could still write; a row on any other shape was not written by the finalizer. Neither is
ever read, scanned or released: the run is `NOT_ELIGIBLE` and nothing is read, counted,
written or released. Finalization is its own job (`uploads/finalize.py`); a file reaches
here only after it has copied the object to a key no ticket was signed for, hashed both
copies to the claim and swapped the row to it. `commit_clean` additionally refuses a verdict
unless the row still references the key that was scanned, and never on an incoming key.

**The order, and why each step is where it is.**

1. *Read the row* as the tenant, requiring `ready` and `pending`, under forced
   RLS and with the tenant named in the predicate. A file that is not this
   tenant's, does not exist, or has left `pending` is `NOT_ELIGIBLE` and nothing
   else happens: a duplicate, a stale job and another tenant's file id all end
   here. The read is rolled back before any transition, because each transition
   binds the tenant itself and commits or rolls back what it is given. A row whose key
   is not a final key ends here too, with no read and no attempt.
2. *Admit* (the object gate). The upload window is judged before the store is touched. A
   window that has not elapsed **defers**: nothing is read, nothing is counted,
   nothing is written. An oversized object is held (`over_ceiling`) without an
   attempt, because retrying cannot change the answer.
3. *Count the attempt* (`begin_attempt`), before the object is read, so a
   crash still counts it. Every admission failure other than those two counts,
   as `ObjectGate.counts_attempt` says.
4. *Scan* the one bounded stream. The same read feeds the digest and the
   structural probe.
5. *Verify* the object's identity again, and *assess* (`assess_release`).
6. *Transition*, by the assessment and by nothing else:

   | Assessment | Call |
   |---|---|
   | `INFECTED` | `commit_infected` |
   | `CLEAN_ELIGIBLE` | `commit_clean`, with the evidence the assessment builds |
   | `HELD` | `record_failure`, with the assessment's own failure class |

   `commit_clean` can still refuse on the row's own evidence and say `HELD`; that
   is reported as a hold. A scanner `OK` is never an input to `commit_clean`
   except through `ReleaseAssessment.clean_evidence`, which refuses anything but
   an eligible assessment.

**Which hold is recorded.** `ReleaseAssessment.failure` names the first failing
gate in the order object, scanner, integrity, structure. One case needs the order
read the other way, and it is not a gate: when the scanner never took the stream
(unavailable, misconfigured, timed out) the object gate reports an incomplete
read, which would label a scanner outage `object_unreachable`. When the stream
neither failed nor finished, the object did nothing wrong, and the scanner's own
class is recorded instead. It changes which closed-vocabulary label a hold
carries and never whether there is one.

**Nothing here can release a file by failing.** Every exception from a
dependency becomes a hold or propagates; none becomes a pass. A scanner that
raises is a `scanner_error`. An exception from a transition propagates and the
file stays `pending`, which is what the sweep selects.

**No scanner text reaches a log line.** Log lines name the tenant, the file and
a closed-vocabulary class, as the transitions do.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import text

from .objects import Admission, ObjectGate, ObjectReader, ObjectReference, ObjectReferenceError
from .protocol import Scanner
from .release import ReleaseAssessment, ReleaseOutcome, RowIntegrity, assess_release
from .result import ScanFailure, ScanOutcome, ScanResult
from .transition import (
    TransitionKind,
    begin_attempt,
    commit_clean,
    commit_infected,
    record_failure,
)

logger = logging.getLogger(__name__)

_AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)

#: The only statement in this module, and a read. The tenant is in the predicate
#: as well as enforced by RLS, so the answer does not depend on the session
#: having been bound correctly. No `for update`: the transitions take the lock.
_ROW = text(
    "select storage_key, content_type, created_at, size_bytes, checksum_sha256, "
    "checksum_verified_at "
    "from public.files "
    "where id = cast(:file_id as uuid) and tenant_id = cast(:tenant_id as uuid) "
    "and status = 'ready' and scan_status = 'pending'"
)

class ScanDisposition(StrEnum):
    """What one run did. Only `CLEAN` and `INFECTED` moved a file out of `pending`."""

    #: `commit_clean` applied, on a `CLEAN_ELIGIBLE` assessment.
    CLEAN = "clean"
    #: `commit_infected` applied; the file is quarantined.
    INFECTED = "infected"
    #: The file stays `pending`, with a recorded reason (or one already recorded).
    HELD = "held"
    #: The upload window has not elapsed. Nothing was read, counted or written.
    DEFERRED = "deferred"
    #: No pending, ready file of this tenant, or it left that state during the run.
    #: Nothing was written by this branch.
    NOT_ELIGIBLE = "not_eligible"


@dataclass(frozen=True, slots=True)
class ScanRun:
    disposition: ScanDisposition
    #: The failure class the file now carries, for a hold.
    failure: ScanFailure | None = None
    #: `scan_attempts` after this run's own attempt, when it counted one.
    attempts: int | None = None
    #: When the window opens, for a deferral.
    opens_at: datetime | None = None
    #: The audit actions committed with the change.
    audited: tuple[str, ...] = ()


def _is_final(key: str) -> bool:
    """Whether this is a key the finalizer wrote, by the one module that states the shape."""
    window = importlib.import_module("koras_api.core.upload_window")
    return bool(window.is_final_key(key))


def _canonical(value: str, what: str) -> str:
    try:
        if str(uuid.UUID(value)) == value:
            return value
    except (ValueError, AttributeError, TypeError):
        pass
    raise ValueError(f"{what} must be a canonical UUID")


async def _fail(
    session: Any,  # noqa: ANN401 - the caller's open session
    tenant_id: str,
    file_id: str,
    failure: ScanFailure,
    attempts: int | None,
) -> ScanRun:
    recorded = await record_failure(session, tenant_id=tenant_id, file_id=file_id, failure=failure)
    if recorded.kind is TransitionKind.NOT_ELIGIBLE:
        return ScanRun(ScanDisposition.NOT_ELIGIBLE)
    return ScanRun(
        ScanDisposition.HELD, failure=failure, attempts=attempts, audited=recorded.audited
    )


def _hold_failure(
    assessment: ReleaseAssessment, *, stream_failed: bool, stream_completed: bool
) -> ScanFailure:
    """The class a hold records; see the module on the one case read the other way."""
    result = assessment.scan_result
    if not stream_failed and not stream_completed and result.failure is not None:
        return result.failure
    return assessment.failure or ScanFailure.INSPECTION_INCOMPLETE


async def scan_file(
    session: Any,  # noqa: ANN401 - an open session with no uncommitted work
    *,
    tenant_id: str,
    file_id: str,
    reader: ObjectReader,
    scanner: Scanner,
    max_attempts: int,
    now: datetime,
) -> ScanRun:
    """Run one scan of one file, as the tenant, through the four existing layers.

    `max_attempts` is `FILE_SCAN_MAX_ATTEMPTS`, handed to `begin_attempt`
    unchanged; it must be the same on every worker (see `transition.py`).
    """
    _canonical(tenant_id, "tenant_id")
    _canonical(file_id, "file_id")

    row = await _read_row(session, tenant_id, file_id)
    if row is None:
        return ScanRun(ScanDisposition.NOT_ELIGIBLE)

    # Only a key the finalizer wrote is scanned. An incoming key is one a signed PUT could
    # still write; any other shape was not written by the finalizer (a ticket was never
    # signed for it in this product, so it is server-written by something that must say so
    # before it may be scanned). Held: no read, no attempt, no verdict, no write.
    if not _is_final(str(row["storage_key"])):
        logger.warning(
            "scan: file %s of tenant %s is not on a final key; not scanned", file_id, tenant_id
        )
        return ScanRun(ScanDisposition.NOT_ELIGIBLE)

    # An object key that does not belong to this tenant and file is a row the
    # reader refuses to name. It is held as unreachable, never read. This is an
    # integrity hold on the row itself and does not wait for the upload window:
    # no object is touched, so the window protects nothing here.
    try:
        ref = ObjectReference(tenant_id, file_id, str(row["storage_key"]))
    except ObjectReferenceError:
        logger.error("scan: file %s of tenant %s has no readable object key", file_id, tenant_id)
        started = await begin_attempt(
            session, tenant_id=tenant_id, file_id=file_id, now=now, max_attempts=max_attempts
        )
        if started.kind is TransitionKind.NOT_ELIGIBLE:
            return ScanRun(ScanDisposition.NOT_ELIGIBLE)
        return await _fail(
            session, tenant_id, file_id, ScanFailure.OBJECT_UNREACHABLE, started.attempts
        )

    admission = await reader.admit(ref, row["created_at"], expected_size=row["size_bytes"])
    if admission.gate is ObjectGate.WINDOW_NOT_ELAPSED:
        return ScanRun(ScanDisposition.DEFERRED, opens_at=admission.opens_at)
    if admission.gate is ObjectGate.OVERSIZED:
        return await _fail(session, tenant_id, file_id, ScanFailure.OVER_CEILING, None)

    started = await begin_attempt(
        session, tenant_id=tenant_id, file_id=file_id, now=now, max_attempts=max_attempts
    )
    if started.kind is TransitionKind.NOT_ELIGIBLE:
        return ScanRun(ScanDisposition.NOT_ELIGIBLE)
    attempts = started.attempts

    # From here the attempt is counted. A cancellation (the queue's timeout, a
    # worker shutting down) is recorded as `scan_interrupted` and propagates.
    try:
        return await _scan_counted_attempt(
            session,
            tenant_id=tenant_id,
            file_id=file_id,
            ref=ref,
            row=row,
            admission=admission,
            reader=reader,
            scanner=scanner,
            attempts=attempts,
        )
    except asyncio.CancelledError:
        await _record_interrupted(session, tenant_id, file_id)
        raise


async def _read_row(
    session: Any,  # noqa: ANN401
    tenant_id: str,
    file_id: str,
) -> dict[str, Any] | None:
    """The row as the tenant, ready and pending, or nothing. A read, rolled back."""
    try:
        await session.execute(_AS_TENANT, {"tenant_id": tenant_id})
        found = (
            (await session.execute(_ROW, {"tenant_id": tenant_id, "file_id": file_id}))
            .mappings()
            .first()
        )
        row = dict(found) if found is not None else None
        # A read only. Ending it here leaves the session with no uncommitted
        # work, which is what each transition requires.
        await session.rollback()
    except BaseException:
        await session.rollback()
        raise
    return row


async def _record_interrupted(
    session: Any,  # noqa: ANN401 - the caller's open session
    tenant_id: str,
    file_id: str,
) -> None:
    """Record `scan_interrupted` for a counted attempt that was cancelled.

    Shielded, so a second cancellation cannot abandon the write half done, and
    never raising: the caller is already propagating a cancellation and must go
    on doing so. The session may be mid-transaction, so it is rolled back first.
    If the verdict itself committed before the cancellation landed, the file has
    left `pending` and `record_failure` finds nothing to write. A worker killed
    outright (SIGKILL, a lost machine) records nothing; the attempt was counted
    before the read and the file is still `pending`, which is what the sweep
    selects.
    """

    async def write() -> None:
        await session.rollback()
        await record_failure(
            session,
            tenant_id=tenant_id,
            file_id=file_id,
            failure=ScanFailure.SCAN_INTERRUPTED,
            # Only the best label there is: never over a failure that is already
            # recorded, whether this run established it just before the cancellation
            # or an earlier attempt did.
            keep_existing=True,
        )

    inner = asyncio.ensure_future(write())
    # Retrieved even if the caller is cancelled again and never awaits it.
    inner.add_done_callback(lambda done: done.cancelled() or done.exception())
    try:
        await asyncio.shield(inner)
    except (Exception, asyncio.CancelledError) as error:  # noqa: BLE001 - never replace the cancellation in flight
        logger.error(
            "scan: could not record the interruption of file %s: %s",
            file_id,
            type(error).__name__,
        )


async def _scan_counted_attempt(
    session: Any,  # noqa: ANN401
    *,
    tenant_id: str,
    file_id: str,
    ref: ObjectReference,
    row: dict[str, Any],
    admission: Admission,
    reader: ObjectReader,
    scanner: Scanner,
    attempts: int | None,
) -> ScanRun:
    if not admission.ready:
        failure = admission.gate.failure or ScanFailure.OBJECT_UNREACHABLE
        return await _fail(session, tenant_id, file_id, failure, attempts)

    stream = reader.stream(ref, admission)
    try:
        result = await scanner.scan(stream)
    except Exception as error:  # noqa: BLE001 - a scanner that raises is a hold, never a pass
        logger.error("scan: the scanner raised %s for file %s", type(error).__name__, file_id)
        result = ScanResult(ScanOutcome.SCANNER_ERROR)
    check = await reader.verify(ref, admission, stream)
    assessment = assess_release(
        object_check=check,
        scan_result=result,
        content_type=str(row["content_type"]) if row["content_type"] is not None else None,
        row=RowIntegrity.from_row(row),
    )

    if assessment.outcome is ReleaseOutcome.INFECTED:
        applied = await commit_infected(session, tenant_id=tenant_id, file_id=file_id)
        if applied.kind is TransitionKind.APPLIED:
            return ScanRun(ScanDisposition.INFECTED, attempts=attempts, audited=applied.audited)
        return ScanRun(ScanDisposition.NOT_ELIGIBLE, attempts=attempts)

    if assessment.outcome is ReleaseOutcome.CLEAN_ELIGIBLE:
        released = await commit_clean(
            session,
            tenant_id=tenant_id,
            file_id=file_id,
            evidence=assessment.clean_evidence(
                tenant_id=tenant_id, file_id=file_id, storage_key=ref.key
            ),
        )
        if released.kind is TransitionKind.APPLIED:
            return ScanRun(ScanDisposition.CLEAN, attempts=attempts, audited=released.audited)
        if released.kind is TransitionKind.HELD:
            return ScanRun(
                ScanDisposition.HELD,
                failure=released.failure,
                attempts=attempts,
                audited=released.audited,
            )
        return ScanRun(ScanDisposition.NOT_ELIGIBLE, attempts=attempts)

    failure = _hold_failure(
        assessment, stream_failed=stream.failure is not None, stream_completed=stream.completed
    )
    return await _fail(session, tenant_id, file_id, failure, attempts)
