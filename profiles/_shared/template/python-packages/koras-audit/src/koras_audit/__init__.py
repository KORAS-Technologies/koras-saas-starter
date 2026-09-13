"""Audit events: who did what, to which target, with what outcome.

The shape and the emitter, and nothing else yet. An event names an action, an
actor, a tenant, a target and an outcome -- including a refusal, because a
denial is as much a fact about the system as a success -- and carries a small
mapping of details. It carries no secret, no token and no content: the point
of an audit record is that it can be kept longer and read by more people than
the data it describes.

`AuditSink` is the seam. The one implementation here writes a structured log
record, which is enough for a log pipeline to index and for a test to assert.
A durable table is the next implementation, behind the same protocol, and
nothing that emits an event has to change for it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

__all__ = ["AuditEvent", "AuditSink", "LoggingAuditSink", "MemoryAuditSink", "Outcome"]

Outcome = Literal["ok", "denied", "failed", "pending"]

_FORBIDDEN_DETAIL = ("token", "secret", "password", "key", "credential", "authorization")


@dataclass(frozen=True)
class AuditEvent:
    #: What happened, dotted: ai.tool.proposed, ai.action.approved.
    action: str
    actor_id: str
    tenant_id: str
    target_type: str
    target_id: str
    outcome: Outcome
    details: Mapping[str, str | int | bool] = field(default_factory=dict)
    at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        for name in self.details:
            lowered = name.lower()
            if any(word in lowered for word in _FORBIDDEN_DETAIL):
                raise ValueError(
                    f"audit detail {name!r} looks like a secret and may not be recorded"
                )


class AuditSink(Protocol):
    def emit(self, event: AuditEvent) -> None: ...


class LoggingAuditSink:
    """One structured line per event, on a logger of its own."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._log = logger or logging.getLogger("koras.audit")

    def emit(self, event: AuditEvent) -> None:
        self._log.info(
            "audit %s",
            json.dumps(
                {
                    "action": event.action,
                    "actor_id": event.actor_id,
                    "tenant_id": event.tenant_id,
                    "target_type": event.target_type,
                    "target_id": event.target_id,
                    "outcome": event.outcome,
                    "details": dict(event.details),
                    "at": event.at.isoformat(),
                },
                sort_keys=True,
            ),
        )


class MemoryAuditSink:
    """Keeps the events, for a test to read back."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)
