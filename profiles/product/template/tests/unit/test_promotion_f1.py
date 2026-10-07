# ruff: noqa: ANN001, ANN201, ANN401, E501, SLF001
"""The F1 detector, pure: classification, counts, dispositions and the read-only guarantees."""

from __future__ import annotations

import ast
import datetime as dt
import re
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from promotion import f1
from promotion.f1 import F1Error, classify, detect, load_dispositions
from promotion.result import Check
from promotion_support import ERROR, FakeRunner, make_config

T = "3f4c1a52-6d1e-4c4e-9a53-0f7a1b2c3d4e"
T2 = "11111111-2222-4333-8444-555555555555"
NOW = dt.datetime(2026, 10, 6, 12, 0, tzinfo=dt.UTC)
EARLIER = NOW - dt.timedelta(days=2)
DIGEST = "a" * 64


def fid() -> str:
    return str(uuid.uuid4())


def final_key(tenant: str, file_id: str) -> str:
    return f"tenants/{tenant}/documents/{file_id}/final/{uuid.uuid4()}/a.csv"


def row(**over: Any) -> dict[str, Any]:
    file_id = over.pop("file_id", fid())
    tenant = over.pop("tenant_id", T)
    base: dict[str, Any] = {
        "tenant_id": tenant,
        "file_id": file_id,
        "storage_key": final_key(tenant, file_id),
        "status": "ready",
        "scan_status": "clean",
        "scan_object_etag": "etag-1",
        "checksum_sha256": DIGEST,
        "checksum_verified_at": EARLIER,
        "scan_attempted_at": NOW,
    }
    base.update(over)
    return base


# --- classification --------------------------------------------------------------------


def test_a_verified_digest_on_its_own_final_key_is_safe() -> None:
    assert classify(row()) == f1.VERIFIED_DIGEST


def test_final_shape_alone_is_not_evidence() -> None:
    assert classify(row(checksum_verified_at=None)) == f1.FINAL_KEY_NO_VERIFIED_DIGEST
    # even with a well-formed claim: a claim is not a verification
    assert classify(row(checksum_verified_at=None, checksum_sha256=DIGEST)) == (
        f1.FINAL_KEY_NO_VERIFIED_DIGEST
    )
    assert classify(row(checksum_verified_at=None, checksum_sha256=None)) == (
        f1.FINAL_KEY_NO_VERIFIED_DIGEST
    )


@pytest.mark.parametrize("claim", [None, "", "A" * 64, "abc", "g" * 64, "a" * 63, "a" * 65, 7])
def test_a_verified_timestamp_without_a_wellformed_claim_is_missing_claim(claim) -> None:
    assert classify(row(checksum_sha256=claim)) == f1.MISSING_CLAIM


def test_a_verdict_older_than_the_verification_is_not_trusted() -> None:
    old = row(checksum_verified_at=NOW, scan_attempted_at=NOW - dt.timedelta(hours=1))
    assert classify(old) == f1.VERDICT_PREDATES
    # a few seconds of clock skew is not a failure
    near = row(checksum_verified_at=NOW, scan_attempted_at=NOW - dt.timedelta(seconds=5))
    assert classify(near) == f1.VERIFIED_DIGEST
    far = row(checksum_verified_at=NOW, scan_attempted_at=NOW - dt.timedelta(seconds=61))
    assert classify(far) == f1.VERDICT_PREDATES


def test_a_verified_row_with_no_verdict_time_cannot_show_the_verdict_followed() -> None:
    assert classify(row(scan_attempted_at=None)) == f1.VERDICT_PREDATES


def test_a_verified_digest_on_someone_elses_final_key_is_not_own() -> None:
    other = fid()
    wrong_file = row(storage_key=final_key(T, other))
    assert classify(wrong_file) == f1.UNRECOGNISED_KEY_SHAPE
    file_id = fid()
    foreign = row(file_id=file_id, storage_key=final_key(T2, file_id))
    assert classify(foreign) == f1.UNRECOGNISED_KEY_SHAPE


def test_incoming_legacy_and_odd_keys_fail() -> None:
    file_id = fid()
    incoming = f"tenants/{T}/documents/{file_id}/incoming/{uuid.uuid4()}/a.csv"
    assert classify(row(file_id=file_id, storage_key=incoming)) == f1.INCOMING_KEY_RELEASABLE
    legacy = f"tenants/{T}/documents/{file_id}/a.csv"
    assert classify(row(file_id=file_id, storage_key=legacy)) == f1.LEGACY_KEY_RELEASABLE
    for key in ("", None, "a/b", "tenants/x", f"other/{T}/documents/{file_id}/a.csv", 5):
        assert classify(row(file_id=file_id, storage_key=key)) == f1.UNRECOGNISED_KEY_SHAPE
    # a five-segment key that names another tenant or file is not a legacy key of this row
    assert classify(
        row(file_id=file_id, storage_key=f"tenants/{T2}/documents/{file_id}/a.csv")
    ) == (f1.UNRECOGNISED_KEY_SHAPE)
    assert classify(row(file_id=file_id, storage_key=f"tenants/{T}/documents/{fid()}/a.csv")) == (
        f1.UNRECOGNISED_KEY_SHAPE
    )


@pytest.mark.parametrize(
    ("status", "scan"),
    [
        ("ready", "pending"),
        ("ready", "infected"),
        ("ready", "skipped"),
        ("pending", "clean"),
        ("quarantined", "infected"),
        ("ready", None),
        ("ready", "CLEAN"),
    ],
)
def test_the_classifier_refuses_a_row_that_is_not_releasable(status: str, scan) -> None:
    with pytest.raises(F1Error):
        classify(row(status=status, scan_status=scan))


# --- detect(): the runner is injected ----------------------------------------------------


class Runner:
    """A fake read-only query runner keyed by the module's own statements."""

    def __init__(
        self,
        rows: list[dict[str, Any]],
        *,
        read_only: str = "on",
        bypass: Any = True,
        schema: Mapping[str, set[str]] | None = None,
        not_releasable: list[dict[str, Any]] | None = None,
    ) -> None:
        self.rows = rows
        self.guard = {"read_only": read_only, "bypasses_rls": bypass}
        self.schema = (
            {t: set(c) for t, c in f1.REQUIRED_COLUMNS.items()} if schema is None else schema
        )
        self.not_releasable = not_releasable or []
        self.calls: list[str] = []

    def __call__(self, sql: str) -> list[dict[str, Any]]:
        self.calls.append(sql)
        assert sql in f1.SQL_STATEMENTS, "only the module's own SELECTs may be run"
        if sql == f1._Q_GUARD:
            return [self.guard]
        if sql == f1._Q_SCHEMA:
            return [
                {"table_name": t, "column_name": c} for t, cols in self.schema.items() for c in cols
            ]
        if sql == f1._Q_TOTALS:
            tenants = {r["tenant_id"] for r in self.rows}
            return [
                {
                    "tenants_total": len(tenants),
                    "tenants_with_files": len(tenants),
                    "files_total": len(self.rows) + sum(g["n"] for g in self.not_releasable),
                }
            ]
        if sql == f1._Q_NOT_RELEASABLE:
            return self.not_releasable
        return self.rows


def test_detect_counts_per_class_and_the_raw_unverified_count() -> None:
    unverified = row(checksum_verified_at=None)
    other = fid()
    wrong_file = row(storage_key=final_key(T, other))
    report = detect(Runner([row(), row(), unverified, wrong_file]))
    assert report.counts == {
        f1.FINAL_KEY_NO_VERIFIED_DIGEST: 1,
        f1.UNRECOGNISED_KEY_SHAPE: 1,
        f1.VERIFIED_DIGEST: 2,
    }
    assert report.raw_unverified_count == 2
    assert {r.tenant_id for r in report.rows} == {T}


def test_pending_rows_are_counted_apart_and_never_in_the_unverified_count() -> None:
    pending = [{"status": "ready", "scan_status": "pending", "n": 8}]
    report = detect(Runner([row()], not_releasable=pending))
    assert report.not_releasable_pending == 8
    assert report.raw_unverified_count == 0
    check = f1.check_f1(report, "dev", f1.Dispositions())
    assert check.passed and check.data["not_releasable_pending"] == 8
    assert check.data["F1_UNVERIFIED_RELEASABLE_COUNT"] == 0


def test_a_row_the_sql_returned_that_the_python_rule_refuses_is_an_error_not_a_count() -> None:
    no_stamp = row(scan_object_etag=None)
    with pytest.raises(F1Error, match="disagree"):
        detect(Runner([no_stamp]))
    smuggled = row(scan_status="pending")
    with pytest.raises(F1Error, match="disagree"):
        detect(Runner([smuggled]))
    not_final = row(storage_key=f"tenants/{T}/documents/{fid()}/a.csv")
    with pytest.raises(F1Error, match="disagree"):
        detect(Runner([not_final]))


def test_infected_skipped_and_pending_are_not_counted_either() -> None:
    groups = [
        {"status": "ready", "scan_status": "pending", "n": 2},
        {"status": "quarantined", "scan_status": "infected", "n": 3},
        {"status": "ready", "scan_status": "skipped", "n": 1},
        {"status": "ready", "scan_status": "clean", "n": 4},  # clean but withheld by identity
    ]
    report = detect(Runner([], not_releasable=groups))
    assert (report.not_releasable_pending, report.not_releasable_other) == (2, 8)
    assert report.raw_unverified_count == 0


def test_zero_rows_against_a_migrated_database_is_a_pass() -> None:
    check = f1.check_f1(detect(Runner([])), "prod", f1.Dispositions())
    assert check.passed and check.data["F1_UNVERIFIED_RELEASABLE_COUNT"] == 0


def test_unknown_is_never_a_pass() -> None:
    with pytest.raises(F1Error, match="read-only"):
        detect(Runner([], read_only="off"))
    with pytest.raises(F1Error, match="bypass"):
        detect(Runner([], bypass=False))
    with pytest.raises(F1Error, match="bypass"):
        detect(Runner([], bypass=None))
    with pytest.raises(F1Error, match="schema is empty"):
        detect(Runner([], schema={}))
    missing_table = {t: set(c) for t, c in f1.REQUIRED_COLUMNS.items()}
    del missing_table["files"]
    with pytest.raises(F1Error, match="files does not exist"):
        detect(Runner([], schema=missing_table))
    missing_column = {t: set(c) for t, c in f1.REQUIRED_COLUMNS.items()}
    missing_column["files"].discard("checksum_verified_at")
    with pytest.raises(F1Error, match="checksum_verified_at"):
        detect(Runner([], schema=missing_column))
    no_stamp_column = {t: set(c) for t, c in f1.REQUIRED_COLUMNS.items()}
    no_stamp_column["files"].discard("scan_object_etag")
    with pytest.raises(F1Error, match="scan_object_etag"):
        detect(Runner([], schema=no_stamp_column))


def test_the_guard_runs_before_anything_else() -> None:
    runner = Runner([], read_only="off")
    with pytest.raises(F1Error):
        detect(runner)
    assert runner.calls == [f1._Q_GUARD]


# --- check_f1 and dispositions -----------------------------------------------------------


def synthetic_report() -> tuple[f1.F1Report, str]:
    file_id = fid()
    report = detect(Runner([row(file_id=file_id, checksum_verified_at=None), row()]))
    return report, file_id


def entry(file_id: str, *, env: str = "dev", classification: str = "") -> f1.Disposition:
    return f1.Disposition(
        env=env,
        tenant_id=T,
        file_id=file_id,
        classification=classification or f1.FINAL_KEY_NO_VERIFIED_DIGEST,
        reason="synthetic",
        recorded="2026-10-06",
    )


def test_a_failing_row_fails_the_check_with_raw_and_net_shown() -> None:
    report, file_id = synthetic_report()
    check = f1.check_f1(report, "dev", f1.Dispositions())
    assert isinstance(check, Check) and not check.passed
    assert check.data["raw_unverified_count"] == 1
    assert check.data["F1_UNVERIFIED_RELEASABLE_COUNT"] == 1
    assert check.data["unverified_rows"][0]["file_id"] == file_id


def test_a_dev_disposition_is_honoured_and_never_hidden() -> None:
    report, file_id = synthetic_report()
    check = f1.check_f1(report, "dev", f1.Dispositions(entries=(entry(file_id),)))
    assert check.passed
    assert check.data["raw_unverified_count"] == 1 and check.data["dispositioned_count"] == 1
    assert check.data["F1_UNVERIFIED_RELEASABLE_COUNT"] == 0
    assert check.data["counts"][f1.DISPOSITIONED] == 1
    assert check.data["counts"][f1.FINAL_KEY_NO_VERIFIED_DIGEST] == 1
    assert check.data["unverified_rows"][0]["disposition"] == f1.DISPOSITIONED
    assert "raw 1" in check.detail and "net 0" in check.detail


@pytest.mark.parametrize("env", ["test", "stg", "prod"])
def test_dispositions_are_ignored_outside_dev(env: str) -> None:
    report, file_id = synthetic_report()
    check = f1.check_f1(report, env, f1.Dispositions(entries=(entry(file_id),)))
    assert not check.passed
    assert check.data["F1_UNVERIFIED_RELEASABLE_COUNT"] == 1
    assert check.data["dispositions_ignored"] == 1


def test_a_disposition_stops_applying_when_the_row_changed() -> None:
    file_id = fid()
    # now verified: the recorded class no longer matches, but the row is safe anyway
    safe = detect(Runner([row(file_id=file_id)]))
    check = f1.check_f1(safe, "dev", f1.Dispositions(entries=(entry(file_id),)))
    assert check.passed and check.data["dispositions_unmatched"] == [f"{T}:{file_id}"]
    # now a different failing class: counts again
    other = detect(Runner([row(file_id=file_id, storage_key=final_key(T, fid()))]))
    check = f1.check_f1(other, "dev", f1.Dispositions(entries=(entry(file_id),)))
    assert not check.passed and check.data["F1_UNVERIFIED_RELEASABLE_COUNT"] == 1
    # no longer releasable (not in the report at all): nothing to cover, nothing hidden
    gone = f1.check_f1(detect(Runner([])), "dev", f1.Dispositions(entries=(entry(file_id),)))
    assert gone.passed and gone.data["dispositions_unmatched"] == [f"{T}:{file_id}"]


def test_a_disposition_never_covers_a_different_file() -> None:
    report, _ = synthetic_report()
    assert not f1.check_f1(report, "dev", f1.Dispositions(entries=(entry(fid()),))).passed


def test_disposition_errors_fail_closed_in_every_environment() -> None:
    report = detect(Runner([]))
    for env in f1.ENVIRONMENTS:
        check = f1.check_f1(report, env, f1.Dispositions(errors=("bad",)))
        assert not check.passed and check.data["disposition_errors"] == ["bad"]


def test_an_unknown_environment_fails() -> None:
    assert not f1.check_f1(detect(Runner([])), "qa", f1.Dispositions()).passed


def test_check_output_names_no_key_and_no_file_name() -> None:
    file_id = fid()
    secret_key = f"tenants/{T}/documents/{file_id}/final/{uuid.uuid4()}/payroll-SECRET.csv"
    report = detect(
        Runner([row(file_id=file_id, storage_key=secret_key, checksum_verified_at=None)])
    )
    check = f1.check_f1(report, "prod", f1.Dispositions())
    blob = repr(check)
    assert "payroll" not in blob and "tenants/" not in blob and "/final/" not in blob
    assert "etag-1" not in blob


# --- the dispositions file ---------------------------------------------------------------


def test_the_shipped_dispositions_file_is_valid() -> None:
    from promotion.config import load_config

    loaded = load_dispositions(load_config().f1_dispositions)
    assert loaded.errors == ()
    assert {e.env for e in loaded.entries} <= {"dev"}


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "d.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_dispositions_for_other_environments_are_errors(tmp_path: Path) -> None:
    body = f"""
version: 1
dispositions:
  - env: prod
    ref: "{T}:{fid()}"
    classification: final_key_no_verified_digest
    reason: x
    recorded: 2026-10-06
"""
    loaded = load_dispositions(write(tmp_path, body))
    assert loaded.entries == () and len(loaded.errors) == 1 and "dev only" in loaded.errors[0]


def test_a_well_formed_dispositions_file_is_read(tmp_path: Path) -> None:
    body = f"""
version: 1
dispositions:
  - env: dev
    ref: "{T}:{T2}"
    classification: final_key_no_verified_digest
    reason: " a reason "
    recorded: 2026-10-06
"""
    loaded = load_dispositions(write(tmp_path, body))
    assert loaded.errors == () and loaded.entries[0].reason == "a reason"
    assert loaded.entries[0].ref == f"{T}:{T2}"


@pytest.mark.parametrize(
    "item",
    [
        "env: dev\n    ref: nope\n    classification: final_key_no_verified_digest\n    reason: x\n    recorded: 2026-10-06",
        f'env: dev\n    ref: "{T}:{T2}"\n    classification: verified_digest\n    reason: x\n    recorded: 2026-10-06',
        f'env: dev\n    ref: "{T}:{T2}"\n    classification: final_key_no_verified_digest\n    reason: ""\n    recorded: 2026-10-06',
        f'env: dev\n    ref: "{T}:{T2}"\n    classification: final_key_no_verified_digest\n    reason: x\n    recorded: yesterday',
        f'env: mars\n    ref: "{T}:{T2}"\n    classification: final_key_no_verified_digest\n    reason: x\n    recorded: 2026-10-06',
        f'env: dev\n    ref: "{T.upper()}:{T2}"\n    classification: final_key_no_verified_digest\n    reason: x\n    recorded: 2026-10-06',
        "just a string",
    ],
)
def test_malformed_dispositions_are_errors(tmp_path: Path, item: str) -> None:
    loaded = load_dispositions(write(tmp_path, f"version: 1\ndispositions:\n  - {item}\n"))
    assert loaded.entries == () and len(loaded.errors) == 1


def test_unparseable_or_oddly_shaped_files_are_errors_and_a_missing_file_is_empty(
    tmp_path: Path,
) -> None:
    assert load_dispositions(write(tmp_path, "a: [unclosed")).errors
    assert load_dispositions(write(tmp_path, "- just\n- a list\n")).errors
    assert load_dispositions(write(tmp_path, "version: 1\nsurprise: 1\n")).errors
    assert load_dispositions(write(tmp_path, "version: 1\ndispositions: 3\n")).errors
    assert load_dispositions(tmp_path / "absent.yaml") == f1.Dispositions()
    assert load_dispositions(write(tmp_path, "")) == f1.Dispositions()


# --- read-only by construction -------------------------------------------------------------

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|call|do|vacuum|"
    r"analyze|merge|lock|comment|reindex|cluster|refresh|listen|notify|set|reset|execute)\b",
    re.IGNORECASE,
)


def test_every_statement_is_a_single_select() -> None:
    assert f1.SQL_STATEMENTS
    for sql in f1.SQL_STATEMENTS:
        assert sql.lstrip().lower().startswith("select"), sql[:40]
        assert ";" not in sql
        # `set_config` and friends would be a write; whole-word matching keeps column names out
        assert not FORBIDDEN.search(sql), FORBIDDEN.search(sql)
        assert "set_config" not in sql.lower() and "nextval" not in sql.lower()


def test_the_only_other_statements_are_begin_read_only_and_rollback() -> None:
    assert f1._BEGIN_READ_ONLY == "begin transaction read only"
    assert f1._ROLLBACK == "rollback"
    tree = ast.parse(Path(f1.__file__).read_text(encoding="utf-8"))
    sql_names = {"_Q_GUARD", "_Q_SCHEMA", "_Q_TOTALS", "_Q_NOT_RELEASABLE", "_Q_RELEASABLE"}
    seen_execute: list[str] = []
    seen_fetch: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"execute", "executemany", "copy_records_to_table"}:
                arg = node.args[0]
                assert isinstance(arg, ast.Name), "execute takes a named constant only"
                seen_execute.append(arg.id)
            if node.func.attr in {"fetch", "fetchrow", "fetchval"}:
                arg = node.args[0]
                assert isinstance(arg, ast.Name) and arg.id == "sql"
                seen_fetch.append(arg.id)
    assert set(seen_execute) == {"_BEGIN_READ_ONLY", "_ROLLBACK"}
    assert seen_fetch == ["sql"]
    # `run(sql)` is only ever called with the module's own statements
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run":
            arg = node.args[0]
            assert isinstance(arg, ast.Name) and arg.id in sql_names


def test_the_rule_is_the_products_not_a_copy() -> None:
    from koras_api.core import file_release

    assert f1.releasable is file_release.releasable
    assert file_release.RELEASABLE_SQL in f1._Q_RELEASABLE
    assert file_release.RELEASABLE_SQL in f1._Q_NOT_RELEASABLE


def test_a_connection_string_is_redacted_in_errors() -> None:
    url = "postgresql://user:p%40ss@db.example.com:5432/postgres?sslmode=require"
    cleaned = f1.redact(f"could not connect to {url} and also postgres://x:y@h/db", url)
    assert (
        "p%40ss" not in cleaned and "postgres://" not in cleaned and "postgresql://" not in cleaned
    )


# --- the command line ---------------------------------------------------------------------


@pytest.fixture
def product(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A valid configuration file for the CLI, and an environment with no admin URL."""
    import yaml
    from promotion_support import raw_config

    path = tmp_path / "promotion.yaml"
    path.write_text(yaml.safe_dump(raw_config()), encoding="utf-8")
    monkeypatch.delenv("DATABASE_ADMIN_URL", raising=False)
    monkeypatch.delenv("DOPPLER_CONFIG", raising=False)
    monkeypatch.delenv("DOPPLER_PROJECT", raising=False)
    return str(path)


def _args(product: str, *extra: str) -> list[str]:
    return ["--config", product, "--env", "dev", *extra]


def test_the_cli_fails_without_a_url(product, monkeypatch, capsys) -> None:
    monkeypatch.setenv("DOPPLER_CONFIG", "dev")
    assert f1.main(_args(product), runner=FakeRunner()) == 1
    assert "not set" in capsys.readouterr().out


def test_the_cli_fails_on_an_invalid_configuration(tmp_path, capsys) -> None:
    assert f1.main(["--config", str(tmp_path / "none.yaml"), "--env", "dev"]) == 1
    assert capsys.readouterr().out.startswith("FAIL")


@pytest.mark.parametrize("bound", [None, "test"])
def test_the_cli_refuses_a_url_not_bound_to_the_environment(
    bound, product, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nobody:hunter2@127.0.0.1:1/none")
    if bound is not None:
        monkeypatch.setenv("DOPPLER_CONFIG", bound)

    def no_connect(url: str) -> None:
        raise AssertionError("must not connect when the URL is not bound to --env")

    monkeypatch.setattr(f1, "run_against_database", no_connect)
    assert f1.main(_args(product), runner=FakeRunner()) == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL") and "bound" in out and "hunter2" not in out


def test_allow_unbound_is_the_explicit_override(product, monkeypatch, capsys) -> None:
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nobody:hunter2@127.0.0.1:1/none")
    reached: list[str] = []

    def fake(url: str) -> f1.F1Report:
        reached.append("connected")
        raise f1.F1Error("stop here")

    monkeypatch.setattr(f1, "run_against_database", fake)
    assert f1.main(_args(product, "--allow-unbound"), runner=FakeRunner()) == 1
    assert reached == ["connected"]
    capsys.readouterr()


def test_a_connect_error_reports_only_the_exception_class(monkeypatch) -> None:
    import asyncpg

    async def refuse(*args: Any, **kwargs: Any) -> None:
        raise OSError("connect failed for postgresql://u:hunter2@10.0.0.9/db password hunter2")

    monkeypatch.setattr(asyncpg, "connect", refuse)
    with pytest.raises(F1Error) as caught:
        f1.run_against_database("postgresql://u:hunter2@10.0.0.9/db")
    assert str(caught.value) == "the database is unreachable (OSError)"


def test_the_cli_reports_an_unreachable_database_redacted(product, monkeypatch, capsys) -> None:
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nobody:hunter2@127.0.0.1:1/none")
    monkeypatch.setenv("DOPPLER_CONFIG", "dev")
    assert f1.main(_args(product), runner=FakeRunner()) == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL") and "hunter2" not in out and "postgresql://" not in out


def test_the_gate_reads_the_admin_url_from_the_environments_own_store(
    tmp_path, monkeypatch
) -> None:
    config = make_config(tmp_path)
    seen: list[str] = []

    def fake(url: str) -> f1.F1Report:
        seen.append(url)
        return detect(Runner([]))

    monkeypatch.setattr(f1, "run_against_database", fake)
    from promotion.adapters import build_adapters

    runner = FakeRunner(store={("stg", "DATABASE_ADMIN_URL"): "postgresql://u:p@h/db"})
    store, _ = build_adapters(config, runner)
    assert f1.check_for_environment("stg", config, store).passed
    assert seen == ["postgresql://u:p@h/db"]
    # the same call for another environment finds no URL there and FAILS: never another's
    failed = f1.check_for_environment("prod", config, store)
    assert not failed.passed and "no DATABASE_ADMIN_URL" in failed.detail
    erroring = FakeRunner(store={("dev", "DATABASE_ADMIN_URL"): ERROR})
    store2, _ = build_adapters(config, erroring)
    assert not f1.check_for_environment("dev", config, store2).passed
