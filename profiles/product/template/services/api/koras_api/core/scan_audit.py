"""The audit actions the scanner records (ADR 0013, `secure_files`).

A capability's actions are registered by that capability's own module, so a product
generated without `secure_files` has neither the actions nor this file. The worker reaches
this module by name from `koras_worker.scanning.transition`, because the sink it writes
through only accepts an action somebody registered.

`storage.object.quarantined` is the foundation's own action and is written by the scanner's
infected transition as well.
"""

from __future__ import annotations

from koras_audit import AuditAction, Classification, actions

OBJECT_SCANNED = "storage.object.scanned"
OBJECT_SCAN_FAILED = "storage.object.scan_failed"
OBJECT_SCAN_EXHAUSTED = "storage.object.scan_exhausted"

SCAN_ACTIONS = (
    AuditAction(
        key=OBJECT_SCANNED,
        classification=Classification.AUDIT,
        summary=(
            "A scan found no known signature in this exact object and every required check "
            "passed."
        ),
    ),
    AuditAction(
        key=OBJECT_SCAN_FAILED,
        classification=Classification.AUDIT,
        summary=(
            "A file could not obtain a releasable scan result. Written when a "
            "failure begins or its class changes, not once per attempt."
        ),
    ),
    AuditAction(
        key=OBJECT_SCAN_EXHAUSTED,
        classification=Classification.SECURITY,
        summary=(
            "The operational retry threshold was reached and a person should look. "
            "The file stays pending and stays in the sweep; it is never released."
        ),
    ),
)

actions.extend(SCAN_ACTIONS)
