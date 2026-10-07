"""Write one audit event on the caller's session, through the registered sink.

The sink takes the action's classification from the registry, never from the caller, and its
`flush` writes the row and commits **once**: so a swap executed on the same session earlier
commits with its event or not at all. Reached by name, because the worker does not depend on
the API package. `koras_api.core.upload_audit` is imported for its side effect: it registers
the finalization actions, and the sink refuses an action nobody registered.
"""

from __future__ import annotations

import importlib
from typing import Any

from koras_audit import AuditEvent, Outcome

ACTOR = "system"


async def emit_and_commit(
    session: Any,  # noqa: ANN401 - the caller's session, holding the change to commit
    *,
    tenant_id: str,
    action: str,
    file_id: str,
    outcome: Outcome = "ok",
    **details: str | int | bool,
) -> None:
    importlib.import_module("koras_api.core.upload_audit")
    audit = importlib.import_module("koras_api.core.audit")
    sink = audit.SqlAuditSink(session, tenant_id)
    sink.emit(
        AuditEvent(
            action=action,
            actor_id=ACTOR,
            tenant_id=tenant_id,
            target_type="file",
            target_id=file_id,
            outcome=outcome,
            details=details,
        )
    )
    await sink.flush()
