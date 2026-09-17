"""Which value wins, and why that one.

The ladder, once, in a pure function:

    a person's own value        if the scope admits one
    the organisation's value
    the platform's value
    the definition's own default

Nothing here reads a database. It is handed three mappings of key to stored
value -- whatever the three tables held for this caller -- and the catalogue,
and it answers. That is what makes every scenario in the test plan a unit test
with no fixtures: "an existing organisation is unaffected by a later platform
change" is two calls with different global mappings and the same organisation
one.

**Why the answer carries its source.** A settings page has to say whether a
value is the default or something somebody chose, and a person's preferences
page has to say what they would fall back to. Returning a bare value would mean
every surface re-deriving that by comparing against the default, which gets it
wrong the moment somebody deliberately sets a value equal to the default.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .coercion import SettingError, coerce
from .definitions import SettingDefinition, SettingValue
from .registry import SettingsRegistry

#: What one of the three tables held, as `{key: value}`.
StoredValues = Mapping[str, Any]


class Source(StrEnum):
    """Which rung of the ladder answered."""

    USER = "user"
    ORGANIZATION = "organization"
    GLOBAL = "global"
    DEFAULT = "default"


@dataclass(frozen=True)
class Resolved:
    """One setting, resolved for one caller."""

    key: str
    value: SettingValue
    source: Source
    #: Whether this caller could set a personal value for it. False for every
    #: two-level setting, so a preferences page knows what to offer without
    #: reading the scope itself.
    can_override: bool
    #: What the organisation would fall back to if this person cleared theirs.
    #: The value a "reset to the organisation setting" control announces.
    organization_value: SettingValue
    #: What the platform holds, which is what an organisation reset copies in.
    global_value: SettingValue


@dataclass(frozen=True)
class Skipped:
    """A stored value the resolver would not use, and why.

    Not an error. A bound tightened or an option withdrawn leaves rows that
    were valid when written; the resolver falls through and records what it
    passed over, so an operator can find them without a customer reporting a
    page that will not load.
    """

    key: str
    source: Source
    value: Any


@dataclass(frozen=True)
class Resolution:
    """Every setting, resolved, plus what was passed over."""

    settings: dict[str, Resolved]
    skipped: tuple[Skipped, ...]

    def value(self, key: str) -> SettingValue:
        """The resolved value, for a caller that wants only that."""
        return self.settings[key].value


def resolve(
    definition: SettingDefinition,
    *,
    global_values: StoredValues,
    organization_values: StoredValues,
    member_values: StoredValues,
) -> tuple[Resolved, tuple[Skipped, ...]]:
    """One setting's answer, and anything skipped reaching it."""
    skipped: list[Skipped] = []

    platform = _usable(definition, global_values, Source.GLOBAL, skipped)
    global_value = platform if platform is not None else definition.default

    organization: SettingValue | None = None
    if definition.scope.admits_organization:
        organization = _usable(definition, organization_values, Source.ORGANIZATION, skipped)
    organization_value = organization if organization is not None else global_value

    member: SettingValue | None = None
    if definition.scope.admits_user:
        member = _usable(definition, member_values, Source.USER, skipped)

    if member is not None:
        value, source = member, Source.USER
    elif organization is not None:
        value, source = organization, Source.ORGANIZATION
    elif platform is not None:
        value, source = platform, Source.GLOBAL
    else:
        value, source = definition.default, Source.DEFAULT

    resolved = Resolved(
        key=definition.key,
        value=value,
        source=source,
        can_override=definition.scope.admits_user,
        organization_value=organization_value,
        global_value=global_value,
    )
    return resolved, tuple(skipped)


def resolve_all(
    registry: SettingsRegistry,
    *,
    global_values: StoredValues,
    organization_values: StoredValues,
    member_values: StoredValues,
) -> Resolution:
    """Every registered setting, resolved for one caller.

    This is what a request uses. Three mappings in, one answer out, and the
    caller reads three tables once rather than once per key -- the thing the
    brief asks for in so many words and the thing a naive implementation gets
    wrong first.

    Deprecated settings are resolved too. A page stops offering them; code that
    still reads one keeps working until it is changed, which is the difference
    between withdrawing a setting and breaking every caller of it.

    A stored key that is not in the catalogue is ignored rather than returned.
    A definition removed in a deploy leaves rows behind, and answering with one
    would hand a surface a setting it has no definition to render.
    """
    settings: dict[str, Resolved] = {}
    skipped: list[Skipped] = []
    for definition in registry:
        answer, passed_over = resolve(
            definition,
            global_values=global_values,
            organization_values=organization_values,
            member_values=member_values,
        )
        settings[definition.key] = answer
        skipped.extend(passed_over)
    return Resolution(settings=settings, skipped=tuple(skipped))


def _usable(
    definition: SettingDefinition,
    stored: StoredValues,
    source: Source,
    skipped: list[Skipped],
) -> SettingValue | None:
    """The stored value for this key at this rung, if there is a usable one.

    `None` means "this rung holds nothing", which is why a setting whose value
    is genuinely null cannot exist: clearing a setting is removing the row, and
    a row holding null would be indistinguishable from the absence the ladder
    is built on. `member_preferences.locale` made the other choice -- null
    clears the choice rather than deleting the row -- and it could, because it
    is one column rather than a ladder.
    """
    if definition.key not in stored:
        return None
    raw = stored[definition.key]
    if raw is None:
        return None
    try:
        return coerce(definition, raw)
    except SettingError:
        # Coerced rather than merely checked, so a row and a freshly written
        # value go through one path. Checking and then converting would be two
        # implementations of the same rule, and the pair would disagree the
        # first time one of them learned something.
        skipped.append(Skipped(key=definition.key, source=source, value=raw))
        return None
