"""Which rung answers, and the scenario the whole feature exists for.

Every one of the brief's resolution scenarios is a call to `resolve_all` with
different mappings. That is the payoff of a resolver with no I/O: "an existing
organisation is unaffected by a later platform change" is two calls with the
same organisation mapping and different global ones, and it needs no database,
no tenant and no fixture.
"""

from __future__ import annotations

from collections.abc import Mapping

from koras_settings import (
    Resolution,
    Scope,
    SettingsRegistry,
    Source,
    build_catalogue,
    resolve_all,
)
from support import setting

CATALOGUE = build_catalogue([setting()])
NOTHING: Mapping[str, object] = {}


def _resolve(
    *,
    global_values: Mapping[str, object] | None = None,
    organization_values: Mapping[str, object] | None = None,
    member_values: Mapping[str, object] | None = None,
    catalogue: SettingsRegistry | None = None,
) -> Resolution:
    return resolve_all(
        catalogue or CATALOGUE,
        global_values=global_values or NOTHING,
        organization_values=organization_values or NOTHING,
        member_values=member_values or NOTHING,
    )


def test_nothing_set_anywhere_resolves_to_the_definitions_own_default() -> None:
    """Scenario 1, and the reason a product with no Control Plane works."""
    answer = _resolve().settings["grid.pageSize"]
    assert answer.value == 50
    assert answer.source is Source.DEFAULT


def test_a_platform_default_beats_the_definition() -> None:
    answer = _resolve(global_values={"grid.pageSize": 75}).settings["grid.pageSize"]
    assert answer.value == 75
    assert answer.source is Source.GLOBAL


def test_an_organisation_value_beats_the_platform() -> None:
    """Scenario 3."""
    answer = _resolve(
        global_values={"grid.pageSize": 75},
        organization_values={"grid.pageSize": 100},
    ).settings["grid.pageSize"]
    assert answer.value == 100
    assert answer.source is Source.ORGANIZATION


def test_a_persons_value_beats_the_organisation() -> None:
    """Scenario 4."""
    answer = _resolve(
        global_values={"grid.pageSize": 75},
        organization_values={"grid.pageSize": 100},
        member_values={"grid.pageSize": 25},
    ).settings["grid.pageSize"]
    assert answer.value == 25
    assert answer.source is Source.USER


def test_clearing_a_persons_value_falls_back_to_the_organisation() -> None:
    """Scenario 5. A reset removes the row, so the mapping simply lacks it."""
    answer = _resolve(
        organization_values={"grid.pageSize": 100},
        member_values={},
    ).settings["grid.pageSize"]
    assert answer.value == 100
    assert answer.source is Source.ORGANIZATION


def test_an_existing_organisation_is_unaffected_by_a_later_platform_change() -> None:
    """Scenario 7 — the property the whole feature exists to provide.

    The organisation was provisioned when the platform default was 50, so its
    snapshot holds 50. The platform later moves to 75. The organisation still
    reads 50, because a snapshot is a copy and not a link.
    """
    snapshot = {"grid.pageSize": 50}
    before = _resolve(global_values={"grid.pageSize": 50}, organization_values=snapshot)
    after = _resolve(global_values={"grid.pageSize": 75}, organization_values=snapshot)
    assert before.settings["grid.pageSize"].value == 50
    assert after.settings["grid.pageSize"].value == 50


def test_a_new_organisation_receives_the_latest_platform_default() -> None:
    """Scenario 8. Nothing snapshotted yet, so the platform value answers."""
    answer = _resolve(global_values={"grid.pageSize": 75}).settings["grid.pageSize"]
    assert answer.value == 75


def test_a_person_cannot_override_a_two_level_setting_even_if_a_row_exists() -> None:
    """A row written before the scope was narrowed must not start winning.

    The scope is consulted on the way out as well as on the way in, so a value
    that should never have been stored does not become authoritative because a
    guard was added after it.
    """
    catalogue = build_catalogue([setting(scope=Scope.GLOBAL_ORG, user_visible=False)])
    answer = _resolve(
        catalogue=catalogue,
        organization_values={"grid.pageSize": 100},
        member_values={"grid.pageSize": 25},
    ).settings["grid.pageSize"]
    assert answer.value == 100
    assert answer.can_override is False


def test_a_platform_only_setting_ignores_an_organisation_row() -> None:
    catalogue = build_catalogue([setting(scope=Scope.GLOBAL_ONLY, user_visible=False)])
    answer = _resolve(
        catalogue=catalogue,
        global_values={"grid.pageSize": 75},
        organization_values={"grid.pageSize": 100},
    ).settings["grid.pageSize"]
    assert answer.value == 75


def test_the_answer_says_what_a_reset_would_restore() -> None:
    """Both reset controls announce a value before they are pressed."""
    answer = _resolve(
        global_values={"grid.pageSize": 75},
        organization_values={"grid.pageSize": 100},
        member_values={"grid.pageSize": 25},
    ).settings["grid.pageSize"]
    assert answer.organization_value == 100
    assert answer.global_value == 75


def test_a_value_that_no_longer_validates_falls_through_and_is_reported() -> None:
    """A bound tightened in a deploy must not take the page down.

    The row was valid when it was written. Refusing to render is the wrong
    answer: the next rung down is a working page, and the skipped row is
    something an operator can find without a customer reporting it.
    """
    resolution = _resolve(
        global_values={"grid.pageSize": 75},
        organization_values={"grid.pageSize": 9999},
    )
    answer = resolution.settings["grid.pageSize"]
    assert answer.value == 75
    assert answer.source is Source.GLOBAL
    assert [skipped.key for skipped in resolution.skipped] == ["grid.pageSize"]
    assert resolution.skipped[0].source is Source.ORGANIZATION


def test_a_stored_key_nobody_declared_is_ignored() -> None:
    """A definition removed in a deploy leaves rows behind."""
    resolution = _resolve(organization_values={"grid.gone": 1})
    assert "grid.gone" not in resolution.settings


def test_a_null_row_is_the_same_as_no_row() -> None:
    answer = _resolve(
        global_values={"grid.pageSize": 75},
        organization_values={"grid.pageSize": None},
    ).settings["grid.pageSize"]
    assert answer.value == 75


def test_every_registered_setting_is_answered_in_one_call() -> None:
    """The brief asks for one request, not one per setting."""
    resolution = _resolve()
    assert set(resolution.settings) == {"grid.pageSize"}
    assert resolution.value("grid.pageSize") == 50
