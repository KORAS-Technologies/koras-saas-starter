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

from koras_audit import AuditEvent, Outcome
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .database import rebind_tenant

_AUDIT_INSERT = text(
    "insert into public.audit_events "
    " (tenant_id, actor_id, action, target_type, target_id, outcome, details, created_at) "
    "values (:tenant_id, :actor_id, :action, :target_type, :target_id, :outcome, "
    " cast(:details as jsonb), :created_at)"
)


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
                    "created_at": event.at,
                },
            )
        if events:
            await self._session.commit()
            await rebind_tenant(self._session, self._tenant_id)
        return len(events)
