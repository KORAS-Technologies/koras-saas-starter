"""The audit actions upload finalization records (ADR 0013, `secure_files`).

A capability's actions are registered by that capability's own module, so a
product generated without `secure_files` has neither the actions nor this file.
The worker reaches this module by name (`koras_worker.uploads._audit`), because
the sink it writes through only accepts an action somebody registered.
"""

from __future__ import annotations

from koras_audit import AuditAction, Classification, actions

UPLOAD_FINALIZED = "storage.upload.finalized"
UPLOAD_HELD = "storage.upload.held"

UPLOAD_ACTIONS = (
    AuditAction(
        key=UPLOAD_FINALIZED,
        classification=Classification.AUDIT,
        summary=(
            "An upload was copied to a final key no ticket was signed for. `corroborated` "
            "means this process hashed both the incoming and the final bytes to the SHA-256 "
            "the upload was authorized for and found the ticket's own upload id on the object."
        ),
    ),
    AuditAction(
        key=UPLOAD_HELD,
        classification=Classification.SECURITY,
        summary=(
            "An upload was not finalized and stays on its incoming key, which nothing "
            "releases. `reason` is the closed word recorded on the file."
        ),
    ),
)

actions.extend(UPLOAD_ACTIONS)
