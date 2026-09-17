"""What a setting is, before anybody has set it.

A definition is code. It declares the key, the shape of the value, which
scopes may hold one, what it defaults to when nothing holds one, and the i18n
keys a surface renders it by. It carries no value and knows nothing about a
tenant, a person or a table.

Everything a definition can get wrong is refused at import. A duplicate key, an
enum whose default is not among its options, an integer default outside its own
bounds, a setting marked visible to a person that no person may write -- each
raises where it is a traceback with a stack rather than at request time, where
it is a 500 for somebody's customer. That is the property `koras_reporting`'s
registry has and the reason it has it.

**Labels are keys, not English.** A definition carries `label_key` and
`description_key`, and the catalogue in `packages/i18n` carries the sentences,
in every language the product speaks. Prose in a definition would be prose no
translator ever sees.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

#: The value a setting can hold.
#:
#: Deliberately the JSON types and nothing else. A value is stored as `jsonb`,
#: travels over an API, and is rendered in a browser; a type that does not
#: survive that round trip is a type a setting cannot have. A list is a tuple
#: here so a definition's default cannot be mutated by whoever reads it.
SettingValue = bool | int | float | str | tuple[str, ...] | dict[str, Any]

_DOTTED = re.compile(r"^[a-z][a-z0-9]*(\.[a-z][a-zA-Z0-9]*)+$")
_I18N_KEY = re.compile(r"^[a-z][a-zA-Z0-9]*(\.[a-zA-Z0-9]+)+$")


class Scope(StrEnum):
    """Which levels may hold a value for this setting.

    The names read as the ladder they are: every setting has a platform
    default, some may be set by an organisation, and some of those may be
    overridden by a person. There is no scope that skips a rung -- a setting a
    person may change but an organisation may not would mean an administrator
    who cannot see why their people disagree.
    """

    #: The platform decides, and nobody else. A customer never sees one.
    GLOBAL_ONLY = "global_only"
    #: The platform decides the default; an organisation may change it.
    GLOBAL_ORG = "global_org"
    #: As above, and a person may then override it for themselves.
    GLOBAL_ORG_USER = "global_org_user"

    @property
    def admits_organization(self) -> bool:
        return self is not Scope.GLOBAL_ONLY

    @property
    def admits_user(self) -> bool:
        return self is Scope.GLOBAL_ORG_USER


class DataType(StrEnum):
    """How a stored value is read back.

    `ENUM` is a string constrained to the definition's options, and is separate
    from `STRING` because the two are rendered by different controls and
    refused for different reasons.
    """

    BOOLEAN = "boolean"
    INTEGER = "integer"
    DECIMAL = "decimal"
    STRING = "string"
    ENUM = "enum"
    STRING_LIST = "string_list"
    OBJECT = "object"


class Category(StrEnum):
    """Where a setting appears, and in what order.

    The first seven are the initial catalogue. The rest are declared now and
    hold nothing yet, as of 2026-09-17: a category added later is a value in
    this enum plus an entry in `CATEGORY_ORDER`, and every surface that groups
    by category keeps working. That is the extension the design was asked for,
    and it costs one line each to have it already.
    """

    GENERAL = "general"
    APPEARANCE = "appearance"
    GRID = "grid"
    NOTIFICATIONS = "notifications"
    FILES = "files"
    REPORTING = "reporting"
    ACCESSIBILITY = "accessibility"
    SECURITY = "security"
    STORAGE = "storage"
    BACKUP = "backup"
    RETENTION = "retention"
    AUDIT = "audit"
    AI = "ai"
    WORKFLOW = "workflow"
    SEARCH = "search"
    BRANDING = "branding"
    INTEGRATIONS = "integrations"
    PRIVACY = "privacy"
    SUPPORT = "support"


#: The order categories are shown in, which is not their alphabetical order.
#:
#: A tuple rather than the enum's own order, because the enum's order is a
#: declaration order somebody will one day tidy, and the sequence a customer
#: reads should not change when they do.
CATEGORY_ORDER: tuple[Category, ...] = (
    Category.GENERAL,
    Category.APPEARANCE,
    Category.GRID,
    Category.NOTIFICATIONS,
    Category.FILES,
    Category.REPORTING,
    Category.ACCESSIBILITY,
    Category.SECURITY,
    Category.STORAGE,
    Category.BACKUP,
    Category.RETENTION,
    Category.AUDIT,
    Category.AI,
    Category.WORKFLOW,
    Category.SEARCH,
    Category.BRANDING,
    Category.INTEGRATIONS,
    Category.PRIVACY,
    Category.SUPPORT,
)


class Status(StrEnum):
    """Whether a setting is still offered.

    This is what the brief called an active flag, and it is a status rather
    than a boolean for the reason `ReportDefinition.status` is: a withdrawn
    setting is not the same as one that never existed. A deprecated definition
    still resolves -- rows holding it keep answering -- and stops being offered
    on any surface, so nobody sets it again while the ones who have it keep
    working.
    """

    AVAILABLE = "available"
    DEPRECATED = "deprecated"


class UiControl(StrEnum):
    """A hint about which control renders a value.

    A hint, never behaviour. A surface that cannot draw chips may draw a text
    field; what it may not do is accept a value the definition refuses, and
    that decision is `coercion.py`'s, not this field's.
    """

    TOGGLE = "toggle"
    SELECT = "select"
    NUMBER = "number"
    TEXT = "text"
    CHIPS = "chips"


@dataclass(frozen=True)
class SettingDefinition:
    """One setting this build knows about.

    Frozen, because a definition is a fact of the build. Everything that could
    be inconsistent is checked in `__post_init__`, so a catalogue either
    imports or the process does not start.
    """

    key: str
    category: Category
    data_type: DataType
    #: What resolves when no scope holds a value. Mandatory, and the reason a
    #: product with no Control Plane and an empty database still renders: the
    #: fourth level of the ladder is always present.
    default: SettingValue
    scope: Scope
    label_key: str
    description_key: str

    #: Required when `data_type` is `ENUM`, refused otherwise.
    options: tuple[str, ...] = ()
    #: Bounds for `INTEGER` and `DECIMAL`. Checked against the default here and
    #: against every written value in `coercion.py`.
    minimum: float | None = None
    maximum: float | None = None

    #: Whether an organisation administrator sees it on their settings page. A
    #: setting can be organisation-scoped and still hidden -- something the
    #: platform sets on their behalf and they do not administer.
    org_admin_visible: bool = True
    #: Whether a person sees it on their preferences page. Refused unless the
    #: scope admits a person, which is the rule that stops a surface offering
    #: an override nothing would honour.
    user_visible: bool = True
    #: Values are replaced by a marker in audit details. Not a secret store --
    #: secrets never enter this framework at all -- but a setting whose value
    #: is nobody else's business.
    sensitive: bool = False
    #: Never shown on any customer surface, whatever the two flags above say.
    system: bool = False

    status: Status = Status.AVAILABLE
    ui: UiControl = UiControl.TEXT
    order: int = 100
    #: Free-form labels for grouping and search. Not authorization.
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not _DOTTED.match(self.key):
            raise ValueError(
                f"setting key {self.key!r} must be dotted, as `grid.pageSize` or "
                "`general.timezone`"
            )
        # The key's first segment is conventionally the category -- `grid.*` in
        # GRID -- and is deliberately not enforced. The initial catalogue
        # already breaks it: the appearance settings are `ui.*`, because that is
        # what a reader of `ui.theme` expects and `appearance.theme` is not.
        # A rule the first catalogue has to violate is a rule that teaches
        # nothing.
        for name, text in (
            ("label_key", self.label_key),
            ("description_key", self.description_key),
        ):
            if not _I18N_KEY.match(text):
                raise ValueError(
                    f"setting {self.key!r} needs a dotted i18n key for {name}, not prose"
                )

        if self.data_type is DataType.ENUM:
            if not self.options:
                raise ValueError(f"setting {self.key!r} is an enum and declares no options")
            if self.default not in self.options:
                raise ValueError(
                    f"setting {self.key!r} defaults to {self.default!r}, "
                    f"which is not one of its options"
                )
        elif self.options:
            raise ValueError(
                f"setting {self.key!r} declares options but is a {self.data_type.value}"
            )

        self._check_default_type()
        self._check_bounds()

        if self.user_visible and not self.scope.admits_user:
            raise ValueError(
                f"setting {self.key!r} is marked visible to a person but its scope "
                f"({self.scope.value}) admits no personal override"
            )

    def _check_default_type(self) -> None:
        """The default must be the type the definition says it is.

        Checked here rather than trusted, because a default is the one value
        that is never coerced on the way in: it comes straight from the
        catalogue to the caller when nothing else holds a value.

        `bool` is tested before `int` on purpose. In Python `True` is an `int`,
        so an integer setting defaulting to `True` would pass a naive check and
        then render as a checkbox nobody asked for.
        """
        default = self.default
        ok = False
        match self.data_type:
            case DataType.BOOLEAN:
                ok = isinstance(default, bool)
            case DataType.INTEGER:
                ok = isinstance(default, int) and not isinstance(default, bool)
            case DataType.DECIMAL:
                ok = isinstance(default, (int, float)) and not isinstance(default, bool)
            case DataType.STRING | DataType.ENUM:
                ok = isinstance(default, str)
            case DataType.STRING_LIST:
                ok = isinstance(default, tuple) and all(isinstance(item, str) for item in default)
            case DataType.OBJECT:
                ok = isinstance(default, dict)
        if not ok:
            raise ValueError(
                f"setting {self.key!r} is a {self.data_type.value} and defaults to "
                f"{default!r}, which is not one"
            )

    def _check_bounds(self) -> None:
        numeric = self.data_type in (DataType.INTEGER, DataType.DECIMAL)
        if not numeric:
            if self.minimum is not None or self.maximum is not None:
                raise ValueError(
                    f"setting {self.key!r} declares bounds but is a {self.data_type.value}"
                )
            return
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError(f"setting {self.key!r} has a minimum above its maximum")
        value = self.default
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return  # already reported by _check_default_type
        if self.minimum is not None and value < self.minimum:
            raise ValueError(f"setting {self.key!r} defaults below its own minimum")
        if self.maximum is not None and value > self.maximum:
            raise ValueError(f"setting {self.key!r} defaults above its own maximum")

    @property
    def offered(self) -> bool:
        """Whether a surface should still present this setting."""
        return self.status is Status.AVAILABLE
