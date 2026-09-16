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
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol

__all__ = [
    "AuditAction",
    "AuditActionRegistry",
    "AuditEvent",
    "AuditSink",
    "Classification",
    "LoggingAuditSink",
    "MemoryAuditSink",
    "Outcome",
    "actions",
]

Outcome = Literal["ok", "denied", "failed", "pending"]

_ACTION = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


class Classification(StrEnum):
    """What kind of record this is, and therefore how long it is kept.

    The distinction that stops this table becoming the log. An event is a row
    here only when somebody may later have to prove it happened; everything
    else is a log line and lives for days, not years.

    activity        someone did an ordinary thing: a file was opened, a report
                    was viewed. Interesting for a week, rarely for a year.
    audit           the default. A durable record of a change or an access
                    that a customer or an auditor may ask about later.
    security        an authorization decision, a refusal, a credential or a
                    hold. Kept longest, and readable by fewer people.
    administrative  a configuration or membership change: who was invited,
                    what was switched on.
    """

    ACTIVITY = "activity"
    AUDIT = "audit"
    SECURITY = "security"
    ADMINISTRATIVE = "administrative"


@dataclass(frozen=True)
class AuditAction:
    """One action this system can record, declared rather than discovered.

    The classification belongs to the action, not to the call site: the same
    action recorded from two routes must be kept for the same time, and a
    caller deciding that per call is how a security event ends up swept with
    the activity.
    """

    key: str
    classification: Classification
    summary: str

    def __post_init__(self) -> None:
        if not _ACTION.match(self.key):
            raise ValueError(
                f"audit action {self.key!r} must be dotted lower-case, as `storage.object.uploaded`"
            )
        if not self.summary.strip():
            raise ValueError(f"audit action {self.key!r} needs a summary")


class AuditActionRegistry:
    """The actions this build can record, refused on duplicate.

    `koras_reporting`'s shape: registration fails at import, where it is a
    traceback with a stack, rather than at request time, where it is a 500 for
    a customer. Iteration is ordered so two runs of one build agree.
    """

    def __init__(self) -> None:
        self._actions: dict[str, AuditAction] = {}

    def add(self, action: AuditAction) -> None:
        if action.key in self._actions:
            raise ValueError(f"the audit action {action.key!r} is already registered")
        self._actions[action.key] = action

    def extend(self, actions: Iterable[AuditAction]) -> None:
        for action in actions:
            self.add(action)

    def clear(self) -> None:
        """For tests, and for a second registration pass in one process."""
        self._actions.clear()

    def __iter__(self) -> Iterator[AuditAction]:
        return iter(sorted(self._actions.values(), key=lambda action: action.key))

    def __len__(self) -> int:
        return len(self._actions)

    def __contains__(self, key: object) -> bool:
        return key in self._actions

    def classification_of(self, key: str) -> Classification:
        """The class an action is kept under.

        An unregistered action is refused rather than given a default. A
        default would mean a security event swept on the activity schedule
        because somebody added a string and nobody noticed.
        """
        action = self._actions.get(key)
        if action is None:
            raise ValueError(
                f"the audit action {key!r} is not registered; declare it before recording it"
            )
        return action.classification


#: The registry for this process. Each module registers its own actions at
#: import; see `core/audit.py` in the API.
actions = AuditActionRegistry()

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
