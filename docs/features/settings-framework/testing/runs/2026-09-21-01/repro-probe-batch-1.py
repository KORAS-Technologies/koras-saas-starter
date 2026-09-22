"""F27 reconciliation probes, batch 1 — RAN AGAINST 5e8fbc4, BEFORE ANY FIX.

Each test ASSERTS THE DEFECTIVE BEHAVIOUR, so a green run means the finding
still reproduces. All eight passed on 5e8fbc4 against a product generated from
that tree, using the product's own fixtures in `tests/unit/test_settings_api.py`.

Archived as evidence, not as a suite to keep running: `test_set07_*` is expected
to FAIL on the accepted tree, because SET-07 was fixed. Its replacement lives in
the product template as
`test_the_effective_route_withholds_the_platform_value_without_the_permission`.
"""

from __future__ import annotations

from test_settings_api import MEMBER, OWNER, _install, _Session  # noqa: F401


def test_set07_effective_discloses_org_and_global_to_a_caller_refused_by_the_sibling() -> None:
    session = _Session(platform={"grid.pageSize": 120}, tenant={"grid.pageSize": 77})
    client = _install(session, MEMBER)

    gated = client.get("/api/v1/tenant/settings/values")
    assert gated.status_code == 403, "the sibling route is supposed to refuse a plain member"

    open_route = client.get("/api/v1/settings/effective")
    assert open_route.status_code == 200
    page = open_route.json()["settings"]["grid.pageSize"]
    assert page["organization_value"] == 77, "REPRODUCED: org value disclosed without permission"
    assert page["global_value"] == 120, "REPRODUCED: platform value disclosed without permission"


def test_set08_a_system_setting_is_writable_by_a_tenant_administrator() -> None:
    """The shipped catalogue declares no system setting, so this substitutes two."""
    import koras_api.routers.settings as settings_router
    from koras_settings import (
        Category, DataType, Scope, SettingDefinition, Status, UiControl, build_catalogue,
    )

    system_only = SettingDefinition(
        key="probe.systemOnly", category=Category.GENERAL, data_type=DataType.BOOLEAN,
        default=False, scope=Scope.GLOBAL_ORG, label_key="x.l", description_key="x.d",
        ui=UiControl.TOGGLE, order=999, user_visible=False, system=True,
    )
    withdrawn = SettingDefinition(
        key="probe.retired", category=Category.GENERAL, data_type=DataType.BOOLEAN,
        default=False, scope=Scope.GLOBAL_ORG, label_key="x.l", description_key="x.d",
        ui=UiControl.TOGGLE, order=998, user_visible=False, status=Status.DEPRECATED,
    )
    original = settings_router.catalogue
    settings_router.catalogue = build_catalogue([system_only, withdrawn])
    try:
        listed = {d["key"] for d in _install(_Session(), OWNER).get(
            "/api/v1/settings/definitions").json()}
        assert "probe.systemOnly" not in listed, "a system setting is correctly hidden"
        assert "probe.retired" not in listed, "a deprecated setting is correctly hidden"

        for key in ("probe.systemOnly", "probe.retired"):
            session = _Session()
            answer = _install(session, OWNER).patch(
                "/api/v1/tenant/settings/values", json={"values": {key: True}})
            assert answer.status_code == 200, f"{key}: {answer.text}"
            wrote = [p for sql, p in session.writes() if "tenant_setting_values" in sql]
            assert wrote, f"REPRODUCED: {key} was written by a tenant administrator"
    finally:
        settings_router.catalogue = original


def test_set09_an_unbounded_string_is_accepted_on_a_route_needing_no_permission() -> None:
    from koras_api.settings_catalogue import catalogue

    text_key = next(
        (d.key for d in catalogue
         if str(d.data_type) == "string" and d.scope.admits_user and not d.system),
        None,
    )
    if text_key is None:
        import pytest
        pytest.skip("the shipped catalogue declares no user-writable string setting")

    session = _Session()
    huge = "A" * 1_000_000
    answer = _install(session, MEMBER).patch(
        "/api/v1/me/settings", json={"values": {text_key: huge}})
    assert answer.status_code == 200, answer.text
    stored = [p for sql, p in session.writes() if "member_setting_values" in sql]
    assert stored, "nothing was written"
    biggest = max(len(str(row["value"])) for row in stored[0])
    assert biggest > 900_000, "REPRODUCED: a one-megabyte value stored, no permission needed"


def test_set10_a_multi_key_write_commits_more_than_once() -> None:
    session = _Session(platform={}, tenant={})
    answer = _install(session, OWNER).patch(
        "/api/v1/tenant/settings/values",
        json={"values": {"grid.pageSize": 60, "ui.theme": "dark"}},
    )
    assert answer.status_code == 200, answer.text
    assert session.commits > 1, (
        f"REPRODUCED: {session.commits} commits for one logical write -- "
        "the values are committed when the first audit event flushes"
    )


def test_set17_a_scope_refusal_on_me_settings_records_nothing() -> None:
    from koras_api.settings_catalogue import catalogue

    org_only = next(
        (d.key for d in catalogue if not d.scope.admits_user and not d.system), None)
    assert org_only is not None, "the catalogue declares no organisation-only setting"

    session = _Session()
    answer = _install(session, MEMBER).patch(
        "/api/v1/me/settings", json={"values": {org_only: True}})
    assert answer.status_code == 403, answer.text
    assert session.audited() == [], (
        "REPRODUCED: the docstring says the refusal is recorded; nothing was")


def test_set18_skipped_reports_a_bare_key_and_not_which_rung_held_it() -> None:
    # 5 is below grid.pageSize's minimum of 10, so the resolver passes it over.
    session = _Session(tenant={"grid.pageSize": 5})
    answer = _install(session, OWNER).get("/api/v1/settings/effective")
    assert answer.status_code == 200
    skipped = answer.json()["skipped"]
    assert skipped == ["grid.pageSize"], skipped
    assert all(isinstance(entry, str) for entry in skipped), (
        "REPRODUCED: a bare key, so an operator cannot tell which rung holds the bad value")


def test_set19_an_unbounded_caller_supplied_key_reaches_the_audit_row() -> None:
    session = _Session()
    long_key = "z" * 5000
    answer = _install(session, MEMBER).patch(
        "/api/v1/tenant/settings/values", json={"values": {long_key: 1}})
    assert answer.status_code == 403, answer.text
    rows = session.audited()
    assert rows, "the refusal was not recorded at all"
    assert len(rows[0]["target_id"]) > 4000, (
        "REPRODUCED: a 5000-character caller-supplied key stored on the refusal path")


def test_set20_the_catalogue_does_not_publish_sensitive() -> None:
    answer = _install(_Session(), OWNER).get("/api/v1/settings/definitions")
    assert answer.status_code == 200
    assert all("sensitive" not in item for item in answer.json()), (
        "REPRODUCED: no surface can mask a field, because the flag is not published")
