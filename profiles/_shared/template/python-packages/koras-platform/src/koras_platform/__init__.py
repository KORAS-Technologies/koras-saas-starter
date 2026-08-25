"""Vocabulary and invariants shared by every component of a KORAS project.

Kept separate from ``koras_auth``, which verifies tokens: this package defines
what an environment and a role *are*, while auth decides who is presenting one.
Services that never handle a JWT still need these definitions.
"""

from .adapters import EnvironmentIsolationError, ExternalAdapter
from .environment import Environment, resolve_environment
from .roles import OrganizationRole, is_organization_role

__all__ = [
    "Environment",
    "EnvironmentIsolationError",
    "ExternalAdapter",
    "OrganizationRole",
    "is_organization_role",
    "resolve_environment",
]
