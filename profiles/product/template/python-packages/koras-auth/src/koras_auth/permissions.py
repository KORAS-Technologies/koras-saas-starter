"""The product permission catalogue, on the Python side.

The same closed set `packages/permissions/src/index.ts` declares, and the same
role-to-permission map. Duplicated rather than shared because the two runtimes
cannot import each other; the generator's structural test compares the two
files and fails when they drift, which is how the Files router got by with
mirroring one rule by hand and how a second consumer -- the AI runtime, which
checks a tool's declared permission -- cannot.

Add a permission here and in the TypeScript catalogue, in the same commit, or
the test says which side is behind.
"""

from __future__ import annotations

from collections.abc import Iterable

from koras_platform import OrganizationRole

__all__ = ["PRODUCT_PERMISSIONS", "ROLE_PERMISSIONS", "is_product_permission", "permissions_for"]

PRODUCT_PERMISSIONS: tuple[str, ...] = (
    "product.access",
    "team.read",
    "team.manage",
    "settings.read",
    "settings.manage",
    "files.read",
    "files.upload",
    "files.manage",
    # The assistant. Every member may use it; approving the actions it
    # proposes is the authority to make them happen, so it belongs to the
    # people who administer the tenant.
    "ai.use",
    "ai.approve",
)

_EVERYONE: tuple[str, ...] = ("product.access", "files.read", "files.upload", "ai.use")

ROLE_PERMISSIONS: dict[OrganizationRole, tuple[str, ...]] = {
    OrganizationRole.OWNER: PRODUCT_PERMISSIONS,
    OrganizationRole.ADMIN: PRODUCT_PERMISSIONS,
    OrganizationRole.SECURITY_ADMIN: (*_EVERYONE, "team.read", "settings.read"),
    OrganizationRole.BILLING_ADMIN: (*_EVERYONE, "settings.read"),
    OrganizationRole.MEMBER: _EVERYONE,
}

_KNOWN = frozenset(PRODUCT_PERMISSIONS)


def is_product_permission(value: str) -> bool:
    return value in _KNOWN


def permissions_for(roles: Iterable[OrganizationRole | str]) -> frozenset[str]:
    """Every permission the roles grant, as the union the TypeScript side computes.

    Unknown names grant nothing: a role this build does not recognise is not
    a role at all here, which is the same rule the session cookie is read
    under.
    """
    granted: set[str] = set()
    for role in roles:
        try:
            resolved = role if isinstance(role, OrganizationRole) else OrganizationRole(role)
        except ValueError:
            continue
        granted.update(ROLE_PERMISSIONS[resolved])
    return frozenset(granted)
