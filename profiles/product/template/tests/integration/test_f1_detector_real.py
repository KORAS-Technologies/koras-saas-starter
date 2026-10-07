# ruff: noqa: ANN001, ANN002, ANN003, ANN201, ANN202, ANN401, E501, S101, E402, S105, S608
"""The F1 detector against a real PostgreSQL (ADR 0013 section 7, `secure_files`).

Seeds a row of every class, in two tenants, as a role that bypasses row-level security (the
`DATABASE_ADMIN_URL` shape), and asserts the detector's classification, its counts, that every
tenant is covered, that the transaction is read-only, that it refuses the application role and
that it changes nothing. The release rule it asks is the product's own: a row of each kind the rule
withholds is seeded as well, and none of them is counted.

Needs `E2E_ADMIN_DATABASE_URL` (a superuser or BYPASSRLS URL for a migrated database) and
`E2E_DATABASE_URL` (the restricted application role, which the detector must refuse): the two
variables the generator-integration round trip already sets. Every test runs when both are set;
nothing here skips on its own, and the CI step that runs this module fails on a skip.

A throwaway local database:

    docker run -d --name f1-pg -e POSTGRES_PASSWORD=postgres -p 127.0.0.1:55433:5432 \
        supabase/postgres:15.6.1.143
    MIGRATE_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55433/postgres \
        bash local/scripts/migrate.sh

Do not point it at a database another suite is using for exact counts: the assertions are relative
to what the database held before the seed, but the seed itself is permanent.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from promotion import f1
from promotion.adapters import build_adapters
from promotion_support import FakeRunner, make_config

ADMIN_URL = os.environ.get("E2E_ADMIN_DATABASE_URL", "")
APP_URL = os.environ.get("E2E_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not ADMIN_URL or not APP_URL,
    reason="needs a real PostgreSQL as a BYPASSRLS role and as the app role; "
    "set E2E_ADMIN_DATABASE_URL and E2E_DATABASE_URL",
)

NOW = dt.datetime.now(dt.UTC)
HOUR_AGO = NOW - dt.timedelta(hours=1)
DAY_AGO = NOW - dt.timedelta(days=1)
DIGEST = hashlib.sha256(b"x").hexdigest()


def dsn(url: str) -> str:
    return re.sub(r"^postgres(?:ql)?(?:\+\w+)?://", "postgresql://", url, count=1)


def run(coro):
    return asyncio.run(coro)


async def _connect():
    return await asyncpg.connect(dsn(ADMIN_URL), statement_cache_size=0)


@dataclass
class Seeded:
    tenant_a: str
    tenant_b: str
    ids: dict[str, str]  # label -> file id
    baseline: dict[str, int]


def _key(tenant: str, file_id: str, shape: str) -> str:
    if shape == "final":
        return f"tenants/{tenant}/documents/{file_id}/final/{uuid.uuid4()}/a.csv"
    if shape == "other_file":
        return f"tenants/{tenant}/documents/{uuid.uuid4()}/final/{uuid.uuid4()}/a.csv"
    if shape == "incoming":
        return f"tenants/{tenant}/documents/{file_id}/incoming/{uuid.uuid4()}/a.csv"
    return f"tenants/{tenant}/documents/{file_id}/a.csv"  # legacy


async def _file(conn, tenant: str, label: str, shape: str = "final", **cols: Any) -> str:
    file_id = str(uuid.uuid4())
    values: dict[str, Any] = {
        "status": "ready",
        "scan_status": "clean",
        "checksum_sha256": DIGEST,
        "checksum_verified_at": DAY_AGO,
        "scan_attempted_at": NOW,
        "scan_object_etag": "etag-1",
    }
    values.update(cols)
    await conn.execute(
        "insert into public.files (id, tenant_id, storage_key, name, size_bytes, content_type, "
        "category, status, uploaded_by, scan_status, checksum_sha256, checksum_verified_at, "
        "scan_attempted_at, scan_object_etag) values ($1, $2, $3, $4, 1, 'text/csv', 'documents', "
        "$5, 'u', $6, $7, $8, $9, $10)",
        uuid.UUID(file_id),
        uuid.UUID(tenant),
        _key(tenant, file_id, shape),
        f"{label}-PRIVATE-NAME.csv",
        values["status"],
        values["scan_status"],
        values["checksum_sha256"],
        values["checksum_verified_at"],
        values["scan_attempted_at"],
        values["scan_object_etag"],
    )
    return file_id


def _report() -> f1.F1Report:
    return f1.run_against_database(ADMIN_URL)


async def _seed() -> Seeded:
    conn = await _connect()
    try:
        tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
        for tenant in (tenant_a, tenant_b):
            await conn.execute(
                "insert into public.tenants (id, slug, name) values ($1, $2, 'F1')",
                uuid.UUID(tenant),
                f"f1-{tenant[:8]}",
            )
        ids: dict[str, str] = {}
        a, b = tenant_a, tenant_b
        ids["verified"] = await _file(conn, a, "v")
        # a restore replacement hashed what it wrote and set the same two columns: same evidence
        ids["restored"] = await _file(conn, a, "o", checksum_verified_at=HOUR_AGO)
        ids["f1"] = await _file(conn, a, "f", checksum_verified_at=None)
        ids["f1_no_claim"] = await _file(
            conn, a, "n", checksum_verified_at=None, checksum_sha256=None
        )
        ids["missing_claim"] = await _file(conn, a, "m", checksum_sha256=None)
        ids["predates"] = await _file(
            conn, a, "p", checksum_verified_at=NOW, scan_attempted_at=NOW - dt.timedelta(days=2)
        )
        ids["no_verdict_time"] = await _file(conn, a, "t", scan_attempted_at=None)
        ids["other_file"] = await _file(conn, a, "x", "other_file")
        # rows the release rule withholds: none of these is counted as F1
        ids["pending"] = await _file(conn, a, "1", scan_status="pending")
        ids["infected"] = await _file(conn, a, "2", status="ready", scan_status="infected")
        ids["skipped"] = await _file(conn, a, "3", scan_status="skipped")
        ids["clean_no_stamp"] = await _file(conn, a, "4", scan_object_etag=None)
        ids["clean_blank_stamp"] = await _file(conn, a, "5", scan_object_etag="")
        ids["clean_legacy_key"] = await _file(conn, a, "6", "legacy")
        ids["clean_incoming_key"] = await _file(conn, a, "7", "incoming")
        ids["not_ready"] = await _file(conn, a, "8", status="pending")
        # the second tenant: an F1 row and a verified row, and its own pending
        ids["b_f1"] = await _file(conn, b, "bf", checksum_verified_at=None)
        ids["b_verified"] = await _file(conn, b, "bv")
        ids["b_pending"] = await _file(conn, b, "bp", scan_status="pending")
    finally:
        await conn.close()
    return Seeded(tenant_a, tenant_b, ids, {})


@pytest.fixture(scope="module")
def seeded() -> Seeded:
    before = _report()
    state = run(_seed())
    state.baseline = {
        **before.counts,
        "_pending": before.not_releasable_pending,
        "_other": before.not_releasable_other,
    }
    return state


def _classes(report: f1.F1Report) -> dict[str, str]:
    return {r.file_id: r.classification for r in report.rows}


def test_every_class_is_classified_from_real_rows(seeded: Seeded) -> None:
    got = _classes(_report())
    ids = seeded.ids
    assert got[ids["verified"]] == f1.VERIFIED_DIGEST
    assert got[ids["restored"]] == f1.VERIFIED_DIGEST
    assert got[ids["b_verified"]] == f1.VERIFIED_DIGEST
    assert got[ids["f1"]] == f1.FINAL_KEY_NO_VERIFIED_DIGEST
    assert got[ids["f1_no_claim"]] == f1.FINAL_KEY_NO_VERIFIED_DIGEST
    assert got[ids["b_f1"]] == f1.FINAL_KEY_NO_VERIFIED_DIGEST
    assert got[ids["missing_claim"]] == f1.MISSING_CLAIM
    assert got[ids["predates"]] == f1.VERDICT_PREDATES
    assert got[ids["no_verdict_time"]] == f1.VERDICT_PREDATES
    # a final key that names another file is releasable by the rule and is not this row's own
    assert got[ids["other_file"]] == f1.UNRECOGNISED_KEY_SHAPE


def test_what_the_release_rule_withholds_is_not_releasable_and_not_counted(seeded: Seeded) -> None:
    report = _report()
    got = _classes(report)
    for label in (
        "pending",
        "infected",
        "skipped",
        "clean_no_stamp",
        "clean_blank_stamp",
        "clean_legacy_key",
        "clean_incoming_key",
        "not_ready",
        "b_pending",
    ):
        assert seeded.ids[label] not in got, label
    assert report.not_releasable_pending >= seeded.baseline["_pending"] + 2  # pending, b_pending
    # infected, skipped, the two unstamped, the legacy and the incoming key, and the not-ready one
    assert report.not_releasable_other >= seeded.baseline["_other"] + 7
    check = f1.check_f1(report, "prod", f1.Dispositions())
    shown = {r["file_id"] for r in check.data["unverified_rows"]}
    assert seeded.ids["pending"] not in shown and seeded.ids["clean_no_stamp"] not in shown


def test_counts_per_class_and_the_unverified_total(seeded: Seeded) -> None:
    report = _report()
    delta = {k: v - seeded.baseline.get(k, 0) for k, v in report.counts.items()}
    assert delta[f1.VERIFIED_DIGEST] == 3
    assert delta[f1.FINAL_KEY_NO_VERIFIED_DIGEST] == 3
    assert delta[f1.MISSING_CLAIM] == 1
    assert delta[f1.VERDICT_PREDATES] == 2
    assert delta[f1.UNRECOGNISED_KEY_SHAPE] == 1
    unsafe_before = sum(v for k, v in seeded.baseline.items() if k in f1.UNSAFE_CLASSES)
    assert report.raw_unverified_count - unsafe_before == 3 + 1 + 2 + 1
    check = f1.check_f1(report, "prod", f1.Dispositions())
    assert not check.passed
    assert check.data["F1_UNVERIFIED_RELEASABLE_COUNT"] == report.raw_unverified_count


def test_a_dev_disposition_covers_exactly_the_recorded_row_and_nothing_else(seeded: Seeded) -> None:
    report = _report()
    entry = f1.Disposition(
        "dev", seeded.tenant_a, seeded.ids["f1"], f1.FINAL_KEY_NO_VERIFIED_DIGEST, "r", "2026-10-06"
    )
    check = f1.check_f1(report, "dev", f1.Dispositions(entries=(entry,)))
    assert check.data["dispositioned_count"] == 1
    assert check.data["F1_UNVERIFIED_RELEASABLE_COUNT"] == report.raw_unverified_count - 1
    again = f1.check_f1(report, "stg", f1.Dispositions(entries=(entry,)))
    assert again.data["dispositioned_count"] == 0


def test_every_tenant_is_covered_by_the_admin_connection(seeded: Seeded) -> None:
    report = _report()
    assert {seeded.tenant_a, seeded.tenant_b} <= {r.tenant_id for r in report.rows}
    assert report.tenants_with_files >= 2
    assert report.tenants_total >= report.tenants_with_files
    # tenant B rows are visible with no tenant context set at all
    assert any(
        r.tenant_id == seeded.tenant_b and r.file_id == seeded.ids["b_f1"] for r in report.rows
    )


def test_the_application_role_is_refused_because_zero_would_prove_nothing(seeded: Seeded) -> None:
    with pytest.raises(f1.F1Error, match="bypass"):
        f1.run_against_database(APP_URL)

    # and what the application role sees is, in fact, nothing: the reason for the refusal
    async def count_as_app() -> int:
        conn = await asyncpg.connect(dsn(APP_URL), statement_cache_size=0)
        try:
            return int(await conn.fetchval("select count(*) from public.files"))
        finally:
            await conn.close()

    assert run(count_as_app()) == 0


def test_an_unreachable_database_is_an_error_not_a_zero() -> None:
    with pytest.raises(f1.F1Error, match="unreachable") as raised:
        f1.run_against_database("postgresql://nobody:secret@127.0.0.1:1/none")
    assert "secret" not in str(raised.value) and "postgresql://" not in str(raised.value)


def test_an_empty_database_is_a_failure_not_a_pass() -> None:
    async def make() -> str:
        conn = await _connect()
        try:
            name = f"f1_empty_{uuid.uuid4().hex[:8]}"
            await conn.execute(f'create database "{name}"')
            return name
        finally:
            await conn.close()

    name = run(make())
    parts = urlsplit(dsn(ADMIN_URL))
    empty = urlunsplit(parts._replace(path=f"/{name}"))
    try:
        with pytest.raises(f1.F1Error, match="schema is empty"):
            f1.run_against_database(empty)
    finally:

        async def drop() -> None:
            conn = await _connect()
            try:
                await conn.execute(f'drop database "{name}"')
            finally:
                await conn.close()

        run(drop())


def test_the_detector_runs_in_a_read_only_transaction_and_a_write_there_is_refused(
    seeded: Seeded,
) -> None:
    statements: list[str] = []
    original = asyncpg.Connection.execute

    async def spy(self, query, *args, **kwargs):
        statements.append(query)
        return await original(self, query, *args, **kwargs)

    asyncpg.Connection.execute = spy  # type: ignore[method-assign]
    try:
        _report()
    finally:
        asyncpg.Connection.execute = original  # type: ignore[method-assign]
    assert statements == ["begin transaction read only", "rollback"]

    async def attempt_write() -> str:
        conn = await _connect()
        try:
            await conn.execute("begin transaction read only")
            assert await conn.fetchval("select current_setting('transaction_read_only')") == "on"
            try:
                await conn.execute("update public.files set name = name")
            except asyncpg.exceptions.ReadOnlySQLTransactionError as error:
                return type(error).__name__
            return "written"
        finally:
            await conn.execute("rollback")
            await conn.close()

    assert run(attempt_write()) == "ReadOnlySQLTransactionError"


def test_the_detector_changes_nothing(seeded: Seeded) -> None:
    async def fingerprint() -> tuple[str, str]:
        conn = await _connect()
        try:
            out = []
            for table in ("files", "tenants"):
                out.append(
                    await conn.fetchval(
                        f"select md5(coalesce(string_agg(t::text, '|' order by t::text), '')) "
                        f"from public.{table} t"
                    )
                )
            return tuple(out)  # type: ignore[return-value]
        finally:
            await conn.close()

    before = run(fingerprint())
    _report()
    f1.check_f1(_report(), "dev", f1.Dispositions())
    assert run(fingerprint()) == before


def test_the_sql_spelling_and_the_python_rule_agree_on_every_seeded_row(seeded: Seeded) -> None:
    """`detect` raises on a disagreement; reaching here with the seed in place is the proof."""
    report = _report()
    assert len(report.rows) >= 10


def test_the_gate_check_reads_the_url_from_the_secret_store_and_judges_the_real_database(
    seeded: Seeded, tmp_path: Path
) -> None:
    config = make_config(tmp_path)
    runner = FakeRunner(store={("prod", "DATABASE_ADMIN_URL"): ADMIN_URL})
    store, _ = build_adapters(config, runner)
    check = f1.check_for_environment("prod", config, store)
    assert not check.passed and check.data["F1_UNVERIFIED_RELEASABLE_COUNT"] >= 7
    assert ADMIN_URL not in repr(check) and "PRIVATE-NAME" not in repr(check)
    assert runner.violations() == []


def test_the_cli_prints_ids_and_classes_and_no_key_or_name(
    seeded: Seeded, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_ADMIN_URL", ADMIN_URL)
    code = f1.main(["--env", "prod", "--allow-unbound"], runner=FakeRunner())
    out = capsys.readouterr().out
    assert code == 1
    assert seeded.ids["f1"] in out and f1.FINAL_KEY_NO_VERIFIED_DIGEST in out
    assert "PRIVATE-NAME" not in out and "tenants/" not in out and ADMIN_URL not in out
