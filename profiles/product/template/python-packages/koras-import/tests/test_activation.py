"""The activation rule: off unless explicitly on, for every input that is not an "on"."""

from __future__ import annotations

import pytest
from koras_import import ACTIVATION_ON, IMPORTS_ENABLED_SETTING, parse_import_activation

OFF = ["", "   ", "false", "False", "0", "no", "off", "garbage", "tru", "truee", "2", "null"]
ON = ["true", "TRUE", " True ", "1", "yes", "on"]


@pytest.mark.parametrize("value", OFF)
def test_every_unrecognised_string_is_off(value: str) -> None:
    assert parse_import_activation(value) is False


@pytest.mark.parametrize("value", ON)
def test_only_an_explicit_on_is_on(value: str) -> None:
    assert parse_import_activation(value) is True


@pytest.mark.parametrize("value", [None, 0, 1, 2.5, [], {}, b"true", object()])
def test_a_non_string_non_bool_is_off(value: object) -> None:
    assert parse_import_activation(value) is False


def test_booleans_pass_through() -> None:
    assert parse_import_activation(True) is True
    assert parse_import_activation(False) is False


def test_the_vocabulary_is_closed() -> None:
    assert ACTIVATION_ON == {"true", "1", "yes", "on"}
    assert IMPORTS_ENABLED_SETTING == "IMPORTS_ENABLED"
