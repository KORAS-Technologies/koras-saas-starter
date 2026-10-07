# ruff: noqa: ANN001, ANN003, ANN201, ANN202, ANN401, E501, S101, E402
"""Release, end to end, against everything real (ADR 0013, layer 4).

`test_scan_orchestration_real.py` takes an upload through finalization, the hand-off and the
scan and checks the verdict it leaves. This takes the same chain one step further, to the thing
the chain exists for: **who can read the bytes**. A real PostgreSQL with row-level security forced,
a real S3-compatible store, a real clamd, the real finalizer, the real `file.scan` job and the
real release gate, and a signed URL fetched over HTTP from the store.

* before the verdict the gate refuses and signs nothing; after a clean one it releases, and the URL
  it signs serves exactly the bytes that were uploaded;
* EICAR is refused as quarantined, and no URL exists for it;
* a clean file that is later found infected stops releasing the moment the verdict commits;
* another tenant can not release a file, and a *row of one tenant pointed at another tenant's real,
  clean, final object* releases nothing -- whatever the verdict the row carries.

Needs a database (`E2E_DATABASE_URL`), a store (`STORAGE_*`) and a scanner (`E2E_CLAMD_HOST`). It is
generated only into a product with `secure_files`, where the generator-integration workflow runs it
against all three and fails on any skip.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

DATABASE_URL = os.environ.get("E2E_DATABASE_URL", "")
if DATABASE_URL:
    os.environ["DATABASE_URL"] = DATABASE_URL
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

STORE_ENV = ("STORAGE_ENDPOINT", "STORAGE_BUCKET", "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL
    or not all(os.environ.get(n) for n in STORE_ENV)
    or not os.environ.get("E2E_CLAMD_HOST"),
    reason="needs a database (E2E_DATABASE_URL), a store (STORAGE_*) and a scanner (E2E_CLAMD_HOST)",
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
pytest.importorskip("koras_worker")
from eicar_support import materialize  # noqa: E402
from koras_api.core.file_release_gate import require_releasable  # noqa: E402
from koras_worker.scanning import commit_infected  # noqa: E402
from test_scan_orchestration_real import CSV, Chain, chain, queue  # noqa: E402
from test_scan_runtime_real import AS_TENANT, engine  # noqa: E402

assert chain and engine and queue  # re-exported fixtures


async def _ask(chain: Chain, file_id: str, *, as_tenant: str | None = None):
    """The gate, asked as the restricted role with that tenant's session bound."""
    tenant = as_tenant or chain.tenant
    async with async_sessionmaker(chain.engine, expire_on_commit=False)() as session:
        await session.execute(AS_TENANT, {"tenant_id": tenant})
        return await require_releasable(session, tenant, file_id, actor_id="u", consumer="download")


async def _refused(chain: Chain, file_id: str, *, as_tenant: str | None = None) -> HTTPException:
    with pytest.raises(HTTPException) as caught:
        await _ask(chain, file_id, as_tenant=as_tenant)
    return caught.value


def _served(chain: Chain, key: str) -> bytes:
    url = chain.store.presign_download(key, "a.csv", 60)
    answer = httpx.get(url, timeout=30)
    assert answer.status_code == 200, answer.text
    return answer.content


async def test_a_file_is_refused_until_the_scanner_says_clean_and_then_serves_its_bytes(
    chain: Chain,
) -> None:
    file_id, incoming = await chain.upload(CSV)
    # An upload that has not been finalized: an incoming key, no verdict.
    early = await _refused(chain, file_id)
    assert (early.status_code, early.detail["code"]) == (409, "file_scan_pending")

    await chain.finalize(file_id)
    # Finalized is readable *by the scanner*; it is not a release.
    pending = await _refused(chain, file_id)
    assert (pending.status_code, pending.detail["code"]) == (409, "file_scan_pending")

    assert (await chain.run_job(file_id))["status"] == "clean"
    row = await _ask(chain, file_id)
    assert str(row.id) == file_id and row.storage_key != incoming
    assert _served(chain, row.storage_key) == CSV


async def test_eicar_is_refused_as_quarantined_and_no_url_exists_for_it(chain: Chain) -> None:
    file_id, _ = await chain.upload(materialize(), "text/plain", name="a.txt")
    await chain.finalize(file_id)
    assert (await chain.run_job(file_id))["status"] == "infected"
    refused = await _refused(chain, file_id)
    assert (refused.status_code, refused.detail["code"]) == (403, "file_quarantined")
    assert "eicar" not in str(refused.detail).lower()


async def test_a_clean_file_found_infected_later_stops_releasing_when_the_verdict_commits(
    chain: Chain,
) -> None:
    file_id, _ = await chain.upload(CSV)
    await chain.finalize(file_id)
    assert (await chain.run_job(file_id))["status"] == "clean"
    assert str((await _ask(chain, file_id)).id) == file_id

    async with async_sessionmaker(chain.engine, expire_on_commit=False)() as session:
        await commit_infected(session, tenant_id=chain.tenant, file_id=file_id)

    refused = await _refused(chain, file_id)
    assert (refused.status_code, refused.detail["code"]) == (403, "file_quarantined")


async def test_another_tenant_cannot_release_a_clean_file(chain: Chain, engine, queue) -> None:
    file_id, _ = await chain.upload(CSV)
    await chain.finalize(file_id)
    assert (await chain.run_job(file_id))["status"] == "clean"
    other = Chain(engine, queue)
    try:
        refused = await _refused(chain, file_id, as_tenant=other.tenant)
        assert (refused.status_code, refused.detail["code"]) == (404, "file_not_found")
    finally:
        other.clean_up()


async def test_a_row_pointed_at_another_tenants_clean_object_releases_nothing(
    chain: Chain, engine, queue
) -> None:
    """The row is this tenant's and says `clean`; the object it names is another tenant's, real,
    clean and final (its own row gone, because a key is unique). Nothing about the verdict makes
    it this tenant's to read."""
    mine, _ = await chain.upload(CSV)
    await chain.finalize(mine)
    assert (await chain.run_job(mine))["status"] == "clean"

    theirs = Chain(engine, queue)
    try:
        their_file, _ = await theirs.upload(b"name,amount\nsecret,1\n")
        await theirs.finalize(their_file)
        assert (await theirs.run_job(their_file))["status"] == "clean"
        their_key = (await theirs.row(their_file))["storage_key"]
        assert f"tenants/{theirs.tenant}/" in their_key

        # A key is unique across the table, so this tenant's row can only be pointed at an object
        # whose own row is gone: their row is deleted (the object stays in the store), and then
        # this tenant's clean row is pointed at it.
        async with async_sessionmaker(chain.engine, expire_on_commit=False)() as session:
            await session.execute(AS_TENANT, {"tenant_id": theirs.tenant})
            await session.execute(
                text("delete from public.files where id = cast(:f as uuid)"), {"f": their_file}
            )
            await session.commit()
            await session.execute(AS_TENANT, {"tenant_id": chain.tenant})
            await session.execute(
                text("update public.files set storage_key = :k where id = cast(:f as uuid)"),
                {"k": their_key, "f": mine},
            )
            await session.commit()
        assert their_key in theirs.keys(), "their object is still there, real, final and scanned"

        refused = await _refused(chain, mine)
        assert (refused.status_code, refused.detail["code"]) == (409, "file_scan_pending")
        # Nothing was served: the signed URL for it was never made.
        assert (await chain.row(mine))["scan_status"] == "clean", "the row still says so"
    finally:
        theirs.clean_up()


async def test_a_clean_row_with_no_scanner_stamp_releases_nothing(chain: Chain) -> None:
    file_id, _ = await chain.upload(CSV)
    await chain.finalize(file_id)
    assert (await chain.run_job(file_id))["status"] == "clean"
    async with async_sessionmaker(chain.engine, expire_on_commit=False)() as session:
        await session.execute(AS_TENANT, {"tenant_id": chain.tenant})
        await session.execute(
            text("update public.files set scan_object_etag = null where id = cast(:f as uuid)"),
            {"f": file_id},
        )
        await session.commit()
    refused = await _refused(chain, file_id)
    assert (refused.status_code, refused.detail["code"]) == (409, "file_scan_pending")
