"""The settings this build knows about, refused on duplicate.

`koras_reporting.registry`'s shape, for the same reason it has it: the
catalogue is assembled once at import, so a duplicate key or a malformed
definition is a traceback with a stack rather than a 500 for a customer on the
day somebody opens the settings page.

Iteration is ordered by category, then by the definition's own order, then by
key -- so two runs of one build agree, and a settings page does not reshuffle
itself between deploys.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from .definitions import CATEGORY_ORDER, Category, SettingDefinition

_CATEGORY_POSITION: dict[Category, int] = {
    category: position for position, category in enumerate(CATEGORY_ORDER)
}


class SettingsRegistry:
    """Every setting declared in this process.

    A registry rather than a list, so that a product adding its own settings
    beside the foundation's cannot silently shadow one. Two definitions with
    the same key is always a mistake -- one of them is not being read, and
    nothing would say which.
    """

    def __init__(self) -> None:
        self._settings: dict[str, SettingDefinition] = {}

    def add(self, definition: SettingDefinition) -> None:
        if definition.key in self._settings:
            raise ValueError(f"the setting {definition.key!r} is already registered")
        self._settings[definition.key] = definition

    def extend(self, definitions: Iterable[SettingDefinition]) -> None:
        for definition in definitions:
            self.add(definition)

    def get(self, key: str) -> SettingDefinition | None:
        return self._settings.get(key)

    def require(self, key: str) -> SettingDefinition:
        """The definition for a key, or a refusal naming it.

        An unknown key is an error rather than a default, the same decision
        `AuditActionRegistry.classification_of` takes: a value written under a
        key nobody declared is a value nothing validates, nothing renders and
        nothing sweeps.
        """
        definition = self._settings.get(key)
        if definition is None:
            raise KeyError(f"no setting is registered under {key!r}")
        return definition

    def __contains__(self, key: object) -> bool:
        return key in self._settings

    def __len__(self) -> int:
        return len(self._settings)

    def __iter__(self) -> Iterator[SettingDefinition]:
        return iter(
            sorted(
                self._settings.values(),
                key=lambda setting: (
                    _CATEGORY_POSITION[setting.category],
                    setting.order,
                    setting.key,
                ),
            )
        )

    def offered(self) -> Iterator[SettingDefinition]:
        """The definitions a surface should present, in display order.

        Deprecated settings still resolve -- rows holding one keep answering --
        and stop being offered. That is the whole difference between
        withdrawing a setting and deleting it.
        """
        return (setting for setting in self if setting.offered)

    def by_category(self) -> list[tuple[Category, list[SettingDefinition]]]:
        """Display order, grouped, with empty categories dropped.

        The grouping a settings page renders. Built here rather than in each
        surface so the console, the product and a product's own extension agree
        about what order the categories come in.
        """
        grouped: dict[Category, list[SettingDefinition]] = {}
        for setting in self.offered():
            grouped.setdefault(setting.category, []).append(setting)
        return [
            (category, grouped[category]) for category in CATEGORY_ORDER if category in grouped
        ]


def build_catalogue(*groups: Iterable[SettingDefinition]) -> SettingsRegistry:
    """Assemble the catalogue for this process, once, at import.

    Variadic so the foundation's definitions and a product's own are separate
    arguments rather than one concatenated list -- which means the traceback on
    a collision says which group was being added when it happened.
    """
    registry = SettingsRegistry()
    for group in groups:
        registry.extend(group)
    return registry
