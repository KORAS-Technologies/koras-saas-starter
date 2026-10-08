# ruff: noqa: ANN001, ANN201, ANN401, E501, S101
"""`GET /imports/sources/{file_id}` against a real PostgreSQL, as two tenants (GR-376).

The route reads one `public.files` row by id, and the id is the caller's. Nothing in
the statement names the tenant: what keeps another organisation's file out of the
answer is row-level security on the restricted application role, plus the tenant the
request session was opened under. A scripted session cannot show either, so this
module drives the real app with the real `get_db` and `require_tenant` (the tenant
resolved from the token's organisation through `public.tenants`), replacing only
`require_auth` with a `JWTClaims` of the exact type `verify_token` returns.

What it proves:

* each state the closed vocabulary names is what the row says, for the owner;
* another tenant's file, in **every** state, is answered `missing` -- the same status
  and the same bytes as an id that does not exist and as a malformed id, so the
  route cannot be used to learn that a file exists, what state it is in, or whose;
* the answer carries the one word and no file name, key, size, scan note or tenant;
* a caller without `imports.manage` gets the ordinary 403, identical for a real and
  a foreign file, and an unauthenticated one is not served;
* the route writes nothing: no file, run or audit row changes, in either tenant.

Skipped without a database, on the variable `playwright.config.ts` names. The role in
`E2E_DATABASE_URL` must be the restricted application role; the module refuses to run
as a superuser or a BYPASSRLS role, so a pass cannot be vacuous. CI runs it in the
`import-worker` job under a step that fails on a skip.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

DATABASE_URL = os.environ.get("E2E_DATABASE_URL", "")

if DATABASE_URL:
    os.environ["DATABASE_URL"] = DATABASE_URL
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
# A product generated with `secure_files` refuses to start without a scanner, a bucket and a
# queue. This read-only route touches none of them, so the values only have to be well formed.
os.environ.setdefault("FILE_SCAN_BACKEND", "clamd")
os.environ.setdefault("FILE_SCAN_CLAMD_HOST", "127.0.0.1")
os.environ.setdefault("FILE_SCAN_CLAMD_PORT", "3310")
os.environ.setdefault("STORAGE_ENDPOINT", "http://127.0.0.1:9")
os.environ.setdefault("STORAGE_BUCKET", "unused")
os.environ.setdefault("STORAGE_ACCESS_KEY", "unused")
os.environ.setdefault("STORAGE_SECRET_KEY", "unused")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")
os.environ.setdefault("CORS_ORIGINS", "[]")
# GR-369: every import route refuses unless the deployment activated imports.
os.environ["IMPORTS_ENABLED"] = "true"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="needs a real PostgreSQL; set E2E_DATABASE_URL (see playwright.config.ts)",
)

from fastapi.testclient import TestClient  # noqa: E402
from koras_api.core.auth import require_auth  # noqa: E402
from koras_api.core.settings import settings  # noqa: E402
from koras_api.main import app  # noqa: E402
from koras_auth import JWTClaims  # noqa: E402
from koras_platform import OrganizationRole  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

RUN = uuid.uuid4().hex[:8]
TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())
ORG = {TENANT_A: f"src-state-org-a-{RUN}", TENANT_B: f"src-state-org-b-{RUN}"}


def _claims(role: OrganizationRole, tenant: str, sub: str) -> JWTClaims:
    return JWTClaims(sub=sub, roles=frozenset({role}), organization_id=ORG[tenant])


OWNER_A = _claims(OrganizationRole.OWNER, TENANT_A, "src-owner-a")
OWNER_B = _claims(OrganizationRole.OWNER, TENANT_B, "src-owner-b")
MEMBER_A = _claims(OrganizationRole.MEMBER, TENANT_A, "src-member-a")
HEADERS = {"Authorization": "Bearer not-verified-here"}

NAME = "private-customer-list-xyz.xlsx"
NOTE = "Eicar-Signature-must-never-leak"

AS_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")
AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)

#: label -> (category, status, scan_status, scan_failure, size, the word the owner is told).
STATES: dict[str, tuple[str, str, str, str | None, int, str]] = {
    "ready_clean": ("imports", "ready", "clean", None, 100, "ready"),
    "pending_upload": ("imports", "pending", "pending", None, 100, "checking"),
    "ready_scan_pending": ("imports", "ready", "pending", None, 100, "checking"),
    "ready_integrity_hold": ("imports", "ready", "pending", "integrity_mismatch", 100, "held"),
    "infected": ("imports", "ready", "infected", None, 100, "rejected"),
    "quarantined": ("imports", "quarantined", "pending", None, 100, "rejected"),
    "other_shelf": ("documents", "ready", "clean", None, 100, "missing"),
}


def run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _session() -> tuple[Any, AsyncSession]:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    return engine, async_sessionmaker(engine, expire_on_commit=False)()


async def _seed_tenant(tenant: str, slug: str) -> None:
    engine, session = await _session()
    try:
        async with session:
            who = (
                await session.execute(
                    text(
                        "select rolsuper or rolbypassrls from pg_roles where rolname = current_user"
                    )
                )
            ).scalar_one()
            assert not who, "run this as the restricted application role, never a superuser"
            await session.execute(AS_PROVISIONING)
            await session.execute(
                text(
                    "insert into public.tenants (id, slug, name, zitadel_org_id, status) "
                    "values (cast(:t as uuid), :s, 'Source state', :o, 'active')"
                ),
                {"t": tenant, "s": slug, "o": ORG[tenant]},
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _seed_file(
    tenant: str,
    *,
    category: str,
    status: str,
    scan_status: str,
    scan_failure: str | None,
    size: int,
) -> str:
    file_id = str(uuid.uuid4())
    engine, session = await _session()
    try:
        async with session:
            await session.execute(AS_TENANT, {"tenant_id": tenant})
            await session.execute(
                text(
                    "insert into public.files (id, tenant_id, storage_key, name, size_bytes, "
                    "content_type, category, status, uploaded_by, scan_status, scan_failure, "
                    "scan_note, scan_object_etag) values (cast(:f as uuid), cast(:t as uuid), :k, :n, :size, "
                    "'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', "
                    ":category, :status, 'src-state', :scan_status, :failure, :note, 'etag-1')"
                ),
                {
                    "f": file_id,
                    "t": tenant,
                    "k": f"tenants/{tenant}/{category}/{file_id}/final/{uuid.uuid4()}/{NAME}",
                    "n": NAME,
                    "size": size,
                    "category": category,
                    "status": status,
                    "scan_status": scan_status,
                    "failure": scan_failure,
                    "note": NOTE,
                },
            )
            await session.commit()
    finally:
        await engine.dispose()
    return file_id


async def _footprint(tenant: str) -> dict[str, Any]:
    """What a read-only route must leave alone, as the tenant itself sees it."""
    engine, session = await _session()
    try:
        async with session:
            await session.execute(AS_TENANT, {"tenant_id": tenant})
            counts: dict[str, Any] = {}
            for table in ("files", "import_runs", "audit_events"):
                counts[table] = (
                    await session.execute(text(f"select count(*) from public.{table}"))  # noqa: S608
                ).scalar_one()
            counts["file_rows"] = sorted(
                tuple(map(str, r))
                for r in (
                    await session.execute(
                        text(
                            "select id, status, scan_status, scan_attempts, "
                            "coalesce(scan_failure,''), storage_key from public.files"
                        )
                    )
                ).all()
            )
            await session.rollback()
            return counts
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def seeded() -> dict[str, dict[str, str]]:
    run(_seed_tenant(TENANT_A, f"src-a-{RUN}"))
    run(_seed_tenant(TENANT_B, f"src-b-{RUN}"))
    files: dict[str, dict[str, str]] = {TENANT_A: {}, TENANT_B: {}}
    for tenant in (TENANT_A, TENANT_B):
        for label, (category, status, scan, failure, size, _word) in STATES.items():
            files[tenant][label] = run(
                _seed_file(
                    tenant,
                    category=category,
                    status=status,
                    scan_status=scan,
                    scan_failure=failure,
                    size=size,
                )
            )
    return files


@pytest.fixture(scope="module")
def client(seeded) -> Iterator[TestClient]:
    app.dependency_overrides[require_auth] = lambda: OWNER_A
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def as_(claims: JWTClaims) -> None:
    app.dependency_overrides[require_auth] = lambda: claims


def ask(client: TestClient, file_id: str):
    return client.get(f"/api/v1/imports/sources/{file_id}", headers=HEADERS)


def shape(answer) -> tuple[int, bytes]:
    """Everything a caller could compare between two answers."""
    return answer.status_code, answer.content


@pytest.mark.parametrize("label", list(STATES))
def test_01_the_owner_is_told_the_state_the_row_has(client: TestClient, seeded, label: str) -> None:
    as_(OWNER_A)
    answer = ask(client, seeded[TENANT_A][label])
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"state": STATES[label][5]}


@pytest.mark.parametrize("label", list(STATES))
def test_02_another_tenants_file_is_missing_in_every_state(
    client: TestClient, seeded, label: str
) -> None:
    """B asks about A's file, and A about B's: `missing`, for every state a file can be in."""
    as_(OWNER_B)
    cross = ask(client, seeded[TENANT_A][label])
    assert cross.status_code == 200, cross.text
    assert cross.json() == {"state": "missing"}, f"tenant B learned about tenant A's {label} file"
    as_(OWNER_A)
    reverse = ask(client, seeded[TENANT_B][label])
    assert reverse.json() == {"state": "missing"}, f"tenant A learned about tenant B's {label} file"


def test_03_a_foreign_file_is_indistinguishable_from_unknown_and_malformed(
    client: TestClient, seeded
) -> None:
    """The canonical non-disclosing answer: same status, same body, byte for byte."""
    as_(OWNER_B)
    unknown = shape(ask(client, str(uuid.uuid4())))
    malformed = shape(ask(client, "not-a-uuid"))
    assert unknown == malformed
    assert unknown[0] == 200 and json.loads(unknown[1]) == {"state": "missing"}
    for label, file_id in seeded[TENANT_A].items():
        assert shape(ask(client, file_id)) == unknown, f"foreign {label} differs from unknown"


def test_04_the_answer_is_the_one_word_and_names_nothing(client: TestClient, seeded) -> None:
    as_(OWNER_A)
    for label, file_id in seeded[TENANT_A].items():
        answer = ask(client, file_id)
        assert list(answer.json()) == ["state"], label
        for secret in (NAME, NOTE, file_id, TENANT_A, TENANT_B, "integrity_mismatch", "storage"):
            assert secret not in answer.text, f"{label}: the answer carried {secret!r}"
    as_(OWNER_B)
    for file_id in seeded[TENANT_A].values():
        body = ask(client, file_id).text
        for secret in (NAME, NOTE, file_id, TENANT_A):
            assert secret not in body


def test_05_without_imports_manage_the_answer_is_403_and_the_same_for_every_id(
    client: TestClient, seeded
) -> None:
    """A member holds neither the permission nor a right to learn whether a file exists."""
    as_(MEMBER_A)
    own = ask(client, seeded[TENANT_A]["ready_clean"])
    foreign = ask(client, seeded[TENANT_B]["ready_clean"])
    unknown = ask(client, str(uuid.uuid4()))
    assert own.status_code == 403, own.text
    assert shape(own) == shape(foreign) == shape(unknown)
    assert NAME not in own.text and '"state"' not in own.text


def test_06_an_unauthenticated_caller_is_not_served(client: TestClient, seeded) -> None:
    app.dependency_overrides.pop(require_auth, None)
    try:
        for file_id in (seeded[TENANT_A]["ready_clean"], str(uuid.uuid4())):
            answer = client.get(f"/api/v1/imports/sources/{file_id}")
            assert answer.status_code in (401, 403), answer.text
            assert '"state"' not in answer.text
    finally:
        as_(OWNER_A)


def test_07_with_imports_off_the_route_is_one_403_and_reveals_no_state(
    client: TestClient, seeded, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "imports_enabled", False)
    as_(OWNER_A)
    own = ask(client, seeded[TENANT_A]["ready_clean"])
    foreign = ask(client, seeded[TENANT_B]["ready_clean"])
    unknown = ask(client, str(uuid.uuid4()))
    assert own.status_code == 403, own.text
    assert shape(own) == shape(foreign) == shape(unknown)
    assert '"state"' not in own.text


def test_08_the_route_writes_nothing_in_either_tenant(client: TestClient, seeded) -> None:
    before = {t: run(_footprint(t)) for t in (TENANT_A, TENANT_B)}
    for claims in (OWNER_A, OWNER_B, MEMBER_A):
        as_(claims)
        for tenant in (TENANT_A, TENANT_B):
            for file_id in seeded[tenant].values():
                ask(client, file_id)
        ask(client, "not-a-uuid")
    after = {t: run(_footprint(t)) for t in (TENANT_A, TENANT_B)}
    assert json.dumps(after, sort_keys=True, default=str) == json.dumps(
        before, sort_keys=True, default=str
    ), "a read-only route changed rows"
    for tenant in (TENANT_A, TENANT_B):
        assert before[tenant]["import_runs"] == 0
        assert before[tenant]["files"] == len(STATES)


def test_09_the_tenant_comes_from_the_token_not_from_the_request(
    client: TestClient, seeded
) -> None:
    """A browser-supplied tenant hint is not authorization evidence: it changes nothing."""
    as_(OWNER_B)
    target = seeded[TENANT_A]["ready_clean"]
    for hint in ({"X-Tenant-Id": TENANT_A}, {"x-organization-id": ORG[TENANT_A]}):
        answer = client.get(f"/api/v1/imports/sources/{target}", headers={**HEADERS, **hint})
        assert answer.json() == {"state": "missing"}, hint
    answer = client.get(f"/api/v1/imports/sources/{target}?tenant_id={TENANT_A}", headers=HEADERS)
    assert answer.json() == {"state": "missing"}
