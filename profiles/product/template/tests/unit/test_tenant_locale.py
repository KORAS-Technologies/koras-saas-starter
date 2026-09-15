"""The language a member keeps, and the one a tenant keeps for its members.

Two writes and the read that carries both back, asked of the app with the
tenant and the session replaced. What is tested is the boundary the router
owns: that a value outside the catalogues is refused before anything is
written, that the tenant default needs `settings.manage` and the personal
choice does not, that the statements key on the resolved context rather than
on anything in the body, and that the read reports both values. Whether the
policies then admit the statement is the row-level security suite's claim
(`supabase/tests/160_member_preferences_isolation.sql`), not this file's.
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


class _Result:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    def first(self) -> tuple[Any, ...] | None:
        return self._row


class _Session:
    """Answers the settings read from one row and records every write."""

    def __init__(self, row: tuple[Any, ...] | None = None) -> None:
        self.row = row
        self.statements: list[tuple[str, dict[str, Any]]] = []
        self.commits = 0

    async def execute(self, statement: object, parameters: dict[str, Any]) -> _Result:
        sql = " ".join(str(statement).split())
        self.statements.append((sql, parameters))
        return _Result(self.row if sql.startswith("select") else None)

    async def commit(self) -> None:
        self.commits += 1

    def writes(self) -> list[tuple[str, dict[str, Any]]]:
        return [(sql, params) for sql, params in self.statements if sql.startswith("insert")]


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


OWNER = frozenset({OrganizationRole.OWNER})
MEMBER = frozenset({OrganizationRole.MEMBER})
BILLING = frozenset({OrganizationRole.BILLING_ADMIN})


def test_every_route_needs_a_verified_caller() -> None:
    app.dependency_overrides.clear()
    client = TestClient(app)
    assert client.get("/api/v1/tenant/settings").status_code in (401, 403)
    assert client.put("/api/v1/me/locale", json={"locale": "de"}).status_code in (401, 403)
    assert client.put("/api/v1/tenant/settings/locale", json={"locale": "de"}).status_code in (
        401,
        403,
    )


def test_the_read_carries_the_tenant_default_and_the_callers_own_choice() -> None:
    session = _Session(row=("Alpha", "alpha", {"colour": "#123456"}, {}, "de", "es"))
    answer = _install(session, MEMBER).get("/api/v1/tenant/settings")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["locale"] == "de"
    assert body["member_locale"] == "es"
    assert body["branding"] == {"colour": "#123456"}
    # The preference is joined on the verified subject, never on a parameter
    # the caller supplied: the body has no place to name one.
    sql, params = session.statements[0]
    assert "public.member_preferences" in sql
    assert params == {"tenant_id": TENANT, "user_id": SUBJECT}


def test_a_tenant_that_has_configured_nothing_has_no_languages_either() -> None:
    session = _Session(row=("Alpha", "alpha", {}, {}, None, None))
    body = _install(session, MEMBER).get("/api/v1/tenant/settings").json()
    assert body["locale"] is None and body["member_locale"] is None


def test_a_member_keeps_their_own_choice() -> None:
    session = _Session()
    answer = _install(session, MEMBER).put("/api/v1/me/locale", json={"locale": "de"})
    assert answer.status_code == 204, answer.text
    assert session.commits == 1
    [(sql, params)] = session.writes()
    assert sql.startswith("insert into public.member_preferences")
    assert "on conflict (tenant_id, user_id) do update" in sql
    assert params == {"tenant_id": TENANT, "user_id": SUBJECT, "locale": "de"}


def test_a_member_can_clear_their_choice() -> None:
    session = _Session()
    answer = _install(session, MEMBER).put("/api/v1/me/locale", json={"locale": None})
    assert answer.status_code == 204, answer.text
    [(_, params)] = session.writes()
    assert params["locale"] is None


def test_a_language_the_product_cannot_speak_is_refused_before_anything_is_written() -> None:
    for body in ({"locale": "fr"}, {"locale": "de-AT"}, {"locale": "<script>"}, {}):
        session = _Session()
        client = _install(session, OWNER)
        for path in ("/api/v1/me/locale", "/api/v1/tenant/settings/locale"):
            answer = client.put(path, json=body)
            expected = 204 if body == {} else 422
            assert answer.status_code == expected, (path, body, answer.text)
        if body != {}:
            assert session.writes() == []
            assert session.commits == 0


def test_the_tenant_default_needs_settings_manage() -> None:
    for roles in (MEMBER, BILLING):
        session = _Session()
        answer = _install(session, roles).put(
            "/api/v1/tenant/settings/locale", json={"locale": "de"}
        )
        assert answer.status_code == 403, answer.text
        assert session.writes() == []

    session = _Session()
    answer = _install(session, OWNER).put("/api/v1/tenant/settings/locale", json={"locale": "de"})
    assert answer.status_code == 204, answer.text
    assert session.commits == 1
    [(sql, params)] = session.writes()
    assert sql.startswith("insert into public.tenant_settings")
    assert "on conflict (tenant_id) do update" in sql
    assert params == {"tenant_id": TENANT, "locale": "de"}


def test_the_request_session_declares_the_subject() -> None:
    """The dependency that opens the session passes the verified subject on.

    The policy on `member_preferences` reads `current_user_id()`, so a session
    that declared the tenant alone would see and write no preference. This
    reads the declaration the product makes rather than the database's answer
    to it, which is the RLS suite's job.
    """
    from koras_tenant import Tenant

    assert Tenant(tenant_id=TENANT, user_id=SUBJECT).settings()["app.user_id"] == SUBJECT
    # No subject is the empty string, which `current_user_id()` reads as null,
    # rather than an absent key a pooled connection could carry over.
    assert Tenant(tenant_id=TENANT).settings()["app.user_id"] == ""
