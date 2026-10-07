# ruff: noqa: ANN001, ANN201, ANN202, ANN401, E501, S101, E402
"""A whole `file.scan` run against a real PostgreSQL with row-level security on.

The unit suite proves the composition with an in-memory table. It cannot show
what only a server can: that the one read the runtime makes is valid SQL under
forced RLS as the restricted role, that another tenant's file id finds no row
for real, that the transitions' statements and the real audit sink commit a verdict with
its event as one transaction, and that two workers racing on one file leave it
`infected`. Object bytes and the scanner are still the deterministic fakes; the
database, the transitions and the audit sink are the real ones.

Skipped without a database, on the variable `playwright.config.ts` names. The
role must be the restricted application role; the test refuses to run as a
superuser.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get("E2E_DATABASE_URL", "")

if DATABASE_URL:
    os.environ["DATABASE_URL"] = DATABASE_URL
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="needs a real PostgreSQL; set E2E_DATABASE_URL (see playwright.config.ts)",
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
pytest.importorskip("koras_worker")
from koras_worker.scanning import (
    ObjectReader,
    ScanDisposition,
    ScanFailure,
    ScanOutcome,
    ScanResult,
    scan_file,
)
from object_support import FakeObjectSource, identity
from scanner_support import FakeScanner
from zip_support import Member, build_zip, real_docx, streamed_zip64_deflated

AS_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")
AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)
ISSUED = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
AFTER = ISSUED + timedelta(minutes=17)
CSV = b"name,amount\nacme,10\nglobex,20\n"
SIGNATURE = "Win.Test.EICAR_HDB-1"


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


def sessions(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(
    session: AsyncSession,
    body: bytes = CSV,
    *,
    content_type: str = "text/csv",
    tenant: str | None = None,
    **file: object,
) -> tuple[str, str]:
    """A tenant and a ready, pending file issued at ISSUED, written as provisioning.

    The key is the shape the finalizer writes (`.../final/<generation>/a.csv`), the only one the
    scanner reads. A test that needs another shape passes `storage_key`.
    """
    tenant = tenant or str(uuid.uuid4())
    file_id = str(uuid.uuid4())
    values: dict[str, object] = {
        "checksum_sha256": None,
        "verified": None,
        "created_at": ISSUED,
        "status": "ready",
        "scan_status": "pending",
    }
    values.update(file)
    key = values.pop("storage_key", None) or f"tenants/{tenant}/imports/{file_id}/final/{uuid.uuid4()}/a.csv"
    await session.execute(AS_PROVISIONING)
    await session.execute(
        text(
            "insert into public.tenants (id, slug, name) values (cast(:t as uuid), :s, 'T') "
            "on conflict (id) do nothing"
        ),
        {"t": tenant, "s": f"scan-{tenant[:8]}"},
    )
    await session.commit()
    await session.execute(AS_TENANT, {"tenant_id": tenant})
    await session.execute(
        text(
            "insert into public.files (id, tenant_id, storage_key, name, size_bytes, "
            "content_type, category, status, uploaded_by, scan_status, checksum_sha256, "
            "checksum_verified_at, created_at) values (cast(:f as uuid), cast(:t as uuid), :k, "
            "'a.csv', :size, :ct, 'imports', :status, 'u', :scan_status, :checksum_sha256, "
            ":verified, :created_at)"
        ),
        {
            "f": file_id,
            "t": tenant,
            "k": key,
            "size": len(body),
            "ct": content_type,
            **values,
        },
    )
    await session.commit()
    return tenant, file_id


def _source(body: bytes, tenant: str, file_id: str) -> FakeObjectSource:
    del tenant, file_id  # the fake answers for any key; the reference is validated separately
    return FakeObjectSource(stats=[identity(len(body))], body=body)


async def _scan(
    engine,
    tenant: str,
    file_id: str,
    body: bytes,
    scanner,
    *,
    at: datetime = AFTER,
    max_attempts: int = 12,
    as_tenant: str | None = None,
):
    async with sessions(engine)() as opened:
        return await scan_file(
            opened,
            tenant_id=as_tenant or tenant,
            file_id=file_id,
            reader=ObjectReader(_source(body, tenant, file_id), chunk_bytes=64, clock=lambda: at),
            scanner=scanner,
            max_attempts=max_attempts,
            now=at,
        )


async def _row(engine, tenant: str, file_id: str) -> dict[str, object]:
    async with sessions(engine)() as reader:
        await reader.execute(AS_TENANT, {"tenant_id": tenant})
        return dict(
            (
                await reader.execute(
                    text("select * from public.files where id = cast(:f as uuid)"), {"f": file_id}
                )
            )
            .mappings()
            .one()
        )


async def _audit(engine, tenant: str, file_id: str) -> list[tuple[str, str, dict]]:
    async with sessions(engine)() as reader:
        await reader.execute(AS_TENANT, {"tenant_id": tenant})
        rows = (
            await reader.execute(
                text(
                    "select action, outcome, details from public.audit_events "
                    "where target_id = :f order by created_at, id"
                ),
                {"f": file_id},
            )
        ).all()
    return [
        (r.action, r.outcome, r.details if isinstance(r.details, dict) else json.loads(r.details))
        for r in rows
    ]


class _NonReading:
    def __init__(self, result: ScanResult) -> None:
        self._result = result

    async def scan(self, source):
        return self._result

    async def ping(self) -> bool:
        return False


# =========================================================================================


async def test_a_benign_file_is_released_clean_with_its_scanned_event(engine, session) -> None:
    tenant, file_id = await _seed(session)
    result = await _scan(engine, tenant, file_id, CSV, FakeScanner.candidate_clean())

    assert result.disposition is ScanDisposition.CLEAN
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["status"]) == ("clean", "ready")
    assert row["scan_object_etag"] == "etag-1"
    assert (row["scan_attempts"], row["scan_failure"]) == (1, None)
    assert [(a, o) for a, o, _ in await _audit(engine, tenant, file_id)] == [
        ("storage.object.scanned", "ok")
    ]


async def test_malware_is_quarantined_with_its_security_event_in_one_transaction(
    engine, session
) -> None:
    tenant, file_id = await _seed(session)
    result = await _scan(engine, tenant, file_id, CSV, FakeScanner.infected())

    assert result.disposition is ScanDisposition.INFECTED
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["status"]) == ("infected", "quarantined")
    assert row["scan_object_etag"] is None
    assert [(a, o) for a, o, _ in await _audit(engine, tenant, file_id)] == [
        ("storage.object.quarantined", "denied")
    ]


async def test_no_signature_name_reaches_any_column_or_any_audit_detail(engine, session) -> None:
    from koras_worker.scanning import ClamdScanner
    from scanner_support import replying, serving

    tenant, file_id = await _seed(session)
    async with serving(
        lambda fake: replying(fake, f"stream: {SIGNATURE} FOUND\0".encode())
    ) as fake:
        scanner = ClamdScanner(
            host="127.0.0.1",
            port=fake.port,
            connect_timeout=2.0,
            scan_timeout=5.0,
            max_bytes=1 << 20,
        )
        result = await _scan(engine, tenant, file_id, CSV, scanner)
    assert result.disposition is ScanDisposition.INFECTED

    stored = repr(await _row(engine, tenant, file_id)) + repr(await _audit(engine, tenant, file_id))
    assert SIGNATURE not in stored and "EICAR" not in stored


@pytest.mark.parametrize(
    ("body", "content_type", "failure"),
    [
        (streamed_zip64_deflated(), "application/zip", ScanFailure.INSPECTION_INCOMPLETE),
        (
            build_zip([Member.stored(b"ok.txt", b"fine"), Member.stored(b"s", b"x", flags=1)]),
            "application/zip",
            ScanFailure.INSPECTION_INCOMPLETE,
        ),
        (
            real_docx(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ScanFailure.INSPECTION_INCOMPLETE,
        ),
    ],
)
async def test_a_structural_hold_leaves_the_file_pending_with_its_reason(
    engine, session, body, content_type, failure
) -> None:
    tenant, file_id = await _seed(session, body, content_type=content_type)
    result = await _scan(engine, tenant, file_id, body, FakeScanner.candidate_clean())

    assert result.disposition is ScanDisposition.HELD
    assert result.failure is failure
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["status"], row["scan_failure"]) == (
        "pending",
        "ready",
        failure.value,
    )
    assert row["scan_object_etag"] is None
    assert [a for a, _, _ in await _audit(engine, tenant, file_id)] == [
        "storage.object.scan_failed"
    ]


async def test_a_digest_the_bytes_contradict_is_held_for_real(engine, session) -> None:
    tenant, file_id = await _seed(session, checksum_sha256="0" * 64)
    result = await _scan(engine, tenant, file_id, CSV, FakeScanner.candidate_clean())
    assert result.failure is ScanFailure.INTEGRITY_MISMATCH
    assert (await _row(engine, tenant, file_id))["scan_status"] == "pending"


async def test_a_scanner_outage_is_recorded_as_the_scanner_and_the_file_stays_pending(
    engine, session
) -> None:
    tenant, file_id = await _seed(session)
    result = await _scan(
        engine, tenant, file_id, CSV, _NonReading(ScanResult(ScanOutcome.UNAVAILABLE))
    )
    assert result.failure is ScanFailure.SCANNER_UNAVAILABLE
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["scan_failure"], row["scan_attempts"]) == (
        "pending",
        "scanner_unavailable",
        1,
    )


async def test_the_window_defers_for_real_and_writes_nothing(engine, session) -> None:
    tenant, file_id = await _seed(session)
    result = await _scan(
        engine,
        tenant,
        file_id,
        CSV,
        FakeScanner.candidate_clean(),
        at=ISSUED + timedelta(minutes=5),
    )
    assert result.disposition is ScanDisposition.POSTPONED
    row = await _row(engine, tenant, file_id)
    assert (row["scan_attempts"], row["scan_attempted_at"], row["scan_failure"]) == (0, None, None)
    assert await _audit(engine, tenant, file_id) == []


async def test_another_tenants_job_finds_no_row_under_rls_and_changes_nothing(
    engine, session
) -> None:
    tenant, file_id = await _seed(session)
    intruder, _ = await _seed(session)
    result = await _scan(engine, tenant, file_id, CSV, FakeScanner.infected(), as_tenant=intruder)
    assert result.disposition is ScanDisposition.NOT_ELIGIBLE
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["status"], row["scan_attempts"]) == ("pending", "ready", 0)
    assert await _audit(engine, tenant, file_id) == []
    assert await _audit(engine, intruder, file_id) == []


async def test_a_duplicate_run_changes_nothing(engine, session) -> None:
    tenant, file_id = await _seed(session)
    first = await _scan(engine, tenant, file_id, CSV, FakeScanner.candidate_clean())
    second = await _scan(engine, tenant, file_id, CSV, FakeScanner.candidate_clean())
    assert (first.disposition, second.disposition) == (
        ScanDisposition.CLEAN,
        ScanDisposition.NOT_ELIGIBLE,
    )
    row = await _row(engine, tenant, file_id)
    assert row["scan_attempts"] == 1
    assert len(await _audit(engine, tenant, file_id)) == 1


class _After(FakeScanner):
    """Answers only once the other run's verdict is committed, so the commit order is chosen.

    Also answers only once the other run is *inside its scan*. Without that the race this
    stands for is not a race: the run that answers at once can commit its verdict before the
    other has begun its attempt, and that one then correctly finds nothing eligible (the file
    has left `pending`) and never reaches the verdict the test is about. It failed about one run
    in three until both runs were made to have started their counted attempt first.
    """

    def __init__(self, result: ScanResult, engine, tenant: str, file_id: str, seen) -> None:
        super().__init__(result)
        self._probe = (engine, tenant, file_id, seen)
        self.entered = asyncio.Event()
        self.partner: _After | None = None

    async def scan(self, source):
        verdict = await super().scan(source)
        self.entered.set()
        if self.partner is not None:
            await asyncio.wait_for(self.partner.entered.wait(), 20)
        engine, tenant, file_id, seen = self._probe
        if seen is None:
            return verdict
        for _ in range(400):
            if (await _row(engine, tenant, file_id))["scan_status"] == seen:
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("the other run never committed")
        return verdict


@pytest.mark.parametrize("infected_commits_first", [True, False])
async def test_two_workers_racing_clean_and_infected_leave_the_file_infected(
    engine, session, infected_commits_first
) -> None:
    tenant, file_id = await _seed(session)
    # The run that commits first answers as soon as the other is inside its scan; the other
    # answers only after that commit is visible.
    first_seen, second_seen = None, ("infected" if infected_commits_first else "clean")
    clean = _After(ScanResult(ScanOutcome.CANDIDATE_CLEAN), engine, tenant, file_id,
                   second_seen if infected_commits_first else first_seen)  # fmt: skip
    infected = _After(ScanResult(ScanOutcome.INFECTED), engine, tenant, file_id,
                      first_seen if infected_commits_first else second_seen)  # fmt: skip
    clean.partner, infected.partner = infected, clean
    results = await asyncio.gather(
        _scan(engine, tenant, file_id, CSV, clean), _scan(engine, tenant, file_id, CSV, infected)
    )

    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["status"]) == ("infected", "quarantined")
    actions = [a for a, _, _ in await _audit(engine, tenant, file_id)]
    assert actions.count("storage.object.quarantined") == 1
    assert ScanDisposition.INFECTED in {r.disposition for r in results}
    if infected_commits_first:
        assert "storage.object.scanned" not in actions
    else:
        assert actions == ["storage.object.scanned", "storage.object.quarantined"]


async def test_the_threshold_writes_scan_exhausted_once_and_the_file_stays_scannable(
    engine, session
) -> None:
    tenant, file_id = await _seed(session)
    for _ in range(5):
        await _scan(engine, tenant, file_id, CSV, FakeScanner.unavailable(), max_attempts=3)
    row = await _row(engine, tenant, file_id)
    assert (row["scan_status"], row["status"], row["scan_attempts"]) == ("pending", "ready", 5)
    actions = [a for a, _, _ in await _audit(engine, tenant, file_id)]
    assert actions.count("storage.object.scan_exhausted") == 1
    assert actions.count("storage.object.scan_failed") == 1

    # Exhaustion excluded nothing: the next scan still releases it.
    result = await _scan(
        engine, tenant, file_id, CSV, FakeScanner.candidate_clean(), max_attempts=3
    )
    assert result.disposition is ScanDisposition.CLEAN


async def test_the_attempt_counter_is_the_transitions_and_saturates_through_the_runtime(
    engine, session
) -> None:
    tenant, file_id = await _seed(session)
    async with sessions(engine)() as opened:
        await opened.execute(AS_TENANT, {"tenant_id": tenant})
        await opened.execute(
            text("update public.files set scan_attempts = 32766 where id = cast(:f as uuid)"),
            {"f": file_id},
        )
        await opened.commit()
    for _ in range(3):
        await _scan(engine, tenant, file_id, CSV, FakeScanner.unavailable(), max_attempts=12)
    assert (await _row(engine, tenant, file_id))["scan_attempts"] == 32767


async def test_non_pending_files_are_never_touched(engine, session) -> None:
    for fields in (
        {"scan_status": "clean"},
        {"scan_status": "infected", "status": "ready"},
        {"scan_status": "skipped"},
    ):
        tenant, file_id = await _seed(session, **fields)
        result = await _scan(engine, tenant, file_id, CSV, FakeScanner.infected())
        assert result.disposition is ScanDisposition.NOT_ELIGIBLE, fields
        row = await _row(engine, tenant, file_id)
        assert row["scan_status"] == fields["scan_status"]
        assert row["scan_attempts"] == 0
