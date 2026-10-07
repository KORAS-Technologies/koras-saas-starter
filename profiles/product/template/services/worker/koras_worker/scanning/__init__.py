"""The malware-scanner runtime (ADR 0013, `secure_files`).

A contract, a ClamAV client, configuration and a result model, a bounded object reader with
the upload-window gate, the guarded transitions out of `pending`, the stream SHA-256, the
structural and integrity gates and the internal release assessment, and `runtime.scan_file`,
which composes them for one file and is what the `file.scan` task runs.

**A scanner `OK` is a candidate, not a release.** The result model has no `clean`; a
candidate becomes a verdict only through a `CLEAN_ELIGIBLE` assessment, which also needs the
object gate, the integrity gate and the structural gate. The verdict is `commit_clean`'s
write to the file's row, and the release rule every consumer goes through reads it.

Two things enqueue `file.scan`: the upload finalizer, after a file reaches its final key,
and the reconciliation sweep (`tasks/scan_sweep.py`), which is always on in a product with
the capability.
"""

from .clamd import ClamdScanner, parse_reply
from .config import (
    MAX_SCAN_BYTES,
    ScannerConfigurationError,
    ScannerSettings,
    UnavailableScanner,
    resolve_scanner,
)
from .objects import (
    Admission,
    ObjectChanged,
    ObjectCheck,
    ObjectGate,
    ObjectIdentity,
    ObjectOversized,
    ObjectReader,
    ObjectReference,
    ObjectReferenceError,
    ObjectSource,
    ObjectSourceError,
    ObjectStream,
    UploadWindowUnavailable,
    earliest_read,
)
from .protocol import ObjectReadError, Scanner
from .release import (
    IntegrityBasis,
    IntegrityOutcome,
    IntegrityResult,
    ReleaseAssessment,
    ReleaseOutcome,
    RowIntegrity,
    assess_integrity,
    assess_release,
)
from .result import (
    Disposition,
    IncompleteKind,
    ScanFailure,
    ScanOutcome,
    ScanResult,
)
from .runtime import ScanDisposition, ScanRun, scan_file
from .structure import (
    ContainerKind,
    ContainerProbe,
    StructuralOutcome,
    StructuralReason,
    StructuralResult,
    inspect_container,
)
from .transition import (
    CleanEvidence,
    TransitionKind,
    TransitionResult,
    TransitionUnavailable,
    begin_attempt,
    commit_clean,
    commit_infected,
    record_failure,
)

__all__ = [
    "ContainerKind",
    "ContainerProbe",
    "IntegrityBasis",
    "IntegrityOutcome",
    "IntegrityResult",
    "ReleaseAssessment",
    "ReleaseOutcome",
    "RowIntegrity",
    "ScanDisposition",
    "ScanRun",
    "scan_file",
    "StructuralOutcome",
    "StructuralReason",
    "StructuralResult",
    "assess_integrity",
    "assess_release",
    "inspect_container",
    "MAX_SCAN_BYTES",
    "Admission",
    "CleanEvidence",
    "ClamdScanner",
    "Disposition",
    "IncompleteKind",
    "ObjectChanged",
    "ObjectCheck",
    "ObjectGate",
    "ObjectIdentity",
    "ObjectOversized",
    "ObjectReadError",
    "ObjectReader",
    "ObjectReference",
    "ObjectReferenceError",
    "ObjectSource",
    "ObjectSourceError",
    "ObjectStream",
    "ScanFailure",
    "ScanOutcome",
    "ScanResult",
    "Scanner",
    "ScannerConfigurationError",
    "ScannerSettings",
    "TransitionKind",
    "TransitionResult",
    "TransitionUnavailable",
    "UnavailableScanner",
    "UploadWindowUnavailable",
    "begin_attempt",
    "commit_clean",
    "commit_infected",
    "earliest_read",
    "parse_reply",
    "record_failure",
    "resolve_scanner",
]
