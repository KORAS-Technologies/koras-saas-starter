"""What the settings routes answer, refuse, and record.

The resolver's own arithmetic is `koras-settings`' suite, with no database and
no HTTP. What is asserted here is the part only the API can get wrong: which
permission guards which scope, which refusal carries which code, that a write
is coerced before it reaches a statement, and that every change leaves a row in
the audit trail naming both halves.

The session is a fake that answers selects from a script and records writes.
It is not a database and proves nothing about row-level security -- that is
`supabase/tests/260`, `270` and `280`, which run as an unprivileged role
against a real Postgres.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from fastapi.testclient import TestClient  # noqa: E402
from koras_api.core.auth import require_auth  # noqa: E402
from koras_api.core.database import get_db  # noqa: E402
from koras_api.core.tenant import require_tenant  # noqa: E402
from koras_api.main import app  # noqa: E402
from koras_auth import JWTClaims  # noqa: E402
from koras_platform import OrganizationRole  # noqa: E402
from koras_tenant import TenantContext  # noqa: E402

app.state.redis = None

TENANT = "00000000-0000-0000-0000-000000000001"
SUBJECT = "user-1"

OWNER = frozenset({OrganizationRole.OWNER})
MEMBER = frozenset({OrganizationRole.MEMBER})


class _Result:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows

    def first(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:  # noqa: ANN401
        return self._rows[0][0]


class _Session:
    """Answers each select from the table it names, and records every write."""

    def __init__(
        self,
        *,
        platform: dict[str, Any] | None = None,
        tenant: dict[str, Any] | None = None,
        member: dict[str, Any] | None = None,
    ) -> None:
        self.platform = platform or {}
        self.tenant = tenant or {}
        self.member = member or {}
        self.statements: list[tuple[str, Any]] = []
        self.commits = 0

    async def execute(
        self,
        statement: object,
        # A dict for a single statement and a list of them for an executemany,
        # which is what the settings store issues. Narrower would be a lie.
        parameters: Any = None,  # noqa: ANN401
    ) -> _Result:
        sql = " ".join(str(statement).split())
        self.statements.append((sql, parameters))
        if not sql.startswith("select"):
            return _Result([])
        if "max(version)" in sql:
            return _Result([(0,)])
        if "public.global_settings" in sql:
            return _Result(list(self.platform.items()))
        if "public.member_setting_values" in sql:
            return _Result(list(self.member.items()))
        if "public.tenant_setting_values" in sql:
            return _Result(list(self.tenant.items()))
        return _Result([])

    async def commit(self) -> None:
        self.commits += 1

    def writes(self) -> list[tuple[str, Any]]:
        return [(sql, params) for sql, params in self.statements if sql.startswith("insert")]

    def audited(self) -> list[dict[str, Any]]:
        return [
            params
            for sql, params in self.statements
            if sql.startswith("insert") and "public.audit_events" in sql
        ]

    def deletes(self) -> list[tuple[str, Any]]:
        return [(sql, params) for sql, params in self.statements if sql.startswith("delete")]


def _install(session: _Session, roles: frozenset[OrganizationRole]) -> TestClient:
    async def _db() -> AsyncIterator[_Session]:
        yield session

    app.dependency_overrides[require_auth] = lambda: JWTClaims(
        sub=SUBJECT, roles=roles, organization_id="org-1"
    )
    app.dependency_overrides[require_tenant] = lambda: TenantContext(
        id=TENANT, slug="alpha", name="Alpha", organization_id="org-1", user_id=SUBJECT
    )
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


# ── the catalogue ────────────────────────────────────────────────────────────


def test_the_catalogue_is_published_with_the_metadata_a_control_needs() -> None:
    client = _install(_Session(), OWNER)
    answer = client.get("/api/v1/settings/definitions")
    assert answer.status_code == 200, answer.text

    by_key = {item["key"]: item for item in answer.json()}
    page_size = by_key["grid.pageSize"]
    assert page_size["data_type"] == "integer"
    assert page_size["default"] == 50
    assert (page_size["minimum"], page_size["maximum"]) == (10, 500)
    assert page_size["scope"] == "global_org_user"
    # A key, never a sentence: the browser renders it through its own catalogue.
    assert page_size["label_key"] == "settings.def.grid.pageSize.label"


def test_a_plain_member_can_read_the_catalogue() -> None:
    """The route needed `settings.read` until 2026-09-19, and that was total.

    `ROLE_PERMISSIONS[MEMBER]` does not carry `settings.read`; this route is the
    only source of the metadata the preferences page renders a control from;
    and the page swallows the failure. So every plain member -- most of every
    tenant -- opened their own preferences and was told the settings were
    unavailable. Found by the first independent review this framework had.

    What guards it is `TenantDep`: the catalogue is build metadata, identical
    for every customer and holding nobody's values, and a resolved tenant is
    the whole of the protection a list of setting names needs. The
    organisation's *configuration* is a different route and still requires the
    permission -- the case below.
    """
    answer = _install(_Session(), MEMBER).get("/api/v1/settings/definitions")
    assert answer.status_code == 200
    assert any(item["key"] == "grid.pageSize" for item in answer.json())


def test_reading_the_organisations_values_still_needs_the_read_permission() -> None:
    """The permission did not go away; it went where the customer data is."""
    answer = _install(_Session(), MEMBER).get("/api/v1/tenant/settings/values")
    assert answer.status_code == 403
    assert answer.json()["detail"]["code"] == "permission_missing"


def test_a_list_default_is_published_as_a_list() -> None:
    """JSON has no tuples, and a `STRING_LIST` default is one."""
    client = _install(_Session(), OWNER)
    by_key = {item["key"]: item for item in client.get("/api/v1/settings/definitions").json()}
    assert by_key["grid.pageSizeOptions"]["default"] == ["10", "25", "50", "100", "250"]


# ── what it resolves to ──────────────────────────────────────────────────────


def test_the_effective_answer_needs_no_permission_at_all() -> None:
    """The shell reads this before it paints, for every signed-in person.

    A permission here would mean a member without `settings.read` gets an
    unstyled page rather than a refusal.
    """
    session = _Session(tenant={"grid.pageSize": 100}, member={"grid.pageSize": 25})
    answer = _install(session, MEMBER).get("/api/v1/settings/effective")
    assert answer.status_code == 200, answer.text

    page_size = answer.json()["settings"]["grid.pageSize"]
    assert page_size["value"] == 25
    assert page_size["source"] == "user"
    # Both reset controls announce what they would restore, before being pressed.
    assert page_size["organization_value"] == 100
    assert page_size["can_override"] is True


def test_every_setting_is_answered_in_one_request() -> None:
    session = _Session()
    body = _install(session, MEMBER).get("/api/v1/settings/effective").json()
    assert len(body["settings"]) >= 32
    assert body["settings"]["grid.pageSize"]["source"] == "default"
    # Three selects for the whole catalogue, not one per key.
    selects = [sql for sql, _ in session.statements if sql.startswith("select")]
    assert len(selects) == 3


def test_a_value_that_no_longer_validates_is_reported_rather_than_raised() -> None:
    """A bound tightened in a deploy must not take the page down."""
    session = _Session(tenant={"grid.pageSize": 9999})
    body = _install(session, MEMBER).get("/api/v1/settings/effective").json()
    assert body["settings"]["grid.pageSize"]["value"] == 50
    assert body["skipped"] == ["grid.pageSize"]


# ── the organisation's values ────────────────────────────────────────────────


def test_changing_the_organisation_needs_settings_manage() -> None:
    session = _Session()
    answer = _install(session, MEMBER).patch(
        "/api/v1/tenant/settings/values", json={"values": {"grid.pageSize": 100}}
    )
    assert answer.status_code == 403
    assert answer.json()["detail"]["code"] == "permission_missing"
    # A denied configuration change is a fact about the system, and the one an
    # auditor asks about.
    [event] = session.audited()
    assert event["action"] == "settings.refused"
    assert event["outcome"] == "denied"


def test_an_administrator_changes_the_organisation_and_it_is_recorded() -> None:
    session = _Session(tenant={"grid.pageSize": 50})
    answer = _install(session, OWNER).patch(
        "/api/v1/tenant/settings/values", json={"values": {"grid.pageSize": 100}}
    )
    assert answer.status_code == 200, answer.text

    [(sql, params)] = [w for w in session.writes() if "tenant_setting_values" in w[0]]
    assert "on conflict (tenant_id, key) do update" in sql
    assert params == [{"tenant_id": TENANT, "key": "grid.pageSize", "value": "100"}]

    [event] = session.audited()
    assert event["action"] == "settings.tenant_changed"
    assert event["target_id"] == "grid.pageSize"
    # Both halves. A history that records only the new value answers the
    # question the settings page already answers.
    assert '"before": 50' in event["details"]
    assert '"after": 100' in event["details"]


def test_a_value_the_definition_refuses_is_422_and_writes_nothing() -> None:
    session = _Session()
    answer = _install(session, OWNER).patch(
        "/api/v1/tenant/settings/values", json={"values": {"grid.pageSize": 5}}
    )
    assert answer.status_code == 422
    assert answer.json()["detail"]["code"] == "setting_value_invalid"
    assert "at least 10" in answer.json()["detail"]["message"]
    assert session.writes() == []


def test_a_key_nobody_declared_is_404_rather_than_ignored() -> None:
    """Refused, not dropped.

    A write that silently ignored an unknown key would answer 200 to a request
    that changed nothing, and the sender would have no way to tell.
    """
    session = _Session()
    answer = _install(session, OWNER).patch(
        "/api/v1/tenant/settings/values", json={"values": {"grid.pagesize": 100}}
    )
    assert answer.status_code == 404
    assert answer.json()["detail"]["code"] == "setting_not_found"
    assert session.writes() == []


def test_an_organisation_cannot_change_a_setting_only_the_platform_holds() -> None:
    """The brief's mandatory scenario 10, at the route.

    No `GLOBAL_ONLY` setting ships today, so this proves the refusal with the
    catalogue as it is: reset refuses a key the organisation holds no value
    for, by the same check. When a platform-only setting is added, the same
    branch answers for it.
    """
    session = _Session()
    answer = _install(session, OWNER).post(
        "/api/v1/tenant/settings/values/grid.nothing/reset"
    )
    assert answer.status_code == 404
    assert answer.json()["detail"]["code"] == "setting_not_found"


def test_resetting_copies_the_platform_value_rather_than_deleting_the_row() -> None:
    """The control that looks safest is the one that could undo the feature.

    Deleting would make every later read fall through to whatever the platform
    holds then, and keep doing so as it changed -- the dynamic inheritance the
    snapshot exists to prevent.
    """
    session = _Session(platform={"grid.pageSize": 75}, tenant={"grid.pageSize": 100})
    answer = _install(session, OWNER).post("/api/v1/tenant/settings/values/grid.pageSize/reset")
    assert answer.status_code == 200, answer.text

    assert session.deletes() == []
    [(_, params)] = [w for w in session.writes() if "tenant_setting_values" in w[0]]
    assert params == [{"tenant_id": TENANT, "key": "grid.pageSize", "value": "75"}]
    assert session.audited()[0]["action"] == "settings.tenant_reset"


# ── a person's own values ────────────────────────────────────────────────────


def test_a_person_needs_no_permission_to_decide_for_themselves() -> None:
    session = _Session()
    answer = _install(session, MEMBER).patch(
        "/api/v1/me/settings", json={"values": {"grid.pageSize": 25}}
    )
    assert answer.status_code == 200, answer.text
    [(_, params)] = [w for w in session.writes() if "member_setting_values" in w[0]]
    assert params == [
        {"tenant_id": TENANT, "user_id": SUBJECT, "key": "grid.pageSize", "value": "25"}
    ]
    assert session.audited()[0]["action"] == "settings.member_changed"


def test_a_person_cannot_override_what_the_organisation_decides() -> None:
    """The brief's mandatory scenario 9, at the route."""
    session = _Session()
    answer = _install(session, OWNER).patch(
        "/api/v1/me/settings", json={"values": {"files.maxUploadSizeMb": 500}}
    )
    assert answer.status_code == 403
    assert answer.json()["detail"]["code"] == "setting_scope_refused"
    assert session.writes() == []


def test_clearing_a_personal_value_removes_the_row() -> None:
    """Where the organisation's reset is a copy, a person's is a delete.

    "I no longer want a preference" means the organisation's value should
    answer, now and as it changes -- which only an absent row expresses.
    """
    session = _Session(member={"grid.pageSize": 25})
    answer = _install(session, MEMBER).delete("/api/v1/me/settings/grid.pageSize")
    assert answer.status_code == 204, answer.text
    [(sql, params)] = session.deletes()
    assert "public.member_setting_values" in sql
    assert params == {"tenant_id": TENANT, "user_id": SUBJECT, "key": "grid.pageSize"}


def test_clearing_something_nobody_set_is_not_an_error_and_records_nothing() -> None:
    session = _Session()
    answer = _install(session, MEMBER).delete("/api/v1/me/settings/grid.pageSize")
    assert answer.status_code == 204, answer.text
    assert session.audited() == []


def test_clearing_a_setting_no_person_may_hold_is_refused() -> None:
    session = _Session()
    answer = _install(session, OWNER).delete("/api/v1/me/settings/files.maxUploadSizeMb")
    assert answer.status_code == 403
    assert answer.json()["detail"]["code"] == "setting_scope_refused"
