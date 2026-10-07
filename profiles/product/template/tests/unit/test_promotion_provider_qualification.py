# ruff: noqa: ANN001, ANN003, ANN201, ANN202, ANN401, E501, SLF001
"""Provider qualification: junit evaluation, record verification, and the list that cannot rot."""

from __future__ import annotations

import ast
import copy
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from promotion import provider_qualification as pq
from promotion.adapters import AdapterError, build_adapters
from promotion.config import REPO_ROOT
from promotion_support import ERROR, FakeRunner, make_config

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
FORGED = "m12_forged_nonempty_provenance"


def _all_pass() -> dict[str, str]:
    out: dict[str, str] = {}
    for node in pq.required_nodes():
        for name in node.junit_names:
            out[f"{Path(node.file).stem}::{name}"] = "passed"
    return out


def _junit(results: dict[str, str]) -> str:
    cases = []
    for key, outcome in results.items():
        stem, name = key.split("::", 1)
        child = {
            "passed": "",
            "skipped": '<skipped message="needs the store"/>',
            "failed": '<failure message="x"/>',
            "error": '<error message="x"/>',
        }[outcome]
        cases.append(
            f'<testcase classname="tests.integration.{stem}" name="{name}">{child}</testcase>'
        )
    return f'<testsuites><testsuite name="pytest">{"".join(cases)}</testsuite></testsuites>'


def _record(**over):
    record = pq.build_record(
        env="dev",
        results=_all_pass(),
        fingerprint="f" * 64,
        guard_hash="g" * 64,
        provider="s3-compatible",
        commit="abc123",
        now=NOW - timedelta(days=1),
        duration_seconds=70.0,
    )
    record.update(over)
    return record


# --- junit ----------------------------------------------------------------------------------------


def test_all_required_cases_passing_is_a_pass():
    check = pq.evaluate_check(pq.parse_junit(_junit(_all_pass())))
    assert check.passed and check.data["skipped"] == 0 and check.data["failed"] == 0


def test_a_skipped_required_test_fails():
    results = _all_pass()
    results[next(iter(results))] = "skipped"
    check = pq.evaluate_check(pq.parse_junit(_junit(results)))
    assert not check.passed and "skipped" in check.detail


def test_a_missing_required_test_fails():
    results = _all_pass()
    del results[next(k for k in results if "test_A_" in k)]
    check = pq.evaluate_check(pq.parse_junit(_junit(results)))
    assert not check.passed and check.data["missing"] >= 1


def test_a_missing_parametrized_variant_fails():
    results = _all_pass()
    del results[
        "test_upload_checksum_provider::test_I_unsigned_provider_headers_cannot_turn_a_guarded_put_into_a_copy[acl]"
    ]
    check = pq.evaluate_check(pq.parse_junit(_junit(results)))
    assert not check.passed and "m11_unsigned_header_injection" in check.detail


@pytest.mark.parametrize("outcome", ["failed", "error"])
def test_a_failed_or_errored_required_test_fails(outcome):
    results = _all_pass()
    results[next(k for k in results if "test_Q12c" in k)] = outcome
    check = pq.evaluate_check(pq.parse_junit(_junit(results)))
    assert not check.passed and "inv_download_url_possession" in check.detail


@pytest.mark.parametrize("outcome", ["failed", "error", "skipped"])
def test_the_forged_provenance_case_failing_skipping_or_missing_fails_the_qualification(outcome):
    results = _all_pass()
    key = next(k for k in results if "test_Q13" in k)
    results[key] = outcome
    check = pq.evaluate_check(pq.parse_junit(_junit(results)))
    assert not check.passed and FORGED in check.detail
    missing = _all_pass()
    del missing[key]
    check = pq.evaluate_check(pq.parse_junit(_junit(missing)))
    assert not check.passed and FORGED in check.detail and check.data["missing"] >= 1


def test_an_unexpected_extra_skip_fails_even_when_every_required_case_passed():
    results = _all_pass()
    results["test_upload_checksum_provider::test_something_else"] = "skipped"
    check = pq.evaluate_check(pq.parse_junit(_junit(results)))
    assert not check.passed and check.data["skipped"] == 1


def test_an_unexpected_extra_failure_fails_too():
    results = _all_pass()
    results["test_provider_qualification_extra::test_new"] = "failed"
    assert not pq.evaluate_check(pq.parse_junit(_junit(results))).passed


def test_an_empty_junit_fails():
    assert not pq.evaluate_check(pq.parse_junit("<testsuites/>")).passed


# --- environment gate ----------------------------------------------------------------------------

_STORE = {
    "STORAGE_ENDPOINT": "https://s3.example.invalid/storage/v1/s3",
    "STORAGE_BUCKET": "uploads",
    "STORAGE_ACCESS_KEY": "a",
    "STORAGE_SECRET_KEY": "s",
    "E2E_DATABASE_URL": "postgresql+asyncpg://x@127.0.0.1/db",
}


def test_environment_without_storage_credentials_fails_not_skips():
    env = {k: v for k, v in _STORE.items() if not k.startswith("STORAGE_")}
    check = pq.environment_check("dev", env)
    assert check is not None and not check.passed and "no storage credentials" in check.detail


@pytest.mark.parametrize("missing", pq.STORAGE_REQUIRED)
def test_each_missing_credential_is_named_and_fails(missing):
    check = pq.environment_check("dev", {k: v for k, v in _STORE.items() if k != missing})
    assert check is not None and missing in check.detail


def test_environment_without_a_database_fails_and_a_complete_one_is_accepted():
    assert pq.environment_check("dev", {k: v for k, v in _STORE.items() if k != "E2E_DATABASE_URL"})
    assert pq.environment_check("dev", _STORE) is None
    assert pq.environment_check("qa", _STORE) is not None


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://x@127.0.0.1/db",
        "postgresql://x:y@localhost:55434/postgres",
        "postgresql://x:y@[::1]:5432/postgres",
        "postgresql://x:y@LOCALHOST/postgres",
    ],
)
def test_a_loopback_database_is_accepted(url):
    assert pq.environment_check("dev", {**_STORE, "E2E_DATABASE_URL": url}) is None


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://x:y@db.example.com/postgres",
        "postgresql://x:y@10.0.0.5:5432/postgres",
        "postgresql://127.0.0.1@evil.example.com/postgres",  # loopback only as the userinfo
        "postgresql://x:y@evil.example.com/127.0.0.1",
        "postgresql://x:y@localhost.evil.example.com/postgres",
        "postgresql://x:y@127.0.0.1.evil.example.com/postgres",
        "postgresql://x:y@0.0.0.0/postgres",
        "not a url",
        "postgresql://x:y@[::1/postgres",
    ],
)
def test_a_non_loopback_database_is_refused_in_python_not_only_in_the_wrapper(url):
    check = pq.environment_check("dev", {**_STORE, "E2E_DATABASE_URL": url})
    assert check is not None and not check.passed and "loopback" in check.detail


def _store_for(tmp_path, runner):
    store, _ = build_adapters(make_config(tmp_path), runner)
    return store


def test_the_storage_settings_come_from_the_environments_own_secret_store(tmp_path):
    runner = FakeRunner(
        store={
            ("stg", "STORAGE_ENDPOINT"): "https://stg.example.invalid",
            ("stg", "STORAGE_BUCKET"): "stg-files",
            ("stg", "STORAGE_ACCESS_KEY"): "ak",
            ("stg", "STORAGE_SECRET_KEY"): "sk",
            ("prod", "STORAGE_ENDPOINT"): "https://prod.example.invalid",
        }
    )
    resolved = pq.storage_environ(
        "stg",
        _store_for(tmp_path, runner),
        {"E2E_DATABASE_URL": "x", "STORAGE_BUCKET": "ignored"},
        "secret-store",
    )
    assert isinstance(resolved, dict)
    assert resolved["STORAGE_BUCKET"] == "stg-files" and resolved["STORAGE_ENDPOINT"].startswith(
        "https://stg"
    )
    assert resolved["E2E_DATABASE_URL"] == "x"
    assert runner.violations() == []


def test_a_process_environment_never_stands_in_for_the_secret_store_unless_asked(tmp_path):
    process = {"STORAGE_ENDPOINT": "http://127.0.0.1:9000"}
    store = _store_for(tmp_path, FakeRunner())
    from_store = pq.storage_environ("dev", store, process, "secret-store")
    assert isinstance(from_store, dict) and "STORAGE_ENDPOINT" not in from_store
    assert pq.storage_environ("dev", store, process, "process") == process
    assert not pq.storage_environ("dev", store, process, "elsewhere").passed  # type: ignore[union-attr]


def test_an_unreadable_secret_store_fails_not_skips(tmp_path):
    runner = FakeRunner(store={("dev", "STORAGE_ENDPOINT"): ERROR})
    resolved = pq.storage_environ("dev", _store_for(tmp_path, runner), {}, "secret-store")
    assert not resolved.passed  # type: ignore[union-attr]


def test_run_fails_closed_before_starting_pytest_without_credentials(tmp_path):
    check = pq.run("dev", tmp_path / "j.xml", store=_store_for(tmp_path, FakeRunner()), environ={})
    assert not check.passed and not (tmp_path / "j.xml").exists()


# --- run(): the record exists only for a run that is clean in every respect -----------------------


def _fake_subprocess(monkeypatch, junit_results, returncode):
    """Replace subprocess.run: the pytest command writes `junit_results` as its junit file."""
    calls = []

    def fake(argv, **kwargs):
        calls.append(list(argv))
        if argv[0] == "git":
            return subprocess.CompletedProcess(argv, 0, "c" * 40, "")
        junit = next(a for a in argv if a.startswith("--junitxml=")).split("=", 1)[1]
        Path(junit).write_text(_junit(junit_results), encoding="utf-8")
        return subprocess.CompletedProcess(argv, returncode)

    monkeypatch.setattr(pq.subprocess, "run", fake)
    return calls


def _run(tmp_path, **kw):
    return pq.run(
        "dev",
        tmp_path / "j.xml",
        kw.pop("record", tmp_path / "dev.json"),
        store=_store_for(tmp_path, FakeRunner()),
        environ=_STORE,
        source="process",
        now=NOW,
        **kw,
    )


def test_a_clean_run_writes_the_record(tmp_path, monkeypatch):
    calls = _fake_subprocess(monkeypatch, _all_pass(), 0)
    check = _run(tmp_path)
    record = json.loads((tmp_path / "dev.json").read_text(encoding="utf-8"))
    assert check.passed and record["result"] == "PASS"
    assert (
        record["harness_version"] == pq.HARNESS_VERSION
        and record["credentials_source"] == "process"
    )
    assert record["storage_fingerprint"] == pq.storage_fingerprint(
        _STORE["STORAGE_ENDPOINT"], _STORE["STORAGE_BUCKET"], None
    )
    # pytest ran exactly the required nodes, with the project's addopts neutralised
    pytest_call = next(c for c in calls if "pytest" in c)
    assert [a for a in pytest_call if "::" in a] == [n.label for n in pq.required_nodes()]
    assert "addopts=" in pytest_call


def test_clean_junit_with_a_nonzero_exit_is_a_fail_and_leaves_no_record(tmp_path, monkeypatch):
    _fake_subprocess(monkeypatch, _all_pass(), 1)
    check = _run(tmp_path)
    assert not check.passed and "exited 1" in check.detail
    assert not (tmp_path / "dev.json").exists()


def test_a_failing_junit_leaves_no_record_even_with_exit_zero(tmp_path, monkeypatch):
    results = _all_pass()
    results[next(iter(results))] = "failed"
    _fake_subprocess(monkeypatch, results, 0)
    assert not _run(tmp_path).passed
    assert not (tmp_path / "dev.json").exists()


def test_a_stale_pass_record_is_removed_at_the_start_of_every_run(tmp_path, monkeypatch):
    record = tmp_path / "dev.json"
    record.write_text('{"result": "PASS"}', encoding="utf-8")
    # blocked before pytest even starts (no storage credentials) ...
    assert not pq.run(
        "dev", tmp_path / "j.xml", record, store=_store_for(tmp_path, FakeRunner()), environ={}
    ).passed
    assert not record.exists()
    # ... and when pytest produces no junit at all
    record.write_text('{"result": "PASS"}', encoding="utf-8")
    monkeypatch.setattr(
        pq.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 2)
    )
    assert not _run(tmp_path).passed and not record.exists()


# --- record verification: every failure, from a table ---------------------------------------------


def _verify(record, **over):
    args = {"env": "dev", "current_fingerprint": "f" * 64, "current_guard": "g" * 64, "now": NOW}
    args.update(over)
    return pq.verify_record(
        record, args["env"], args["current_fingerprint"], args["current_guard"], args["now"]
    )


def test_a_matching_fresh_record_passes():
    assert _verify(_record()).passed


def _case(slug, status):
    def edit(record):
        record["cases"] = copy.deepcopy(record["cases"])
        record["cases"][slug]["status"] = status

    return edit


def _drop_case(slug):
    def edit(record):
        record["cases"] = {k: v for k, v in record["cases"].items() if k != slug}

    return edit


def _field(**over):
    def edit(record):
        record.update(over)

    return edit


STALE = {
    "another environment": ({"env": "test"}, None),
    "a different store": (
        {"current_fingerprint": pq.storage_fingerprint("https://t", "u", None)},
        None,
    ),
    "no storage configuration": ({"current_fingerprint": None}, None),
    "an empty fingerprint": ({"current_fingerprint": ""}, None),
    "changed guard code": ({"current_guard": "h" * 64}, None),
    "no readable guard code": ({"current_guard": None}, None),
    "an unknown environment": ({"env": "qa"}, None),
    "just over the age limit": (
        {},
        _field(created_at=(NOW - timedelta(days=15)).isoformat()),
    ),
    "a future date": ({}, _field(created_at=(NOW + timedelta(days=1)).isoformat())),
    "a naive timestamp": ({}, _field(created_at="2026-10-05T00:00:00")),
    "no timestamp": ({}, lambda r: r.pop("created_at")),
    "an unparseable timestamp": ({}, _field(created_at="yesterday")),
    "an old harness version": ({}, _field(harness_version=1)),
    "no harness version": ({}, lambda r: r.pop("harness_version")),
    "a future harness version": ({}, _field(harness_version=pq.HARNESS_VERSION + 1)),
    "an old schema": ({}, _field(schema=1)),
    "a failed case": ({}, _case("m06_copy_source_victim_checksum", "failed")),
    "a skipped case": ({}, _case("m01_correct_checksum_upload", "skipped")),
    "a missing case": ({}, _drop_case("m08_delayed_in_flight_put")),
    "a failed forged-provenance case": ({}, _case(FORGED, "failed")),
    "no forged-provenance case": ({}, _drop_case(FORGED)),
    "an extra, unknown case": ({}, lambda r: r["cases"].update({"m99": {"status": "passed"}})),
    "a skipped total": ({}, _field(totals={"skipped": 1, "failed": 0, "missing": 0})),
    "a failed total": ({}, _field(totals={"skipped": 0, "failed": 1, "missing": 0})),
    "a missing total": ({}, _field(totals={"skipped": 0, "failed": 0, "missing": 1})),
    "a verdict that is not PASS": ({}, _field(result="FAIL")),
    "tests that did not pass outside the matrix": ({}, _field(extra_not_passed=["x::y"])),
    "cases that are not a mapping": ({}, _field(cases=[])),
    "a case that is not a mapping": ({}, lambda r: r["cases"].update({FORGED: "passed"})),
}


@pytest.mark.parametrize("name", sorted(STALE))
def test_a_record_is_refused_for_each_of_these(name):
    over, edit = STALE[name]
    record = _record()
    if edit is not None:
        edit(record)
    assert not _verify(record, **over).passed, name


def test_the_age_limit_is_exact():
    assert _verify(_record(created_at=(NOW - timedelta(days=13)).isoformat())).passed
    assert not _verify(_record(created_at=(NOW - timedelta(days=15)).isoformat())).passed
    old = _record(created_at=(NOW - timedelta(days=20)).isoformat())
    assert pq.verify_record(old, "dev", "f" * 64, "g" * 64, NOW, max_age_days=30).passed


@pytest.mark.parametrize("bad", [None, {}, {"schema": 99}, [], "PASS", 3])
def test_unreadable_record_fails(bad):
    assert not _verify(bad).passed


def test_record_contains_no_secret_or_key():
    text = json.dumps(_record())
    assert "tenants/" not in text and "SECRET" not in text and "ACCESS" not in text


# --- the evidence binding: store, guard code and harness, and the forged-provenance case ---------


def _record_before_the_forged_provenance_case():
    """A record exactly as the harness at version 1 issued it: no m12, the old guard code."""
    old_cases = {k: v for k, v in _record()["cases"].items() if k != FORGED}
    return _record(harness_version=1, cases=old_cases, guard_hash="1" * 64)


def test_a_record_issued_before_the_forged_provenance_case_is_stale_on_three_counts():
    old = _record_before_the_forged_provenance_case()
    # (1) the harness version differs
    assert "harness" in _verify(old).detail
    # (2) with the version corrected, the guard code (which covers the suites) differs
    fixed_version = copy.deepcopy(old)
    fixed_version["harness_version"] = pq.HARNESS_VERSION
    assert "changed" in _verify(fixed_version).detail
    # (3) with both corrected, the cases are not exactly the required cases
    fixed_both = copy.deepcopy(fixed_version)
    fixed_both["guard_hash"] = "g" * 64
    assert "not exactly the required" in _verify(fixed_both).detail


def test_the_forged_provenance_case_is_required_and_is_in_the_guard_files():
    assert FORGED in pq.REQUIRED_CASES
    assert pq.EXTRA_SUITE in pq.GUARD_FILES
    assert "12" in {m for matrix, _ in pq.REQUIRED_CASES.values() for m in matrix}
    assert pq.HARNESS_VERSION >= 2


def test_the_record_is_bound_to_the_store_the_guard_code_and_the_harness_and_a_date():
    record = _record()
    assert {"storage_fingerprint", "guard_hash", "harness_version", "created_at"} <= set(record)
    assert record["guard_files"] == list(pq.GUARD_FILES)


# --- fingerprint and guard hash ------------------------------------------------------------------


def test_fingerprint_is_stable_and_separates_stores():
    a = pq.storage_fingerprint("https://e", "uploads", "us-east-1")
    assert a == pq.storage_fingerprint("https://e ", " uploads", None)  # default region, trimmed
    assert len(a) == 64
    assert a != pq.storage_fingerprint("https://e", "other", "us-east-1")
    assert a != pq.storage_fingerprint("https://e2", "uploads", "us-east-1")
    assert a != pq.storage_fingerprint("https://e", "uploads", "eu-west-1")


def test_the_current_fingerprint_is_read_from_the_environments_own_secret_store(tmp_path):
    runner = FakeRunner(
        store={
            ("dev", "STORAGE_ENDPOINT"): "https://e",
            ("dev", "STORAGE_BUCKET"): "b",
            ("test", "STORAGE_ENDPOINT"): "https://other",
            ("test", "STORAGE_BUCKET"): "b",
        }
    )
    store = _store_for(tmp_path, runner)
    assert pq.current_storage_fingerprint("dev", store) == pq.storage_fingerprint(
        "https://e", "b", None
    )
    assert pq.current_storage_fingerprint("test", store) != pq.current_storage_fingerprint(
        "dev", store
    )
    assert pq.current_storage_fingerprint("stg", store) is None  # nothing configured
    erroring = _store_for(tmp_path, FakeRunner(store={("dev", "STORAGE_ENDPOINT"): ERROR}))
    assert pq.current_storage_fingerprint("dev", erroring) is None


def test_the_region_is_part_of_the_current_fingerprint(tmp_path):
    runner = FakeRunner(
        store={
            ("dev", "STORAGE_ENDPOINT"): "https://e",
            ("dev", "STORAGE_BUCKET"): "b",
            ("dev", "STORAGE_REGION"): "eu-west-1",
        }
    )
    assert pq.current_storage_fingerprint(
        "dev", _store_for(tmp_path, runner)
    ) == pq.storage_fingerprint("https://e", "b", "eu-west-1")


def test_guard_hash_changes_when_a_guarded_file_changes(tmp_path):
    files = ("a.py", "b.py")
    (tmp_path / "a.py").write_text("one\n")
    (tmp_path / "b.py").write_text("two\n")
    before = pq.compute_guard_hash(tmp_path, files)
    assert before == pq.compute_guard_hash(tmp_path, files)
    (tmp_path / "b.py").write_text("two changed\n")
    assert pq.compute_guard_hash(tmp_path, files) != before


def test_guard_hash_ignores_line_endings_and_reports_a_missing_file(tmp_path):
    (tmp_path / "a.py").write_bytes(b"x\r\ny\r\n")
    h = pq.compute_guard_hash(tmp_path, ("a.py",))
    (tmp_path / "a.py").write_bytes(b"x\ny\n")
    assert pq.compute_guard_hash(tmp_path, ("a.py",)) == h
    with pytest.raises(OSError):
        pq.compute_guard_hash(tmp_path, ("missing.py",))


def test_the_guard_covers_the_upload_controls_the_finalizer_and_the_qualification_itself():
    required = {
        "services/api/koras_api/core/upload_window.py",
        "services/api/koras_api/core/file_release.py",
        "services/api/koras_api/routers/files.py",
        "services/worker/koras_worker/uploads/finalize.py",
        "tooling/promotion/provider_qualification.py",
        pq.CHECKSUM_SUITE,
        pq.FINALIZE_SUITE,
        pq.EXTRA_SUITE,
    }
    assert required <= set(pq.GUARD_FILES)
    assert len(set(pq.GUARD_FILES)) == len(pq.GUARD_FILES)


def test_the_guard_hash_changes_when_any_guard_file_changes(tmp_path):
    for rel in pq.GUARD_FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x", encoding="utf-8")
    base = pq.compute_guard_hash(tmp_path)
    for rel in pq.GUARD_FILES:
        (tmp_path / rel).write_text("changed", encoding="utf-8")
        assert pq.compute_guard_hash(tmp_path) != base, rel
        (tmp_path / rel).write_text("x", encoding="utf-8")


def test_every_guard_file_exists_and_the_real_hash_computes():
    for rel in pq.GUARD_FILES:
        assert (REPO_ROOT / rel).is_file(), rel
    assert len(pq.compute_guard_hash()) == 64


def test_a_secret_store_that_fails_is_an_adapter_error_not_a_value(tmp_path):
    with pytest.raises(AdapterError):
        _store_for(tmp_path, FakeRunner(store={("dev", "X"): ERROR})).get("dev", "X")


# --- the required list cannot rot ----------------------------------------------------------------


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _functions(path: Path) -> set[str]:
    return {
        n.name
        for n in ast.walk(_tree(path))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _injected_names(path: Path) -> set[str]:
    for n in ast.walk(_tree(path)):
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "INJECTED" for t in n.targets):
            return {k.value for k in n.value.keys}  # type: ignore[attr-defined]
    return set()


def test_required_cases_exist_as_real_tests():
    for node in pq.required_nodes():
        path = REPO_ROOT / node.file
        assert path.is_file(), node.file
        assert node.function in _functions(path), node.label


def test_parametrized_variants_are_exactly_the_suites_injection_table():
    node = next(n for n in pq.required_nodes() if n.params)
    assert set(node.params) == _injected_names(REPO_ROOT / node.file)


def test_every_matrix_row_and_the_invariant_is_covered():
    covered = {m for matrix, _ in pq.REQUIRED_CASES.values() for m in matrix}
    assert covered == {str(i) for i in range(1, 13)} | {"invariant"}
    assert all(nodes for _m, nodes in pq.REQUIRED_CASES.values())


def test_the_suites_hold_exactly_one_skip_and_it_is_the_documented_one():
    """The only skip is `pytestmark` in the finalization suite (no store, no database); the other
    two suites re-export it. A qualification run fails on any skipped required test, so that skip
    cannot be mistaken for a pass; this keeps a second, quieter skip from appearing beside it."""
    expected = {pq.FINALIZE_SUITE: 1, pq.CHECKSUM_SUITE: 0, pq.EXTRA_SUITE: 0}
    for rel, count in expected.items():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert text.count("skipif(") == count, rel
        assert "xfail" not in text and "pytest.skip(" not in text and "mark.skip(" not in text, rel
        assert "pytestmark" in text, rel


# --- the forged-provenance case, read as code ------------------------------------------------------


def _q13():
    tree = _tree(REPO_ROOT / pq.EXTRA_SUITE)
    return next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name.startswith("test_Q13_")
    )


def _function(name: str) -> ast.AST:
    return next(
        n
        for n in ast.walk(_tree(REPO_ROOT / pq.EXTRA_SUITE))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    )


def test_the_forged_provenance_case_builds_weakened_tickets_and_uses_the_real_finalizer():
    # the tickets are the harness's own mechanics: one unguarded, one that signs a forged value
    assert "guarded=False" in ast.unparse(_function("_unguarded"))
    assert "provenance=forged" in ast.unparse(_function("forged_signed_ticket"))
    attempt = ast.unparse(_function("_attempt"))
    assert "TICKETS[ticket]" in attempt and "_finalize(" in attempt, "the REAL UploadFinalizer"
    assert "landed_sha" in attempt, "what landed is measured before the finalizer touches it"
    body = ast.unparse(_q13())
    # a refusal is asserted before anything else, so a finalizer that promotes fails there
    assert "_assert_refused" in body and "FinalizeKind.FINALIZED" in body
    refused = ast.unparse(_function("_assert_refused"))
    assert "FinalizeKind.HELD" in refused and "integrity_mismatch" in refused
    # the digest matches the claim in the copy scenarios, so only provenance can refuse them
    assert "claim=VICTIM" in body and "sha(VICTIM)" in body
    # at least one scenario must land a forged non-empty provenance, or the case is vacuous
    assert "landed_forged >= 1" in body
    # the digest requirement still applies, and the positive control is there
    assert "forged_and_wrong_digest" in body and "honest_key" in body


def test_the_forged_provenance_case_weakens_no_production_guard_and_adds_no_production_path():
    """The only unguarded ticket is the test's own `Run.ticket(guarded=False)`: `guarded` appears
    nowhere in the product's code, and the harness module does not build tickets at all."""
    for rel in (
        "services/api/koras_api/routers/files.py",
        "services/worker/koras_worker/uploads/finalize.py",
        "python-packages/koras-storage/src/koras_storage/__init__.py",
        "tooling/promotion/provider_qualification.py",
    ):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "guarded=False" not in text, rel
