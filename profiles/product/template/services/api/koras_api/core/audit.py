"""The durable audit sink, on `audit_events`, for every module that records.

This is foundation rather than a capability. The table it writes to is
generated into every product, so storage, tenancy and anything added later
can record without depending on reporting being switched on -- which is what
the sink's previous home in `core/reporting.py` quietly required. A general
audit table that an unrelated capability can remove is not somewhere another
module can safely record.

The envelope, the outcome vocabulary and the rule that a detail may not be
named after a credential all come from `koras_audit`; nothing is redefined
here. What this module adds is the write: buffered until the route flushes,
refused for another tenant, and committed on the tenant session with row-level
security forced.
"""

from __future__ import annotations

import json

from koras_audit import AuditAction, AuditEvent, Classification, Outcome, actions
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .database import rebind_tenant

_AUDIT_INSERT = text(
    "insert into public.audit_events "
    " (tenant_id, actor_id, action, target_type, target_id, outcome, details, "
    "  classification, created_at) "
    "values (:tenant_id, :actor_id, :action, :target_type, :target_id, :outcome, "
    " cast(:details as jsonb), :classification, :created_at)"
)

# ── the actions this build can record ─────────────────────────────────────────
#
# Declared here rather than discovered from the strings passed at call sites, so
# that the class an action is kept under is a property of the action. A product
# adds its own with `actions.add(...)` at import; a duplicate key is refused
# where it is a traceback.
#
# Storage is foundation, so its actions are registered unconditionally. A
# capability's actions are registered by that capability's own module.

STORAGE_ACTIONS = (
    AuditAction(
        key="storage.object.uploaded",
        classification=Classification.AUDIT,
        summary="A file was stored and confirmed present in the bucket.",
    ),
    AuditAction(
        key="storage.object.downloaded",
        classification=Classification.ACTIVITY,
        summary="A signed download URL was issued for a file.",
    ),
    AuditAction(
        key="storage.object.deleted",
        classification=Classification.AUDIT,
        summary="A file and its object were removed.",
    ),
    AuditAction(
        key="storage.object.delete_refused",
        classification=Classification.SECURITY,
        summary="A deletion was refused: the caller lacked the role.",
    ),
    AuditAction(
        key="storage.object.quarantined",
        classification=Classification.SECURITY,
        summary="A file was withheld: a scan did not find it clean.",
    ),
    AuditAction(
        key="storage.upload.refused",
        classification=Classification.SECURITY,
        summary="An upload was refused by the plan or the quota.",
    ),
    AuditAction(
        key="storage.upload.failed",
        classification=Classification.AUDIT,
        summary="An upload was announced and did not arrive as promised.",
    ),
    AuditAction(
        key="storage.reconcile.orphan_found",
        classification=Classification.AUDIT,
        summary="The sweep found an object without a row, or a row without an object.",
    ),
    AuditAction(
        key="storage.object.purged",
        classification=Classification.AUDIT,
        summary="A file passed its retention and was removed.",
    ),
    AuditAction(
        key="storage.purge.held",
        classification=Classification.SECURITY,
        summary="A file was due for purge and was kept: a legal hold covers it.",
    ),
)

# Holds are administrative: they change what the system will do rather than
# what it holds. Refusals among them are security, because a refused lift is
# somebody trying to make a purge possible again.
HOLD_ACTIONS = (
    AuditAction(
        key="hold.requested",
        classification=Classification.ADMINISTRATIVE,
        summary="A legal hold was requested. It holds nothing until approved.",
    ),
    AuditAction(
        key="hold.approved",
        classification=Classification.ADMINISTRATIVE,
        summary="A legal hold was approved and is now active.",
    ),
    AuditAction(
        key="hold.released",
        classification=Classification.ADMINISTRATIVE,
        summary="A legal hold was lifted; what it covered may expire again.",
    ),
    AuditAction(
        key="hold.refused",
        classification=Classification.SECURITY,
        summary="A hold transition was refused: the caller lacked the authority.",
    ),
    AuditAction(
        key="audit.searched",
        classification=Classification.ACTIVITY,
        summary="A tenant's own audit history was read.",
    ),
    AuditAction(
        key="audit.exported",
        classification=Classification.AUDIT,
        summary="An export was requested; a copy of the records leaves the product.",
    ),
    AuditAction(
        key="audit.export_downloaded",
        classification=Classification.AUDIT,
        summary="A finished audit export was fetched.",
    ),
    AuditAction(
        key="retention.changed",
        classification=Classification.ADMINISTRATIVE,
        summary="A tenant changed how long it keeps records.",
    ),
)

actions.extend(STORAGE_ACTIONS)
actions.extend(HOLD_ACTIONS)


async def record(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str,
    action: str,
    target_type: str,
    target_id: str,
    outcome: Outcome,
    details: dict[str, str | int | bool] | None = None,
) -> None:
    """Record one event and flush it, for a caller with nothing to batch.

    Most routes emit several events and flush once; a route that emits one
    should not have to know that. Both go through the same sink, so both get
    the cross-tenant refusal and the rebinding after the commit.
    """
    sink = SqlAuditSink(session, tenant_id)
    sink.emit(
        AuditEvent(
            action=action,
            actor_id=actor_id,
            tenant_id=tenant_id,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
            details=details or {},
        )
    )
    await sink.flush()


class SqlAuditSink:
    """`AuditSink` on `audit_events`, on the tenant session.

    Events wait until the route flushes, after the answer and after a
    refusal alike; a sink that wrote mid-request would leave the session in
    whatever state the write left it. An event for another tenant is refused
    rather than dropped, for the reason `core/ai.py` gives.

    The commit drops `app.tenant_id`, which is transaction-local, so the
    tenant is rebound afterwards. A caller that keeps using the session
    without that rebinding finds every later query matching nothing.
    """

    def __init__(self, session: AsyncSession, tenant_id: str) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._pending: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        if event.tenant_id != self._tenant_id:
            raise ValueError("an audit event for another tenant cannot be recorded here")
        self._pending.append(event)

    async def flush(self) -> int:
        events, self._pending = self._pending, []
        for event in events:
            await self._session.execute(
                _AUDIT_INSERT,
                {
                    "tenant_id": event.tenant_id,
                    "actor_id": event.actor_id,
                    "action": event.action,
                    "target_type": event.target_type,
                    "target_id": event.target_id,
                    "outcome": str(event.outcome),
                    "details": json.dumps(dict(event.details)),
                    # From the registry, never from the caller: an action's
                    # class decides how long the row is kept, and a caller
                    # choosing it per call is how a security event is swept
                    # on the activity schedule.
                    "classification": str(actions.classification_of(event.action)),
                    "created_at": event.at,
                },
            )
        if events:
            await self._session.commit()
            await rebind_tenant(self._session, self._tenant_id)
        return len(events)
