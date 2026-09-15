"""Whether a caller may open a report, decided before anything runs.

The rule the navigation registry already applies to modules, applied per
report: a missing permission hides, a missing entitlement locks, and a
capability the build lacks hides because there is nothing to answer with.
Deterministic and free of I/O, so a router can decide for a whole catalogue
in one pass and a test can enumerate every outcome.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from enum import StrEnum

from .definitions import ReportDefinition, Status


class Visibility(StrEnum):
    AVAILABLE = "available"
    #: The caller may have it and the plan does not include it.
    LOCKED = "locked"
    #: The caller may not have it, or the build cannot answer it.
    HIDDEN = "hidden"


def visibility_for(
    definition: ReportDefinition,
    *,
    permissions: Iterable[str],
    entitled: Callable[[str], bool],
    capabilities: Iterable[str] | None = None,
) -> Visibility:
    held = frozenset(permissions)
    if definition.status is Status.DEPRECATED:
        return Visibility.HIDDEN
    if definition.capability is not None and capabilities is not None:
        if definition.capability not in frozenset(capabilities):
            return Visibility.HIDDEN
    if definition.permission not in held:
        return Visibility.HIDDEN
    if definition.entitlement is not None and not entitled(definition.entitlement):
        return Visibility.LOCKED
    return Visibility.AVAILABLE
