"""The internal release-eligibility assessment.

The canonical rule, and the only one:

    object gate PASS
    + scanner result CANDIDATE_CLEAN
    + integrity gate PASS (or explicitly not applicable)
    + structural gate PASS (or explicitly not required)
    = CLEAN_ELIGIBLE

`CLEAN_ELIGIBLE` is an **internal** answer. This module does not call
`commit_clean`, does not touch a session, writes no row and emits no audit
event; the one thing it can hand the caller is a `CleanEvidence`, which is
the type `commit_clean` already requires. A scanner's `OK` is a candidate and is
never enough alone: it composes here, or it does not release.

**Infected dominates.** A scanner `FOUND` is `INFECTED` whatever the other gates
say, including when the object changed during the scan, because quarantine is
the safe direction. It is never `CLEAN_ELIGIBLE`.

**The assessment cannot be forged.** `ReleaseAssessment` stores its inputs and
*computes* the outcome from them; there is no field to set. Its inputs are the
results the gates produced, and the structural gate and the digest both come off
the object check, so they describe the same stream the scanner read.

**The integrity gate.** Three kinds of digest evidence exist, and they are not
equal (`checksum_verified_at` is the row's own statement of which is which):

- the provider's own SHA-256 for the object (`ObjectIdentity.provider_sha256`):
  authoritative; it must equal the stream digest;
- the row's `checksum_sha256` with `checksum_verified_at` set (set by the upload
  finalizer, which hashed the incoming and the final bytes itself): authoritative; it
  must equal the stream digest, and its absence is a hold;
- the row's `checksum_sha256` with no `checksum_verified_at` (a claim nothing has
  verified): not authoritative, so it cannot verify anything, but a claim the bytes
  contradict is a hold;
- none of the above: `NOT_APPLICABLE`. An uploaded file never arrives here without a
  verified claim (the finalizer is the only writer of a final key); a file some other
  server path wrote has none, and the scanner's own digest is then the only one.

An ETag is **never** consulted as a digest. `NOT_APPLICABLE` is an explicit
outcome with its own name, never a missing check treated as a pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .objects import ObjectCheck
from .result import ScanFailure, ScanOutcome, ScanResult
from .structure import (
    StructuralOutcome,
    StructuralReason,
    StructuralResult,
    inspect_container,
)
from .transition import CleanEvidence

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


# --- integrity ----------------------------------------------------------------------


class IntegrityOutcome(StrEnum):
    #: At least one authoritative digest matched the stream digest and none differed.
    VERIFIED = "verified"
    #: A digest, authoritative or claimed, differs from the stream digest.
    MISMATCH = "mismatch"
    #: Evidence the row or the provider says exists could not be compared: the
    #: stream produced no digest, or a corroborated digest is absent or not a digest.
    EVIDENCE_MISSING = "evidence_missing"
    #: No digest of any kind exists, and the upload contract does not require one.
    NOT_APPLICABLE = "not_applicable"

    @property
    def passed(self) -> bool:
        return self in {IntegrityOutcome.VERIFIED, IntegrityOutcome.NOT_APPLICABLE}


class IntegrityBasis(StrEnum):
    """What the comparison rested on. Informational; `PROVIDER` outranks `ROW_CORROBORATED`."""

    PROVIDER = "provider"
    ROW_CORROBORATED = "row_corroborated"
    CLAIM_ONLY = "claim_only"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class RowIntegrity:
    """What the `files` row says about the content digest. Two fields, as the table has them."""

    checksum_sha256: str | None = None
    #: `checksum_verified_at is not None`: a provider corroborated the client's digest.
    checksum_verified: bool = False

    @classmethod
    def from_row(cls, row: dict[str, object]) -> RowIntegrity:
        """Build from the columns `files` has. Missing columns read as no evidence."""
        digest = row.get("checksum_sha256")
        return cls(
            checksum_sha256=str(digest).lower() if digest else None,
            checksum_verified=row.get("checksum_verified_at") is not None,
        )


@dataclass(frozen=True, slots=True)
class IntegrityResult:
    outcome: IntegrityOutcome
    basis: IntegrityBasis = IntegrityBasis.NONE

    @property
    def passed(self) -> bool:
        return self.outcome.passed

    @property
    def failure(self) -> ScanFailure | None:
        """Both holds map to `integrity_mismatch`, as `commit_clean` already does."""
        return None if self.passed else ScanFailure.INTEGRITY_MISMATCH


def assess_integrity(object_check: ObjectCheck, row: RowIntegrity) -> IntegrityResult:
    """Compare the digest computed during the stream with every digest that exists.

    Consults only the stream digest, the provider's digest on the verified
    identity and the row's two checksum columns. It never reads an ETag.
    """
    provider = (
        object_check.identity.provider_sha256.lower()
        if object_check.identity is not None and object_check.identity.provider_sha256
        else None
    )
    stream = object_check.content_sha256
    claimed = row.checksum_sha256.lower() if row.checksum_sha256 else None

    expects_authoritative = provider is not None or row.checksum_verified
    if stream is None or not _SHA256.match(stream):
        # No digest of the bytes: fine only if nothing was owed a comparison.
        if expects_authoritative or claimed is not None:
            return IntegrityResult(IntegrityOutcome.EVIDENCE_MISSING)
        return IntegrityResult(IntegrityOutcome.NOT_APPLICABLE)

    if provider is not None and not _SHA256.match(provider):
        return IntegrityResult(IntegrityOutcome.EVIDENCE_MISSING, IntegrityBasis.PROVIDER)
    if row.checksum_verified and (claimed is None or not _SHA256.match(claimed)):
        return IntegrityResult(IntegrityOutcome.EVIDENCE_MISSING, IntegrityBasis.ROW_CORROBORATED)
    if claimed is not None and not _SHA256.match(claimed):
        return IntegrityResult(IntegrityOutcome.MISMATCH, IntegrityBasis.CLAIM_ONLY)

    if provider is not None and provider != stream:
        return IntegrityResult(IntegrityOutcome.MISMATCH, IntegrityBasis.PROVIDER)
    if claimed is not None and claimed != stream:
        basis = (
            IntegrityBasis.ROW_CORROBORATED if row.checksum_verified else IntegrityBasis.CLAIM_ONLY
        )
        return IntegrityResult(IntegrityOutcome.MISMATCH, basis)

    if provider is not None:
        return IntegrityResult(IntegrityOutcome.VERIFIED, IntegrityBasis.PROVIDER)
    if row.checksum_verified:
        return IntegrityResult(IntegrityOutcome.VERIFIED, IntegrityBasis.ROW_CORROBORATED)
    if claimed is not None:
        # The client's claim agrees with the bytes. It vouches for nothing.
        return IntegrityResult(IntegrityOutcome.NOT_APPLICABLE, IntegrityBasis.CLAIM_ONLY)
    return IntegrityResult(IntegrityOutcome.NOT_APPLICABLE)


# --- composition --------------------------------------------------------------------


class ReleaseOutcome(StrEnum):
    #: Every applicable gate passed. Internal only: nothing is written because of it.
    CLEAN_ELIGIBLE = "clean_eligible"
    #: A signature matched. Dominates every other gate.
    INFECTED = "infected"
    #: Not eligible; the file stays `pending`.
    HELD = "held"


@dataclass(frozen=True, slots=True)
class ReleaseAssessment:
    """The four gates, side by side, and the one answer they compose to.

    Build it with `assess_release`. The outcome is computed, never stored.
    """

    object_check: ObjectCheck
    scan_result: ScanResult
    integrity: IntegrityResult
    #: `None` only when the object gate failed, so there are no bytes to inspect.
    structural: StructuralResult | None

    @property
    def outcome(self) -> ReleaseOutcome:
        if self.scan_result.outcome is ScanOutcome.INFECTED:
            return ReleaseOutcome.INFECTED
        if (
            self.object_check.passed
            and self.scan_result.candidate_clean
            and self.integrity.passed
            and self.structural is not None
            and self.structural.passed
        ):
            return ReleaseOutcome.CLEAN_ELIGIBLE
        return ReleaseOutcome.HELD

    @property
    def eligible(self) -> bool:
        return self.outcome is ReleaseOutcome.CLEAN_ELIGIBLE

    @property
    def failure(self) -> ScanFailure | None:
        """The existing `scan_failure` class for the first hold, in gate order.

        `None` for an eligible or infected result. Order: object, scanner,
        integrity, structure. No class here is new; see `structure.py`.
        """
        if self.outcome is not ReleaseOutcome.HELD:
            return None
        if not self.object_check.passed:
            return self.object_check.gate.failure
        if not self.scan_result.candidate_clean:
            return self.scan_result.failure
        if not self.integrity.passed:
            return self.integrity.failure
        if self.structural is None:
            return ScanFailure.INSPECTION_INCOMPLETE
        return self.structural.failure

    def clean_evidence(self, *, tenant_id: str, file_id: str, storage_key: str) -> CleanEvidence:
        """The proof `commit_clean` takes, for an eligible assessment and no other.

        This builds a value. It writes nothing and does not call `commit_clean`.
        """
        if not self.eligible:
            raise ValueError("only a clean-eligible assessment can become clean evidence")
        return CleanEvidence(
            tenant_id=tenant_id,
            file_id=file_id,
            storage_key=storage_key,
            object_check=self.object_check,
            scan_result=self.scan_result,
            structural_gate_passed=True,
            content_sha256=self.object_check.content_sha256,
        )


def assess_release(
    *,
    object_check: ObjectCheck,
    scan_result: ScanResult,
    content_type: str | None,
    row: RowIntegrity,
) -> ReleaseAssessment:
    """Run the integrity and structural gates and compose all four.

    `content_type` is the file row's declared type, the structural gate's only
    input besides the bytes. The structural gate runs only when the object gate
    passed: without a verified, complete read there is nothing to inspect, and a
    probe over a partial stream must not be able to pass.
    """
    integrity = assess_integrity(object_check, row)
    structural: StructuralResult | None = None
    if object_check.passed and object_check.probe is not None:
        structural = inspect_container(object_check.probe, content_type)
    elif object_check.passed:
        structural = StructuralResult(
            StructuralOutcome.INCOMPLETE_INSPECTION, StructuralReason.PROBE_UNAVAILABLE
        )
    return ReleaseAssessment(
        object_check=object_check,
        scan_result=scan_result,
        integrity=integrity,
        structural=structural,
    )
