"""KORAS staff roles. Control Plane only.

Not shipped by the starter, and deliberately a separate module rather than an
addition to ``roles.py``. Every other file in this package comes from the
starter, so a future starter sync can replace them wholesale; this one is
invisible to that process and survives untouched.

That also means it must be imported explicitly:

    from koras_platform.platform_roles import PlatformRole

rather than from the package root, whose ``__init__`` is starter-owned and would
lose the export on the next sync.
"""

from __future__ import annotations

from enum import StrEnum

from .roles import OrganizationRole


class PlatformRole(StrEnum):
    """KORAS staff. MFA is mandatory for every one of these."""

    SUPER_ADMIN = "platform_super_admin"
    ADMIN = "platform_admin"
    SUPPORT = "platform_support"
    BILLING = "platform_billing"
    READONLY = "platform_readonly"


_PLATFORM_VALUES = frozenset(role.value for role in PlatformRole)
_ORGANIZATION_VALUES = frozenset(role.value for role in OrganizationRole)

# Checked at import rather than asserted: `assert` is stripped under python -O,
# and this is a security boundary, not a debugging aid. If the two sets ever
# overlap, a customer role would grant staff authority somewhere and nothing
# would say so.
_OVERLAP = _PLATFORM_VALUES & _ORGANIZATION_VALUES
if _OVERLAP:
    raise RuntimeError(
        f"Platform and organization roles must be disjoint; both define: {sorted(_OVERLAP)}"
    )


def is_platform_role(value: str) -> bool:
    return value in _PLATFORM_VALUES
