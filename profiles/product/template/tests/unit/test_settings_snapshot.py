"""The copy a new tenant is given, and the promise that it stays theirs.

The database half of this is proved by `supabase/tests/270_*`; what is proved
here is the decision about *what* is copied, which is where the feature is
either right or subtly wrong.

No database. `seed_tenant`'s SQL is exercised against a real Postgres by the
generator's integration job; the choices it makes -- which definitions are
copied, what value each starts with, what a retry does -- are pure, and a test
that needed a container to assert them would be a test nobody runs locally.
"""

from __future__ import annotations

from typing import Any

from koras_api.core.settings_store import _starting_value, as_json
from koras_api.settings_catalogue import catalogue
from koras_settings import Scope, Source, resolve_all


def _snapshot(platform: dict[str, Any]) -> dict[str, Any]:
    """What `seed_tenant` would write, without a database to write it to.

    The same comprehension the store runs, kept in step by both reading the one
    catalogue and the one `_starting_value`.
    """
    return {
        definition.key: _starting_value(definition, platform)
        for definition in catalogue
        if definition.scope.admits_organization
    }


def test_every_applicable_definition_is_copied_not_only_the_platforms_rows() -> None:
    """The subtle one, and the reason the snapshot is not a `select into`.

    A key the platform has never set still gets a row, holding the definition's
    own default. Copying only the rows that exist would leave a gap the platform
    could fill later -- and filling it would change a tenant provisioned before,
    which is precisely what the snapshot exists to prevent.
    """
    snapshot = _snapshot({})
    applicable = {s.key for s in catalogue if s.scope.admits_organization}
    assert set(snapshot) == applicable
    assert snapshot["grid.pageSize"] == 50


def test_a_platform_value_beats_the_definitions_default() -> None:
    snapshot = _snapshot({"grid.pageSize": 75})
    assert snapshot["grid.pageSize"] == 75


def test_a_platform_row_holding_null_is_the_same_as_no_row() -> None:
    """A cleared default means "I have nothing to say", not "use null"."""
    assert _snapshot({"grid.pageSize": None})["grid.pageSize"] == 50


def test_a_platform_only_setting_is_never_copied() -> None:
    """A row nobody may change is a row every reader must learn to ignore."""
    platform_only = [s for s in catalogue if s.scope is Scope.GLOBAL_ONLY]
    snapshot = _snapshot({})
    for setting in platform_only:
        assert setting.key not in snapshot


def test_a_list_default_is_copied_as_a_list() -> None:
    """JSON has no tuples, and a definition's list default is one.

    Stored as a tuple's `repr` this would come back as a string that looks like
    a list, which every reader would then try to index.
    """
    snapshot = _snapshot({})
    assert snapshot["grid.pageSizeOptions"] == ["10", "25", "50", "100", "250"]
    assert as_json(snapshot["grid.pageSizeOptions"]) == '["10", "25", "50", "100", "250"]'


def test_a_boolean_is_written_as_json_and_not_as_python() -> None:
    """`str(True)` is `True`, which is not JSON and not storable as jsonb."""
    assert as_json(True) == "true"
    assert as_json(None) == "null"


def test_an_existing_tenant_is_unaffected_when_the_platform_moves() -> None:
    """The brief's scenario 7, at the level the product runs it.

    The tenant was seeded when the platform said 50. The platform moves to 75.
    The tenant still reads 50, because the resolver reads their row before it
    reads the platform's.
    """
    seeded = _snapshot({"grid.pageSize": 50})
    later = resolve_all(
        catalogue,
        global_values={"grid.pageSize": 75},
        organization_values=seeded,
        member_values={},
    )
    answer = later.settings["grid.pageSize"]
    assert answer.value == 50
    assert answer.source is Source.ORGANIZATION
    # And the tenant can still be told what resetting would give them.
    assert answer.global_value == 75


def test_a_tenant_seeded_today_takes_the_platforms_current_value() -> None:
    """The brief's scenario 8, and the other half of the same promise."""
    seeded = _snapshot({"grid.pageSize": 75})
    now = resolve_all(
        catalogue,
        global_values={"grid.pageSize": 75},
        organization_values=seeded,
        member_values={},
    )
    assert now.settings["grid.pageSize"].value == 75


def test_a_seeded_tenant_resolves_every_setting_from_its_own_rows() -> None:
    """Nothing falls through to the platform after a seed.

    Which is what makes the isolation total rather than partial: a tenant with
    a full set of rows cannot be moved by a platform change at all, and a tenant
    with a partial set could be moved for the keys it lacks.
    """
    resolution = resolve_all(
        catalogue,
        global_values={},
        organization_values=_snapshot({}),
        member_values={},
    )
    for definition in catalogue:
        answer = resolution.settings[definition.key]
        if definition.scope.admits_organization:
            assert answer.source is Source.ORGANIZATION, definition.key
        else:
            assert answer.source is Source.DEFAULT, definition.key
    assert not resolution.skipped


def test_the_snapshot_holds_nothing_the_definitions_would_refuse() -> None:
    """A seeded value must survive being read back.

    A default that no longer satisfies its own definition would be skipped by
    the resolver on every request -- silently, and for every tenant seeded since
    it changed.
    """
    resolution = resolve_all(
        catalogue,
        global_values={},
        organization_values=_snapshot({}),
        member_values={},
    )
    assert resolution.skipped == ()
