"""The settings framework: what a setting is, and which value wins.

Four modules and no I/O. A definition says what a setting is; a registry holds
the ones this build declares and refuses a duplicate at import; coercion turns
what arrived into what the definition says it is or refuses it; and the
resolver walks the ladder -- a person's value, the organisation's, the
platform's, the definition's own default -- and says which rung answered.

Nothing here knows about a table, a tenant, a session or an HTTP request. The
three mappings the resolver is handed are whatever the caller read out of the
three value tables, and keeping a database driver out of this package is what
lets a product and the Control Plane describe the same setting while reading it
from two different schemas. `koras_reporting` is arranged the same way and for
the same reason.

The catalogue itself is not here. The foundation's settings are declared in the
API, beside the routes that serve them, the way reports are -- so a product can
add its own without this package knowing anything about it.
"""

from .coercion import ScopeRefused, SettingError, check_writable, coerce, valid
from .definitions import (
    CATEGORY_ORDER,
    Category,
    DataType,
    Scope,
    SettingDefinition,
    SettingValue,
    Status,
    UiControl,
)
from .registry import SettingsRegistry, build_catalogue
from .resolver import Resolution, Resolved, Skipped, Source, StoredValues, resolve, resolve_all

__all__ = [
    "CATEGORY_ORDER",
    "Category",
    "DataType",
    "Resolution",
    "Resolved",
    "Scope",
    "ScopeRefused",
    "SettingDefinition",
    "SettingError",
    "SettingValue",
    "SettingsRegistry",
    "Skipped",
    "Source",
    "Status",
    "StoredValues",
    "UiControl",
    "build_catalogue",
    "check_writable",
    "coerce",
    "resolve",
    "resolve_all",
    "valid",
]
