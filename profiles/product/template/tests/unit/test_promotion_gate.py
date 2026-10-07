# ruff: noqa: ANN001, ANN003, ANN202, ANN201, ANN401, E501, SLF001
"""The promotion gate: fail closed, read only, one answer per check, decided from a table."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from promotion import f1, gate
from promotion import provider_qualification as pq
from promotion.config import PromotionConfig
from promotion.result import Check, overall
from promotion_support import (
    ERROR,
    SHA,
    FakeRunner,
    green_ci,
    make_config,
    proc,
    raw_config,
)

ENVS = ("dev", "test", "stg", "prod")
GOOD_REGISTER = (
    "| ID | Type | Severity | Status |\n|---|---|---|---|\n"
    "| SEC-1 | SECURITY | High | RESOLVED |\n| SEC-2 | SECURITY-GAP | Critical | Open |\n"
)
OPEN_REGISTER = GOOD_REGISTER  # SEC-2 is open: the failing one
CLEAN_REGISTER = (
    "| ID | Type | Severity | Status |\n|---|---|---|---|\n| SEC-1 | SECURITY | High | RESOLVED |\n"
)
ENDPOINT = "https://s3.example.invalid/storage/v1/s3"


@dataclass
class World:
    """Everything the gate reads, green by default, with one thing at a time made wrong."""

    env: str
    root: Path
    config: PromotionConfig
    store: dict[tuple[str, str], Any] = field(default_factory=dict)
    secrets: dict[str, Any] = field(default_factory=dict)
    machines: dict[str, Any] = field(default_factory=dict)
    ci: list[tuple[str, ...]] = field(default_factory=list)
    f1_rows: int = 0
    f1_error: str | None = None
    record: dict[str, Any] | None = None

    def runner(self) -> FakeRunner:
        return FakeRunner(
            store=self.store, secrets=self.secrets, machines=self.machines, ci=self.ci, sha=SHA
        )


def _world(tmp_path: Path, env: str, monkeypatch, *, register: str = CLEAN_REGISTER) -> World:
    config = make_config(tmp_path)
    (tmp_path / "docs/security").mkdir(parents=True)
    (tmp_path / "docs/security/REGISTER.md").write_text(register, encoding="utf-8")
    world = World(env=env, root=tmp_path, config=config)
    world.store = {
        (env, "FILE_SCAN_BACKEND"): "clamd",
        (env, "DATABASE_ADMIN_URL"): "postgresql://admin:pw@db.invalid/postgres",
        (env, "STORAGE_ENDPOINT"): ENDPOINT,
        (env, "STORAGE_BUCKET"): "files",
    }
    world.machines = {
        f"shop-clamd-{env}": [{"state": "started", "checks": [{"status": "passing"}]}]
    }
    world.ci = green_ci(config.ci_required_jobs)
    world.record = _good_record(env, pq.storage_fingerprint(ENDPOINT, "files", None))

    def fake_db(url: str) -> f1.F1Report:
        if world.f1_error:
            raise f1.F1Error(world.f1_error)
        rows = tuple(
            f1.RowResult("t", f"f{i}", f1.FINAL_KEY_NO_VERIFIED_DIGEST, False)
            for i in range(world.f1_rows)
        )
        return f1.F1Report(rows, 0, 0, 1, 1, world.f1_rows)

    monkeypatch.setattr(f1, "run_against_database", fake_db)
    return world


def _good_record(env: str, fingerprint: str, **over: Any) -> dict[str, Any]:
    results = {
        f"{Path(node.file).stem}::{name}": "passed"
        for node in pq.required_nodes()
        for name in node.junit_names
    }
    record = pq.build_record(
        env=env,
        results=results,
        fingerprint=fingerprint,
        guard_hash=pq.compute_guard_hash(),
        provider="s3-compatible",
        commit="c" * 40,
        now=datetime.now(UTC) - timedelta(days=1),
        duration_seconds=1.0,
    )
    record.update(over)
    return record


def _evaluate(world: World) -> list[Check]:
    path = world.config.qualification_dir / f"{world.env}.json"
    if world.record is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(world.record), encoding="utf-8")
    runner = world.runner()
    checks = gate.evaluate(world.env, config=world.config, commit=SHA, runner=runner)
    assert runner.violations() == [], "the gate issued a command outside the read-only allowlist"
    return checks


def _failed(checks: list[Check]) -> set[str]:
    return {c.id for c in checks if not c.passed}


# -- the green path, in every environment ------------------------------------------------


@pytest.mark.parametrize("env", ENVS)
def test_everything_green_passes_in_every_environment(env, tmp_path, monkeypatch) -> None:
    checks = _evaluate(_world(tmp_path, env, monkeypatch))
    assert overall(checks) == "PASS", [c for c in checks if not c.passed]
    assert {c.id for c in checks} >= {
        "promotion_config",
        "activation_not_applicable",
        "scanner_configured",
        "scanner_healthy",
        "immutable_finalization",
        "provider_qualification",
        f1.CHECK_ID,
        "ci_suites",
        "security_findings",
    }


# -- one thing wrong at a time: each MUST fail the check that owns it -------------------------

Mutation = Callable[[World], None]


def _store(name: str, value: Any) -> Mutation:
    def apply(w: World) -> None:
        w.store[(w.env, name)] = value

    return apply


def _drop_store(name: str) -> Mutation:
    def apply(w: World) -> None:
        w.store.pop((w.env, name), None)

    return apply


def _machines(rows: Any) -> Mutation:
    def apply(w: World) -> None:
        w.machines[f"shop-clamd-{w.env}"] = rows

    return apply


def _no_scanner_app(w: World) -> None:
    w.machines.clear()


def _ci(edit: Callable[[list[tuple[str, ...]]], None]) -> Mutation:
    def apply(w: World) -> None:
        edit(w.ci)

    return apply


def _record(**over: Any) -> Mutation:
    def apply(w: World) -> None:
        assert w.record is not None
        w.record.update(over)

    return apply


def _no_record(w: World) -> None:
    w.record = None


def _record_for_another_store(w: World) -> None:
    w.record = _good_record(
        w.env, pq.storage_fingerprint("https://elsewhere.invalid", "files", None)
    )


def _record_case(slug: str, status: str) -> Mutation:
    def apply(w: World) -> None:
        assert w.record is not None
        w.record["cases"][slug]["status"] = status

    return apply


def _record_without_case(slug: str) -> Mutation:
    def apply(w: World) -> None:
        assert w.record is not None
        del w.record["cases"][slug]

    return apply


def _f1(rows: int = 0, error: str | None = None) -> Mutation:
    def apply(w: World) -> None:
        w.f1_rows, w.f1_error = rows, error

    return apply


def _register_text(text: str | None) -> Mutation:
    def apply(w: World) -> None:
        path = w.root / "docs/security/REGISTER.md"
        if text is None:
            path.unlink()
        else:
            path.write_text(text, encoding="utf-8")

    return apply


def _drop_job(w: World) -> None:
    w.ci = [r for r in w.ci if r[0] != w.config.ci_required_jobs[0]]


FAILING: dict[str, tuple[Mutation, str]] = {
    "scanner backend is none": (_store("FILE_SCAN_BACKEND", "none"), "scanner_configured"),
    "scanner backend is blank": (_store("FILE_SCAN_BACKEND", ""), "scanner_configured"),
    "scanner backend is a lookalike": (
        _store("FILE_SCAN_BACKEND", "clamd-ish"),
        "scanner_configured",
    ),
    "scanner backend is unset": (_drop_store("FILE_SCAN_BACKEND"), "scanner_configured"),
    "scanner backend cannot be read": (_store("FILE_SCAN_BACKEND", ERROR), "scanner_configured"),
    "scanner app does not exist": (_no_scanner_app, "scanner_healthy"),
    "scanner has no machine": (_machines([]), "scanner_healthy"),
    "scanner machine is stopped": (
        _machines([{"state": "stopped", "checks": [{"status": "passing"}]}]),
        "scanner_healthy",
    ),
    "scanner machine has no checks": (
        _machines([{"state": "started", "checks": []}]),
        "scanner_healthy",
    ),
    "scanner check is critical": (
        _machines([{"state": "started", "checks": [{"status": "critical"}]}]),
        "scanner_healthy",
    ),
    "one of two scanner machines is unhealthy": (
        _machines(
            [
                {"state": "started", "checks": [{"status": "passing"}]},
                {"state": "started", "checks": [{"status": "warning"}]},
            ]
        ),
        "scanner_healthy",
    ),
    "a required CI job is missing": (_drop_job, "ci_suites"),
    "a required CI job failed": (
        _ci(lambda rows: rows.__setitem__(0, (rows[0][0], "completed", "failure", *rows[0][3:]))),
        "ci_suites",
    ),
    "a required CI job is still running": (
        _ci(lambda rows: rows.append((rows[0][0], "in_progress", "", "", "github-actions"))),
        "ci_suites",
    ),
    "a required CI job was reported by another app": (
        _ci(lambda rows: rows.__setitem__(0, (*rows[0][:4], "some-other-app"))),
        "ci_suites",
    ),
    "no provider record exists": (_no_record, "provider_qualification"),
    "the provider record is stale": (
        _record(created_at=(datetime.now(UTC) - timedelta(days=15)).isoformat()),
        "provider_qualification",
    ),
    "the provider record is future-dated": (
        _record(created_at=(datetime.now(UTC) + timedelta(days=2)).isoformat()),
        "provider_qualification",
    ),
    "the provider record is for another store": (
        _record_for_another_store,
        "provider_qualification",
    ),
    "the provider record is for another environment": (
        _record(environment="elsewhere"),
        "provider_qualification",
    ),
    "the guard code changed since the record": (
        _record(guard_hash="0" * 64),
        "provider_qualification",
    ),
    "the record is from an older harness": (_record(harness_version=1), "provider_qualification"),
    "the record is of an older schema": (_record(schema=1), "provider_qualification"),
    "a record case failed": (
        _record_case("m06_copy_source_victim_checksum", "failed"),
        "provider_qualification",
    ),
    "the forged-provenance case is skipped": (
        _record_case("m12_forged_nonempty_provenance", "skipped"),
        "provider_qualification",
    ),
    "the forged-provenance case is absent from the record": (
        _record_without_case("m12_forged_nonempty_provenance"),
        "provider_qualification",
    ),
    "the record's own verdict is not PASS": (_record(result="FAIL"), "provider_qualification"),
    "the environment has no storage endpoint": (
        _drop_store("STORAGE_ENDPOINT"),
        "provider_qualification",
    ),
    "the environment has no storage bucket": (
        _drop_store("STORAGE_BUCKET"),
        "provider_qualification",
    ),
    "an unverified releasable file exists": (_f1(rows=1), f1.CHECK_ID),
    "the F1 database is unreachable": (
        _f1(error="the database is unreachable (OSError)"),
        f1.CHECK_ID,
    ),
    "the F1 role bypasses nothing": (
        _f1(error="the connecting role does not bypass row-level security"),
        f1.CHECK_ID,
    ),
    "no database admin URL": (_drop_store("DATABASE_ADMIN_URL"), f1.CHECK_ID),
    "a blank database admin URL": (_store("DATABASE_ADMIN_URL", "   "), f1.CHECK_ID),
    "the database admin URL cannot be read": (_store("DATABASE_ADMIN_URL", ERROR), f1.CHECK_ID),
    "an unresolved critical security finding": (_register_text(OPEN_REGISTER), "security_findings"),
    "the register is missing": (_register_text(None), "security_findings"),
    "the register is empty": (_register_text(""), "security_findings"),
    "the register has a header and no rows": (
        _register_text("| ID | Type | Severity | Status |\n|---|---|---|---|\n"),
        "security_findings",
    ),
    "a register row cannot be parsed": (
        _register_text(CLEAN_REGISTER + "| SEC-3 | SECURITY | High | a | b | Open |\n"),
        "security_findings",
    ),
}


@pytest.mark.parametrize("env", ENVS)
@pytest.mark.parametrize("name", sorted(FAILING))
def test_each_missing_invalid_or_stale_piece_of_evidence_fails_its_own_check(
    name, env, tmp_path, monkeypatch
) -> None:
    mutation, expected = FAILING[name]
    world = _world(tmp_path, env, monkeypatch)
    mutation(world)
    checks = _evaluate(world)
    assert overall(checks) == "FAIL"
    assert expected in _failed(checks), (name, _failed(checks))


def test_a_failure_in_one_environment_does_not_fail_another(tmp_path, monkeypatch) -> None:
    """The scanner of `test` being down says nothing about `dev`: each environment reads its own."""
    world = _world(tmp_path, "dev", monkeypatch)
    world.store[("test", "FILE_SCAN_BACKEND")] = "none"
    assert overall(_evaluate(world)) == "PASS"
    other = _world(tmp_path / "o", "test", monkeypatch)
    other.store[("test", "FILE_SCAN_BACKEND")] = "none"
    assert "scanner_configured" in _failed(_evaluate(other))


def test_one_environments_record_never_vouches_for_another(tmp_path, monkeypatch) -> None:
    world = _world(tmp_path, "test", monkeypatch)
    world.record = _good_record("dev", pq.storage_fingerprint(ENDPOINT, "files", None))
    assert "provider_qualification" in _failed(_evaluate(world))


def test_two_environments_on_one_store_still_need_their_own_record(tmp_path, monkeypatch) -> None:
    world = _world(tmp_path, "stg", monkeypatch)
    world.record = _good_record("prod", pq.storage_fingerprint(ENDPOINT, "files", None))
    assert "provider_qualification" in _failed(_evaluate(world))


# -- unknown environment, no configuration, no checks ----------------------------------------


@pytest.mark.parametrize("env", ["qa", "", "DEV", "prod ", "../dev"])
def test_an_unknown_environment_fails_and_runs_nothing(env, tmp_path) -> None:
    runner = FakeRunner()
    checks = gate.evaluate(env, config=make_config(tmp_path), runner=runner)
    assert overall(checks) == "FAIL" and [c.id for c in checks] == ["environment"]
    assert runner.calls == []


def test_a_missing_or_invalid_configuration_is_a_single_fail(tmp_path) -> None:
    checks = gate.evaluate("dev", config_path=tmp_path / "absent.yaml")
    assert [c.id for c in checks] == ["promotion_config"] and overall(checks) == "FAIL"
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\n", encoding="utf-8")
    checks = gate.evaluate("dev", config_path=bad)
    assert [c.id for c in checks] == ["promotion_config"] and overall(checks) == "FAIL"


def test_a_gate_with_no_checks_fails() -> None:
    assert overall([]) == "FAIL"
    assert overall([Check("a", "PASS", "")]) == "PASS"
    assert overall([Check("a", "PASS", ""), Check("b", "FAIL", "")]) == "FAIL"


# -- data import is optional, and a product that has it cannot skip its checks ----------------


def test_a_product_with_data_import_files_but_no_activation_section_fails(
    tmp_path, monkeypatch
) -> None:
    world = _world(tmp_path, "dev", monkeypatch)
    (tmp_path / "local/config").mkdir(parents=True)
    (tmp_path / "local/config/import-activation.yaml").write_text(
        "environments: {}\n", encoding="utf-8"
    )
    checks = _evaluate(world)
    assert "activation_policy" in _failed(checks)


def test_the_package_on_disk_without_an_activation_section_also_fails(
    tmp_path, monkeypatch
) -> None:
    world = _world(tmp_path, "dev", monkeypatch)
    (tmp_path / "python-packages/koras-import").mkdir(parents=True)
    assert "activation_policy" in _failed(_evaluate(world))


# -- the static checks -----------------------------------------------------------------------


def test_the_static_checks_pass_in_this_product_and_fail_on_an_empty_tree(tmp_path) -> None:
    assert gate.check_finalization().status == "PASS"
    assert gate.check_finalization(tmp_path).status == "FAIL"
    assert gate.check_import_gate_installed(tmp_path).status == "FAIL"


def test_a_finalization_component_that_lost_its_marker_fails(tmp_path) -> None:
    from promotion.config import REPO_ROOT

    for rel in (
        "services/api/koras_api/core/secure_files.py",
        "services/worker/koras_worker/uploads/finalize.py",
        "services/worker/koras_worker/tasks/finalize.py",
        "services/worker/koras_worker/tasks/scan.py",
        "services/api/koras_api/core/upload_window.py",
        "services/api/koras_api/core/file_release.py",
        "services/api/koras_api/routers/files.py",
    ):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((REPO_ROOT / rel).read_text(encoding="utf-8"), encoding="utf-8")
    assert gate.check_finalization(tmp_path).passed
    constant = tmp_path / "services/api/koras_api/core/secure_files.py"
    constant.write_text(
        constant.read_text(encoding="utf-8").replace("SECURE_FILES = True", "SECURE_FILES = False"),
        encoding="utf-8",
    )
    assert not gate.check_finalization(tmp_path).passed


# -- CI parsing, on its own --------------------------------------------------------------------


def _config_with_jobs(tmp_path) -> PromotionConfig:
    return make_config(tmp_path)


def test_ci_needs_a_full_sha_and_a_readable_answer(tmp_path) -> None:
    config = _config_with_jobs(tmp_path)
    jobs = config.ci_required_jobs
    assert gate.check_ci("abc", config, FakeRunner(ci=green_ci(jobs))).status == "FAIL"
    assert gate.check_ci(SHA, config, lambda argv: proc("", 1)).status == "FAIL"
    assert gate.check_ci(SHA, config, FakeRunner(ci=green_ci(jobs))).status == "PASS"
    # no commit given: HEAD is asked of git, and a git that cannot answer is a FAIL
    assert (
        gate.check_ci(None, config, FakeRunner(ci=green_ci(jobs), sha="nonsense")).status == "FAIL"
    )
    assert gate.check_ci(None, config, FakeRunner(ci=green_ci(jobs))).status == "PASS"


def test_ci_latest_run_of_a_job_wins(tmp_path) -> None:
    config = _config_with_jobs(tmp_path)
    jobs = config.ci_required_jobs
    first = jobs[0]
    later_failure = [
        *green_ci(jobs),
        (first, "completed", "failure", "2026-10-06T11:00:00Z", "github-actions"),
    ]
    assert gate.check_ci(SHA, config, FakeRunner(ci=later_failure)).status == "FAIL"
    earlier_failure = [
        (first, "completed", "failure", "2026-10-06T09:00:00Z", "github-actions"),
        *green_ci(jobs),
    ]
    assert gate.check_ci(SHA, config, FakeRunner(ci=earlier_failure)).status == "PASS"


def test_a_spoofed_success_cannot_rescue_a_genuine_failure(tmp_path) -> None:
    config = _config_with_jobs(tmp_path)
    jobs = config.ci_required_jobs
    rows = green_ci(jobs)
    rows[0] = (rows[0][0], "completed", "failure", rows[0][3], "github-actions")
    rows.append((rows[0][0], "completed", "success", "2026-10-06T13:00:00Z", "some-other-app"))
    assert gate.check_ci(SHA, config, FakeRunner(ci=rows)).status == "FAIL"


def test_a_job_the_product_does_not_require_is_ignored_and_a_malformed_row_is_skipped(
    tmp_path,
) -> None:
    config = _config_with_jobs(tmp_path)
    rows = [
        *green_ci(config.ci_required_jobs),
        ("Some other job", "completed", "failure", "x", "github-actions"),
    ]
    assert gate.check_ci(SHA, config, FakeRunner(ci=rows)).status == "PASS"
    assert gate.check_ci(SHA, config, FakeRunner(ci=[("only", "three", "fields")])).status == "FAIL"


def test_the_default_runner_runs_in_the_checkout(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        return proc("")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    gate._run(["gh", "api", "x"])
    assert seen["cwd"] == gate.REPO_ROOT


# -- the guard around every collector, and the record ------------------------------------------


def test_a_collector_that_raises_becomes_a_fail_naming_only_the_class(
    tmp_path, monkeypatch
) -> None:
    world = _world(tmp_path, "dev", monkeypatch)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("secret-looking-detail postgresql://u:p@h/db")

    monkeypatch.setattr(gate, "check_finalization", boom)
    checks = _evaluate(world)
    failed = [c for c in checks if c.id == "immutable_finalization"]
    assert [c.status for c in failed] == ["FAIL"]
    assert "RuntimeError" in failed[0].detail
    assert "secret-looking-detail" not in failed[0].detail and "postgresql" not in failed[0].detail
    assert len(checks) > 5  # the others still ran


def test_main_leaves_no_stale_pass_if_the_run_does_not_finish(tmp_path, monkeypatch) -> None:
    out = tmp_path / "gate.json"
    out.write_text(json.dumps({"result": "PASS"}), encoding="utf-8")

    def crash(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(gate, "evaluate", crash)
    with pytest.raises(KeyboardInterrupt):
        gate.main(["--env", "dev", "--out", str(out)])
    assert json.loads(out.read_text(encoding="utf-8"))["result"] == "FAIL"


def test_main_writes_the_final_record_over_the_placeholder(tmp_path, monkeypatch) -> None:
    out = tmp_path / "gate.json"
    monkeypatch.setattr(gate, "evaluate", lambda *a, **k: [Check("x", "PASS", "fine")])
    assert gate.main(["--env", "dev", "--out", str(out)]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["result"] == "PASS" and [c["id"] for c in written["checks"]] == ["x"]
    assert written["schema"] == "koras.promotion-gate/1"


def test_main_exits_nonzero_on_a_fail(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(gate, "evaluate", lambda *a, **k: [Check("x", "FAIL", "no")])
    assert gate.main(["--env", "dev"]) == 1


def test_record_shape_and_exit_code() -> None:
    checks = [Check(f1.CHECK_ID, "PASS", "x", {"F1_UNVERIFIED_RELEASABLE_COUNT": 0})]
    rec = gate.record("dev", checks)
    assert rec["result"] == "PASS" and rec["F1_UNVERIFIED_RELEASABLE_COUNT"] == 0
    assert gate.record("dev", [])["result"] == "FAIL"
    assert gate.record("dev", [Check("a", "PASS", "")])["F1_UNVERIFIED_RELEASABLE_COUNT"] is None


def test_the_shipped_configuration_drives_the_gate_to_a_clean_fail_with_no_commands_run(
    monkeypatch,
) -> None:
    """The gate against the product as generated: FAIL (nothing is promoted by default), and the
    only commands it issues are reads, answered here as if every external system were absent."""
    runner = FakeRunner()
    checks = gate.evaluate("dev", commit=SHA, runner=runner)
    assert overall(checks) == "FAIL"
    assert runner.violations() == []
    assert "provider_qualification" in _failed(checks)


# -- the raw configuration drives the gate the same way ---------------------------------------


def test_the_required_ci_jobs_come_from_the_configuration(tmp_path) -> None:
    def edit(raw: dict[str, Any]) -> None:
        raw["ci"]["required_jobs"] = ["Only this"]

    config = make_config(tmp_path, edit=edit)
    assert gate.check_ci(SHA, config, FakeRunner(ci=green_ci(["Only this"]))).passed
    assert not gate.check_ci(SHA, config, FakeRunner(ci=green_ci(["Lint", "Test", "Build"]))).passed
    assert raw_config()["ci"]["required_jobs"] != ["Only this"]
