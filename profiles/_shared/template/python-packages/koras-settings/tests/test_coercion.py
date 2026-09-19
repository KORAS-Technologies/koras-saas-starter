"""What a write is allowed to say, and what it is refused for."""

from __future__ import annotations

import pytest
from koras_settings import (
    Category,
    DataType,
    Scope,
    ScopeRefused,
    SettingDefinition,
    SettingError,
    check_writable,
    coerce,
    valid,
)
from settings_support import setting


def test_an_integer_within_its_bounds_is_kept() -> None:
    assert coerce(setting(), 25) == 25


def test_an_integer_below_its_minimum_names_the_bound() -> None:
    with pytest.raises(SettingError, match="at least 10"):
        coerce(setting(), 5)


def test_an_integer_above_its_maximum_names_the_bound() -> None:
    with pytest.raises(SettingError, match="at most 500"):
        coerce(setting(), 5000)


def test_a_bound_reads_as_a_whole_number() -> None:
    """`at least 10.0` in a sentence about rows reads as a defect."""
    with pytest.raises(SettingError, match=r"at least 10\b"):
        coerce(setting(), 1)


def test_a_boolean_is_not_an_integer() -> None:
    with pytest.raises(SettingError, match="whole number"):
        coerce(setting(), True)


def test_text_is_not_an_integer() -> None:
    with pytest.raises(SettingError, match="whole number"):
        coerce(setting(), "25")


def test_the_error_carries_the_key_it_is_about() -> None:
    """So an API error about one key in a batch says which one."""
    with pytest.raises(SettingError) as raised:
        coerce(setting(), 5)
    assert raised.value.key == "grid.pageSize"


def _theme() -> SettingDefinition:
    return setting(
        "ui.theme",
        category=Category.APPEARANCE,
        data_type=DataType.ENUM,
        default="system",
        options=("system", "light", "dark"),
        minimum=None,
        maximum=None,
    )


def test_an_enum_value_outside_its_options_lists_them() -> None:
    with pytest.raises(SettingError, match="system, light, dark"):
        coerce(_theme(), "mauve")


def test_a_boolean_setting_takes_only_a_boolean() -> None:
    switch = setting("grid.paginationEnabled", data_type=DataType.BOOLEAN, default=True,
                     minimum=None, maximum=None)
    assert coerce(switch, False) is False
    with pytest.raises(SettingError, match="true or false"):
        coerce(switch, "yes")


def test_a_string_list_accepts_a_json_list_and_a_tuple() -> None:
    """A row read out of jsonb is a list; a default round-tripped is a tuple."""
    options = setting(
        "grid.pageSizeOptions",
        data_type=DataType.STRING_LIST,
        default=("10", "25", "50", "100", "250"),
        minimum=None,
        maximum=None,
    )
    assert coerce(options, ["10", "25"]) == ("10", "25")
    assert coerce(options, ("10", "25")) == ("10", "25")
    with pytest.raises(SettingError, match="list of text values"):
        coerce(options, [10, 25])


def test_a_decimal_accepts_a_whole_number() -> None:
    scale = setting(
        "accessibility.fontScale",
        category=Category.ACCESSIBILITY,
        data_type=DataType.DECIMAL,
        default=1.0,
        minimum=0.8,
        maximum=2.0,
    )
    assert coerce(scale, 1) == 1.0
    assert coerce(scale, 1.25) == 1.25
    with pytest.raises(SettingError, match="at most 2"):
        coerce(scale, 3)


def test_valid_reports_without_raising() -> None:
    assert valid(setting(), 25) is True
    assert valid(setting(), 5) is False


def test_a_person_may_not_override_an_organisation_setting() -> None:
    """The brief's mandatory scenario 9."""
    with pytest.raises(ScopeRefused, match="cannot be overridden by one person"):
        check_writable(setting(scope=Scope.GLOBAL_ORG, user_visible=False), Scope.GLOBAL_ORG_USER)


def test_an_organisation_may_not_modify_a_platform_setting() -> None:
    """The brief's mandatory scenario 10."""
    with pytest.raises(ScopeRefused, match="cannot be changed here"):
        check_writable(setting(scope=Scope.GLOBAL_ONLY, user_visible=False), Scope.GLOBAL_ORG)


def test_a_permitted_write_is_silent() -> None:
    check_writable(setting(), Scope.GLOBAL_ORG_USER)
    check_writable(setting(), Scope.GLOBAL_ORG)


def test_a_scope_refusal_is_a_setting_error_too() -> None:
    """So one `except` clause can catch both, and the API can still tell them
    apart to answer 403 rather than 422."""
    assert issubclass(ScopeRefused, SettingError)
