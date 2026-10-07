# ruff: noqa: ANN001, ANN201, ANN401, E501, S101
"""The release rule against a real PostgreSQL with row-level security on (`secure_files`).

A scripted session cannot show the things this rule rests on: that the SQL spelling
(`RELEASABLE_SQL`) and the Python predicate answer identically for every state the table can
hold -- every `status`, every `scan_status`, and every way a clean row's identity can be wrong --
that the gate reads through RLS and a tenant predicate so another tenant's file is simply not
there, that another tenant's object can never become releasable however a row is written, and
that a refusal's audit row is written under the tenant's own policies and carries no name, key or
scan note.

Skipped without a database, on the variable `playwright.config.ts` names. The role in
`E2E_DATABASE_URL` must be the restricted application role, not a superuser; the test refuses to
run as one. CI runs this module in a step that fails on a skip.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get("E2E_DATABASE_URL", "")

if DATABASE_URL:
    os.environ["DATABASE_URL"] = DATABASE_URL
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="needs a real PostgreSQL; set E2E_DATABASE_URL (see playwright.config.ts)",
)

from koras_api.core import file_release  # noqa: E402
from koras_api.core.file_release import RELEASABLE_SQL, releasable  # noqa: E402
from koras_api.core.file_release_gate import require_releasable  # noqa: E402

AS_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")
AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)

#: The `status` values a row can carry while it is still a file, crossed with every scan state.
STATUSES = ("pending", "ready", "quarantined")
SCANS = ("pending", "clean", "infected", "skipped")
NOTE = "Eicar-Signature-must-never-leak"
NAME = "private-name-xyz.pdf"
GENERATION = "2222222a-2222-4222-8222-22222222222b"


@pytest.fixture(autouse=True)
def _secure(monkeypatch: pytest.MonkeyPatch) -> None:
    """These are the capability's rule; a product generated with it has this constant True."""
    monkeypatch.setattr(file_release, "SECURE_FILES", True)


@pytest.fixture
async def engine():
    created = create_async_engine(DATABASE_URL)
    async with async_sessionmaker(created, expire_on_commit=False)() as probe:
        who = (
            await probe.execute(
                text("select rolsuper or rolbypassrls from pg_roles where rolname = current_user")
            )
        ).scalar_one()
        assert not who, "run this as the restricted application role, never a superuser"
    try:
        yield created
    finally:
        await created.dispose()


@pytest.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as opened:
        yield opened


async def _tenant(session: AsyncSession) -> str:
    tenant = str(uuid.uuid4())
    await session.execute(AS_PROVISIONING)
    await session.execute(
        text("insert into public.tenants (id, slug, name) values (cast(:t as uuid), :s, 'T')"),
        {"t": tenant, "s": f"rel-{tenant[:8]}"},
    )
    await session.commit()
    return tenant


def _final(tenant: str, file_id: str) -> str:
    return f"tenants/{tenant}/documents/{file_id}/final/{GENERATION}/a.pdf"


async def _file(
    session: AsyncSession,
    tenant: str,
    *,
    status: str,
    scan_status: str,
    key: str | None = None,
    etag: str | None = "etag-1",
) -> str:
    file_id = str(uuid.uuid4())
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    await session.execute(
        text(
            "insert into public.files (id, tenant_id, storage_key, name, size_bytes, content_type, "
            "category, status, uploaded_by, scan_status, scan_note, scan_object_etag) values "
            "(cast(:f as uuid), cast(:t as uuid), :k, :n, 10, 'application/pdf', 'documents', "
            ":status, 'u', :scan_status, :note, :etag)"
        ),
        {
            "f": file_id,
            "t": tenant,
            "k": key or _final(tenant, file_id),
            "n": NAME,
            "status": status,
            "scan_status": scan_status,
            "note": NOTE,
            "etag": etag,
        },
    )
    await session.commit()
    return file_id


async def _python_answer(session: AsyncSession, tenant: str, file_id: str) -> bool:
    """`releasable` asked of the stored row, the way the gate asks it."""
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    row = (
        await session.execute(
            text(
                "select status, scan_status, tenant_id::text as tenant_id, storage_key, "
                "scan_object_etag from public.files where id = cast(:f as uuid)"
            ),
            {"f": file_id},
        )
    ).one()
    return releasable(
        status=row.status,
        scan_status=row.scan_status,
        tenant_id=tenant,
        row_tenant_id=row.tenant_id,
        storage_key=row.storage_key,
        scan_object_etag=row.scan_object_etag,
    )


async def test_the_sql_and_python_spellings_agree_for_every_state_the_table_can_hold(
    session,
) -> None:
    tenant = await _tenant(session)
    other = await _tenant(session)
    expected: dict[str, bool] = {}
    for status in STATUSES:
        for scan_status in SCANS:
            file_id = await _file(session, tenant, status=status, scan_status=scan_status)
            expected[file_id] = await _python_answer(session, tenant, file_id)
    # A clean, ready row of the same tenant whose identity is wrong in each way a row can be.
    spoiled = {
        "another tenant's key": lambda fid: _final(other, fid),
        "an incoming key": lambda fid: f"tenants/{tenant}/documents/{fid}/incoming/{GENERATION}/a.pdf",
        "the pre-finalization shape": lambda fid: f"tenants/{tenant}/documents/{fid}/a.pdf",
        "an extra segment": lambda fid: f"tenants/{tenant}/documents/{fid}/final/{GENERATION}/x/a.pdf",
        "a generation that is not a uuid": lambda fid: f"tenants/{tenant}/documents/{fid}/final/g/a.pdf",
        "an upper-case generation": lambda fid: f"tenants/{tenant}/documents/{fid}/final/{GENERATION.upper()}/a.pdf",
        "an empty name": lambda fid: f"tenants/{tenant}/documents/{fid}/final/{GENERATION}/",
        "an empty category": lambda fid: f"tenants/{tenant}//{fid}/final/{GENERATION}/a.pdf",
    }
    for label, key_of in spoiled.items():
        file_id = str(uuid.uuid4())
        await session.execute(AS_TENANT, {"tenant_id": tenant})
        await session.execute(
            text(
                "insert into public.files (id, tenant_id, storage_key, name, size_bytes, "
                "content_type, category, status, uploaded_by, scan_status, scan_object_etag) values "
                "(cast(:f as uuid), cast(:t as uuid), :k, 'n', 10, 'application/pdf', 'documents', "
                "'ready', 'u', 'clean', 'etag-1')"
            ),
            {"f": file_id, "t": tenant, "k": key_of(file_id)},
        )
        await session.commit()
        expected[file_id] = await _python_answer(session, tenant, file_id)
        assert expected[file_id] is False, label
    for label, etag in (("no stamp", None), ("a blank stamp", "")):
        file_id = await _file(session, tenant, status="ready", scan_status="clean", etag=etag)
        expected[file_id] = await _python_answer(session, tenant, file_id)
        assert expected[file_id] is False, label
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    rows = await session.execute(
        text(f"select f.id::text, {RELEASABLE_SQL} as ok from public.files f")  # noqa: S608
    )
    in_sql = {row[0]: bool(row[1]) for row in rows.fetchall()}
    assert in_sql == expected
    assert sum(expected.values()) == 1, (
        "exactly one combination releases: ready + clean, on its own tenant's final key, stamped"
    )


async def test_the_gate_releases_a_ready_clean_file_and_nothing_else(session) -> None:
    tenant = await _tenant(session)
    clean = await _file(session, tenant, status="ready", scan_status="clean")
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    row = await require_releasable(session, tenant, clean, actor_id="u", consumer="download")
    assert str(row.id) == clean

    for scan_status, http, code in (
        ("pending", 409, "file_scan_pending"),
        ("skipped", 409, "file_scan_pending"),
        ("infected", 403, "file_quarantined"),
    ):
        refused = await _file(session, tenant, status="ready", scan_status=scan_status)
        await session.execute(AS_TENANT, {"tenant_id": tenant})
        with pytest.raises(HTTPException) as caught:
            await require_releasable(session, tenant, refused, actor_id="u", consumer="download")
        assert caught.value.status_code == http
        assert caught.value.detail["code"] == code


async def test_a_clean_row_pointed_at_another_tenants_object_is_never_released(session) -> None:
    """The row is this tenant's, its verdict is `clean`, its key is somebody else's object."""
    tenant = await _tenant(session)
    other = await _tenant(session)
    foreign_file = str(uuid.uuid4())
    pointed = await _file(
        session, tenant, status="ready", scan_status="clean", key=_final(other, foreign_file)
    )
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    with pytest.raises(HTTPException) as caught:
        await require_releasable(session, tenant, pointed, actor_id="u", consumer="download")
    assert caught.value.status_code == 409
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    (event,) = (
        await session.execute(
            text("select action, details::text from public.audit_events where target_id = :f"),
            {"f": pointed},
        )
    ).fetchall()
    assert event[0] == "storage.object.release_refused"
    assert json.loads(event[1]) == {"reason": "unknown", "consumer": "download"}
    assert other not in event[1]


async def test_a_clean_row_with_no_scanner_stamp_is_never_released(session) -> None:
    tenant = await _tenant(session)
    unstamped = await _file(session, tenant, status="ready", scan_status="clean", etag=None)
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    with pytest.raises(HTTPException) as caught:
        await require_releasable(session, tenant, unstamped, actor_id="u", consumer="download")
    assert caught.value.status_code == 409


async def test_a_refusal_is_audited_under_the_tenant_with_a_closed_reason_and_no_leak(
    session,
) -> None:
    tenant = await _tenant(session)
    pending = await _file(session, tenant, status="ready", scan_status="pending")
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    with pytest.raises(HTTPException):
        await require_releasable(session, tenant, pending, actor_id="user-1", consumer="download")
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    rows = (
        await session.execute(
            text(
                "select action, outcome, actor_id, target_id, details::text from public.audit_events "
                "where target_id = :f"
            ),
            {"f": pending},
        )
    ).fetchall()
    assert len(rows) == 1
    action, outcome, actor, target, details = rows[0]
    assert (action, outcome, actor, target) == (
        "storage.object.release_refused",
        "denied",
        "user-1",
        pending,
    )
    assert json.loads(details) == {"reason": "pending", "consumer": "download"}
    assert NOTE not in details
    assert NAME not in details
    assert "tenants/" not in details


async def test_another_tenants_file_is_not_found_and_leaves_no_refusal_event(session) -> None:
    owner = await _tenant(session)
    other = await _tenant(session)
    clean = await _file(session, owner, status="ready", scan_status="clean")
    pending = await _file(session, owner, status="ready", scan_status="pending")
    for target in (clean, pending):
        await session.execute(AS_TENANT, {"tenant_id": other})
        with pytest.raises(HTTPException) as caught:
            await require_releasable(session, other, target, actor_id="u", consumer="download")
        assert caught.value.status_code == 404
        assert caught.value.detail["code"] == "file_not_found"
    await session.execute(AS_TENANT, {"tenant_id": owner})
    leaked = (
        await session.execute(
            text("select count(*) from public.audit_events where target_id in (:a, :b)"),
            {"a": clean, "b": pending},
        )
    ).scalar_one()
    assert leaked == 0


async def test_asking_with_the_wrong_tenant_bound_still_cannot_see_the_row(session) -> None:
    """RLS, not only the predicate: the tenant id passed is the owner's, the session's is not."""
    owner = await _tenant(session)
    other = await _tenant(session)
    clean = await _file(session, owner, status="ready", scan_status="clean")
    await session.execute(AS_TENANT, {"tenant_id": other})
    with pytest.raises(HTTPException) as caught:
        await require_releasable(session, owner, clean, actor_id="u", consumer="download")
    assert caught.value.status_code == 404


async def test_a_missing_file_and_an_unconfirmed_upload_are_not_found(session) -> None:
    tenant = await _tenant(session)
    unconfirmed = await _file(session, tenant, status="pending", scan_status="pending")
    for target in (unconfirmed, str(uuid.uuid4()), "not-a-uuid"):
        await session.execute(AS_TENANT, {"tenant_id": tenant})
        with pytest.raises(HTTPException) as caught:
            await require_releasable(session, tenant, target, actor_id="u", consumer="download")
        assert caught.value.status_code == 404
