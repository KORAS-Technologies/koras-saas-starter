"""What a scan can conclude, and nothing a scanner said beyond that.

**There is no `clean` here, and that is the point.** A scanner answering `OK`
produces `CANDIDATE_CLEAN`: no known signature was found in what the engine
looked at. It is not a release. A file becomes `clean`
only when the candidate *and* the product's structural-safety checks pass,
because ClamAV may answer `OK` for a deflated, streamed ZIP64 entry without
inspecting its payload. Nothing in this module can say a file is releasable;
`requires_structural_gate` is true for the one outcome that could lead there,
and the gate that composes it is `release.assess_release`.

**Raw scanner text stops at the client.** The client parses a reply into one of
these outcomes and discards it. A signature name is classified and dropped: it
is not stored on the result, not logged by this package, and cannot reach the
database.

**Every outcome that is not an `INFECTED` or a `CANDIDATE_CLEAN` is a hold.** A
hold leaves the file `pending`. Nothing here converts a failure into a pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ScanOutcome(StrEnum):
    """The closed set of things a scan attempt can come to."""

    #: The engine found no known signature. A candidate, never a release.
    CANDIDATE_CLEAN = "candidate_clean"
    #: A signature matched.
    INFECTED = "infected"
    #: Could not reach the scanner, or it hung up without answering.
    UNAVAILABLE = "unavailable"
    #: The per-file wall clock ran out.
    TIMEOUT = "timeout"
    #: The reply was not one of the shapes the protocol defines.
    MALFORMED_RESPONSE = "malformed_response"
    #: The scanner answered `ERROR` for a reason other than a limit.
    SCANNER_ERROR = "scanner_error"
    #: The object is larger than the ceiling, or the scanner said a limit was hit.
    LIMIT_EXCEEDED = "limit_exceeded"
    #: The scanner said it could not inspect the whole object: encrypted,
    #: unsupported or incomplete. Not a detection, and not a pass.
    INCOMPLETE_INSPECTION = "incomplete_inspection"
    #: The object could not be read, so there was nothing to scan.
    READ_FAILURE = "read_failure"
    #: The scanner is not usable in this environment or configuration. Never clean.
    MISCONFIGURED = "misconfigured"


class IncompleteKind(StrEnum):
    """Why an inspection was incomplete, for `INCOMPLETE_INSPECTION` only."""

    ENCRYPTED = "encrypted"
    UNSUPPORTED = "unsupported"
    INCOMPLETE = "incomplete"


class ScanFailure(StrEnum):
    """The closed set persisted as `files.scan_failure` (migrations 00039 and 00040).

    A held file needs a reason the sweep can tell apart from an outage, so the set has a
    word for "the scanner reported a limit" and for "the scanner could not inspect it" as
    well as for the faults. `identity_insufficient` is the store giving too little to tell one
    object from a replacement, which is not "unreachable". The upload finalizer writes the
    same column with the same words (`uploads/finalize.py`).
    """

    SCANNER_UNAVAILABLE = "scanner_unavailable"
    SCAN_TIMEOUT = "scan_timeout"
    MALFORMED_RESPONSE = "malformed_response"
    SCANNER_ERROR = "scanner_error"
    OBJECT_UNREACHABLE = "object_unreachable"
    MISCONFIGURED = "misconfigured"
    SCAN_LIMIT_EXCEEDED = "scan_limit_exceeded"
    INSPECTION_INCOMPLETE = "inspection_incomplete"
    OBJECT_CHANGED = "object_changed"
    OVER_CEILING = "over_ceiling"
    IDENTITY_INSUFFICIENT = "identity_insufficient"
    #: A provider-corroborated digest did not match the one computed during the
    #: stream. In the `CHECK` of migration 00039.
    INTEGRITY_MISMATCH = "integrity_mismatch"
    #: A counted attempt that the worker or the queue cut short before the run
    #: reached an assessment (migration 00040). Not the scanner's own
    #: deadline, which is `scan_timeout`; the file stays `pending` for the sweep.
    SCAN_INTERRUPTED = "scan_interrupted"


class Disposition(StrEnum):
    """What the release assessment does with a result. Deliberately has no `CLEAN`."""

    #: Run the structural gate; only candidate plus a passing gate is `clean`.
    CANDIDATE_CLEAN = "candidate_clean"
    #: Quarantine.
    INFECTED = "infected"
    #: Hold `pending`; the cause is operational and a retry can change it.
    HOLD_RETRY = "hold_retry"
    #: Hold `pending`; retrying the same bytes cannot change the answer.
    HOLD_UNINSPECTABLE = "hold_uninspectable"


_FAILURE: dict[ScanOutcome, ScanFailure] = {
    ScanOutcome.UNAVAILABLE: ScanFailure.SCANNER_UNAVAILABLE,
    ScanOutcome.TIMEOUT: ScanFailure.SCAN_TIMEOUT,
    ScanOutcome.MALFORMED_RESPONSE: ScanFailure.MALFORMED_RESPONSE,
    ScanOutcome.SCANNER_ERROR: ScanFailure.SCANNER_ERROR,
    ScanOutcome.LIMIT_EXCEEDED: ScanFailure.SCAN_LIMIT_EXCEEDED,
    ScanOutcome.INCOMPLETE_INSPECTION: ScanFailure.INSPECTION_INCOMPLETE,
    ScanOutcome.READ_FAILURE: ScanFailure.OBJECT_UNREACHABLE,
    ScanOutcome.MISCONFIGURED: ScanFailure.MISCONFIGURED,
}

_UNINSPECTABLE = frozenset({ScanOutcome.LIMIT_EXCEEDED, ScanOutcome.INCOMPLETE_INSPECTION})


@dataclass(frozen=True, slots=True)
class ScanResult:
    """One scan attempt's conclusion. Carries no scanner text."""

    outcome: ScanOutcome
    incomplete_kind: IncompleteKind | None = None
    #: Bytes handed to the scanner. Diagnostic only; a count, not content.
    bytes_sent: int = 0

    def __post_init__(self) -> None:
        if (self.incomplete_kind is not None) != (
            self.outcome is ScanOutcome.INCOMPLETE_INSPECTION
        ):
            raise ValueError("incomplete_kind belongs to INCOMPLETE_INSPECTION and only to it")

    @property
    def candidate_clean(self) -> bool:
        """True for the engine's `OK`. It is not a release; see the module."""
        return self.outcome is ScanOutcome.CANDIDATE_CLEAN

    @property
    def requires_structural_gate(self) -> bool:
        """Whether a later slice must still pass the structural gate.

        True for the only outcome that could end as `clean`, so the rule that
        `OK` alone is never enough is a property of the result, not a
        convention a consumer has to remember.
        """
        return self.candidate_clean

    @property
    def failure(self) -> ScanFailure | None:
        """The `scan_failure` class for a hold; `None` for a verdict."""
        return _FAILURE.get(self.outcome)

    @property
    def disposition(self) -> Disposition:
        if self.outcome is ScanOutcome.CANDIDATE_CLEAN:
            return Disposition.CANDIDATE_CLEAN
        if self.outcome is ScanOutcome.INFECTED:
            return Disposition.INFECTED
        if self.outcome in _UNINSPECTABLE:
            return Disposition.HOLD_UNINSPECTABLE
        return Disposition.HOLD_RETRY
