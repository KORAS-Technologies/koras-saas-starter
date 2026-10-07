"""The audit action the release gate records (ADR 0013, `secure_files`).

A capability's actions are registered by that capability's own module, so a product
generated without `secure_files` has neither the action nor this file. The gate imports
it, which is what makes the action known to the sink before the gate writes one.

`storage.object.quarantined` is the foundation's own action and is what the gate records
for a file that is infected or quarantined; this one is for a file that simply has no
clean verdict (yet, or ever).
"""

from __future__ import annotations

from koras_audit import AuditAction, Classification, actions

OBJECT_RELEASE_REFUSED = "storage.object.release_refused"

RELEASE_ACTIONS = (
    AuditAction(
        key=OBJECT_RELEASE_REFUSED,
        classification=Classification.SECURITY,
        summary=(
            "A file's content was not released: it has no clean verdict for this exact object "
            "(pending, skipped, not recognised, or an identity that does not match). Infected "
            "files are recorded as storage.object.quarantined. Names a closed reason and the "
            "consumer, never a file name, a key or anything the scanner said."
        ),
    ),
)

actions.extend(RELEASE_ACTIONS)
