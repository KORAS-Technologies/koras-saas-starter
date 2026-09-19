"""What a catalogue refuses at import, rather than at request time.

**Named for its package, like every module in these directories.** Each
`python-packages/*/tests/` is on the path as a top-level module with no
`__init__.py`, so two packages carrying one filename are two modules with one
name, and mypy refuses the pair when it checks the whole workspace. This file
was `test_definitions_and_registry.py` and `koras-reporting` already had one --
which is a good name for both, and available to neither.
"""

from __future__ import annotations

import pytest
from koras_settings import (
    Category,
    DataType,
    Scope,
    SettingsRegistry,
    Status,
    build_catalogue,
)
from settings_support import setting


def test_a_duplicate_key_is_refused() -> None:
    registry = SettingsRegistry()
    registry.add(setting())
    with pytest.raises(ValueError, match="already registered"):
        registry.add(setting())


def test_a_catalogue_is_assembled_from_several_groups() -> None:
    catalogue = build_catalogue(
        [setting("grid.pageSize")],
        [
            setting(
                "grid.stickyHeader",
                data_type=DataType.BOOLEAN,
                default=True,
                minimum=None,
                maximum=None,
            )
        ],
    )
    assert len(catalogue) == 2
    assert "grid.stickyHeader" in catalogue


def test_a_collision_between_groups_is_refused() -> None:
    """A product shadowing a foundation setting is always a mistake.

    One of the two is not being read and nothing would say which.
    """
    with pytest.raises(ValueError, match="already registered"):
        build_catalogue([setting()], [setting()])


def test_settings_iterate_by_category_then_order_then_key() -> None:
    catalogue = build_catalogue(
        [
            setting("grid.pageSize", order=20),
            setting("grid.density", order=10, data_type=DataType.STRING, default="cosy",
                    minimum=None, maximum=None),
            setting(
                "general.timezone",
                category=Category.GENERAL,
                data_type=DataType.STRING,
                default="UTC",
                minimum=None,
                maximum=None,
                order=99,
            ),
        ]
    )
    # General comes before Grid in CATEGORY_ORDER whatever the declaration
    # order was, and within Grid the lower `order` wins over the alphabet.
    assert [s.key for s in catalogue] == ["general.timezone", "grid.density", "grid.pageSize"]


def test_a_deprecated_setting_still_resolves_but_is_not_offered() -> None:
    catalogue = build_catalogue([setting(status=Status.DEPRECATED)])
    assert len(catalogue) == 1
    assert list(catalogue.offered()) == []


def test_by_category_drops_the_empty_ones() -> None:
    catalogue = build_catalogue([setting()])
    grouped = catalogue.by_category()
    assert [category for category, _ in grouped] == [Category.GRID]


def test_an_unregistered_key_is_refused_rather_than_defaulted() -> None:
    catalogue = build_catalogue([setting()])
    assert catalogue.get("grid.nothing") is None
    with pytest.raises(KeyError, match="grid.nothing"):
        catalogue.require("grid.nothing")


def test_a_key_that_is_not_dotted_is_refused() -> None:
    with pytest.raises(ValueError, match="must be dotted"):
        setting("pageSize")


def test_a_label_written_as_prose_is_refused() -> None:
    """A definition carries i18n keys, so a translator sees every sentence."""
    with pytest.raises(ValueError, match="i18n key"):
        setting(label_key="Rows per page")


def test_an_enum_with_no_options_is_refused() -> None:
    with pytest.raises(ValueError, match="declares no options"):
        setting(
            "ui.theme",
            category=Category.APPEARANCE,
            data_type=DataType.ENUM,
            default="system",
            minimum=None,
            maximum=None,
        )


def test_an_enum_default_outside_its_options_is_refused() -> None:
    with pytest.raises(ValueError, match="not one of its options"):
        setting(
            "ui.theme",
            category=Category.APPEARANCE,
            data_type=DataType.ENUM,
            default="mauve",
            options=("system", "light", "dark"),
            minimum=None,
            maximum=None,
        )


def test_options_on_something_that_is_not_an_enum_are_refused() -> None:
    with pytest.raises(ValueError, match="declares options"):
        setting(options=("10", "25"))


def test_a_default_of_the_wrong_type_is_refused() -> None:
    with pytest.raises(ValueError, match="is a integer and defaults to"):
        setting(default="fifty")


def test_a_boolean_default_does_not_satisfy_an_integer() -> None:
    """`True` is an `int` in Python, and a page-size of true is not a size."""
    with pytest.raises(ValueError, match="defaults to"):
        setting(default=True)


def test_a_default_outside_its_own_bounds_is_refused() -> None:
    with pytest.raises(ValueError, match="below its own minimum"):
        setting(default=5)
    with pytest.raises(ValueError, match="above its own maximum"):
        setting(default=5000)


def test_a_minimum_above_its_maximum_is_refused() -> None:
    with pytest.raises(ValueError, match="minimum above its maximum"):
        setting(minimum=100, maximum=10)


def test_bounds_on_something_that_is_not_a_number_are_refused() -> None:
    with pytest.raises(ValueError, match="declares bounds"):
        setting(data_type=DataType.STRING, default="x")


def test_a_person_cannot_be_offered_a_setting_no_person_may_write() -> None:
    """The brief's scope rule, enforced where it cannot be forgotten.

    A definition marked visible to a person whose scope admits no personal
    override would render a control that silently does nothing -- or, worse,
    one the API refuses after the person has used it.
    """
    with pytest.raises(ValueError, match="admits no personal override"):
        setting(scope=Scope.GLOBAL_ORG, user_visible=True)


def test_a_two_level_setting_may_still_be_declared_if_it_is_not_user_visible() -> None:
    declared = setting(scope=Scope.GLOBAL_ORG, user_visible=False)
    assert declared.scope.admits_organization is True
    assert declared.scope.admits_user is False


def test_a_platform_only_setting_admits_neither_rung() -> None:
    declared = setting(scope=Scope.GLOBAL_ONLY, user_visible=False)
    assert declared.scope.admits_organization is False
    assert declared.scope.admits_user is False
