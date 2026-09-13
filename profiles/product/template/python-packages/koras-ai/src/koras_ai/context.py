"""Who an AI operation runs for.

Built on the server from a verified token and a resolved tenant, and from
nothing a browser sent. The API's dependency is the only constructor in a
product; a test builds one by hand. It carries the caller's permissions as a
set of strings rather than their roles, so this package never has to know how
a role becomes a permission -- that mapping is the product's, in one place on
each side of the language boundary.

There is no workspace here. The product has no such concept today, and a
field that nothing resolves would be a field somebody fills from a request.
`page` is the one piece of client-supplied context, and it is exactly what it
says: which screen the person was on. It scopes nothing and authorises
nothing; a tool that reads a resource named by it still runs under the tenant
session and still checks its own permission.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageContext:
    """The resource the assistant was opened beside. Informational."""

    type: str
    id: str

    def __post_init__(self) -> None:
        if not self.type.strip() or not self.id.strip():
            raise ValueError("a page context needs both a type and an id")


@dataclass(frozen=True)
class AIContext:
    product_code: str
    environment: str
    tenant_id: str
    organization_id: str
    user_id: str
    #: The organization roles the verified token carried.
    roles: frozenset[str]
    #: The product permissions those roles grant, already derived.
    permissions: frozenset[str]
    page: PageContext | None = None

    def __post_init__(self) -> None:
        for name in ("product_code", "environment", "tenant_id", "organization_id", "user_id"):
            if not str(getattr(self, name)).strip():
                # A programming error, not a request error: nothing a caller
                # sent reaches these fields, so an empty one means the
                # dependency that builds the context is broken.
                raise ValueError(f"AIContext.{name} must not be empty")

    def holds(self, permission: str) -> bool:
        return permission in self.permissions

    def has_any_role(self, *roles: str) -> bool:
        return bool(self.roles & frozenset(roles))
