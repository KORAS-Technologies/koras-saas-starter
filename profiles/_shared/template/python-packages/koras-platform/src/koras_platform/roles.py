"""Organization roles.

Customer users, always scoped to a single organization. The Control Plane is the
authority for these; products consume them when deciding what a signed-in
customer user may do.

KORAS staff roles are deliberately not defined here. They exist only in the
Control Plane, which ships them as ``koras_platform.platform_roles``. A product
has no notion of platform staff authority, and a role set a product can
reference is a role set a product can accidentally honour -- so the names are
absent from product repositories entirely, not merely unused.
"""

from __future__ import annotations

from enum import StrEnum


class OrganizationRole(StrEnum):
    OWNER = "organization_owner"
    ADMIN = "organization_admin"
    BILLING_ADMIN = "billing_admin"
    SECURITY_ADMIN = "security_admin"
    MEMBER = "member"


_ORGANIZATION_VALUES = frozenset(role.value for role in OrganizationRole)


def is_organization_role(value: str) -> bool:
    return value in _ORGANIZATION_VALUES
