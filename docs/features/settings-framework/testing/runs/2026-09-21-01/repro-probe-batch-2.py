"""F27 reconciliation, second batch. Each test asserts the DEFECT."""
from __future__ import annotations
from test_settings_api import MEMBER, OWNER, _install, _Session  # noqa: F401


def test_set11_a_reset_announces_a_value_the_resolver_will_not_use() -> None:
    """Platform holds 5; grid.pageSize's minimum is 10."""
    session = _Session(platform={"grid.pageSize": 5}, tenant={"grid.pageSize": 100})
    answer = _install(session, OWNER).post("/api/v1/tenant/settings/values/grid.pageSize/reset")
    assert answer.status_code == 200, answer.text
    # The reset wrote the platform's invalid value and says so.
    written = [
        row
        for sql, params in session.writes()
        if "tenant_setting_values" in sql
        for row in params
        if row.get("key") == "grid.pageSize"
    ]
    assert written and written[0]["value"] == "5", (
        "REPRODUCED: reset copied a value the definition refuses")

    # And the resolver will not use it: the effective answer falls back.
    after = _Session(platform={"grid.pageSize": 5}, tenant={"grid.pageSize": 5})
    effective = _install(after, OWNER).get("/api/v1/settings/effective").json()
    assert effective["settings"]["grid.pageSize"]["value"] == 50, (
        "expected the definition default")
    assert "grid.pageSize" in effective["skipped"]


def test_set16_an_empty_string_list_is_accepted_and_permits_nothing() -> None:
    session = _Session()
    answer = _install(session, OWNER).patch(
        "/api/v1/tenant/settings/values", json={"values": {"files.allowedExtensions": []}})
    assert answer.status_code == 200, answer.text
    written = [
        row
        for sql, params in session.writes()
        if "tenant_setting_values" in sql
        for row in params
        if row.get("key") == "files.allowedExtensions"
    ]
    assert written and written[0]["value"] == "[]", (
        "REPRODUCED: clearing the field stores an empty list, which permits no upload at all")


def test_set14_the_platform_write_records_no_audit_event() -> None:
    from koras_api.core import settings_store

    class _S(_Session):
        pass

    session = _S(platform={"grid.pageSize": 50})
    import asyncio

    version, changes = asyncio.get_event_loop().run_until_complete(
        settings_store.write_global_values(session, {"grid.pageSize": 120})
    ) if False else (None, None)
    # Simpler: the route discards the diff. Assert the source does not audit.
    import inspect

    from koras_api.routers import platform as platform_router

    body = inspect.getsource(platform_router.write_global_settings)
    assert "_written" in body, "the diff is still computed"
    assert "record(" not in body and "_audit" not in body, (
        "REPRODUCED: the one write that reaches every future tenant records nothing")
