"""What a resolver is handed: who is asking, for which tenant, with which plan.

Built by the API from the verified token and the platform's answer, never
from a request body. A tenant-scoped context refuses to be built without a
tenant, so a resolver written against it cannot run unscoped by accident.
`session` is deliberately untyped here: the framework runs no query and
carries no driver; the product binds its SQLAlchemy session, a test binds a
stub.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .definitions import Scope


@dataclass(frozen=True)
class Entitlement:
    enabled: bool
    #: The plan's ceiling, or None for unlimited.
    limit: int | None = None


@dataclass(frozen=True)
class Plan:
    """The plan as the platform resolved it, or the unresolved default."""

    resolved: bool
    code: str | None = None
    status: str | None = None
    trial_ends_at: datetime | None = None
    period_ends_at: datetime | None = None
    entitlements: Mapping[str, Entitlement] = field(default_factory=dict)

    def limit_of(self, code: str) -> int | None:
        row = self.entitlements.get(code)
        return row.limit if row is not None and row.enabled else None

    def includes(self, code: str) -> bool:
        row = self.entitlements.get(code)
        return row is not None and row.enabled


UNRESOLVED_PLAN = Plan(resolved=False)


@dataclass(frozen=True)
class ReportContext:
    scope: Scope
    user_id: str
    permissions: frozenset[str]
    plan: Plan
    session: Any
    tenant_id: str | None = None
    organization_id: str | None = None
    product_code: str | None = None
    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    #: What the product chose to expose to its resolvers, by name.
    services: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.scope is Scope.TENANT and not self.tenant_id:
            raise ValueError("a tenant-scoped report context needs a tenant")
        if not self.user_id:
            raise ValueError("a report context needs a caller")
