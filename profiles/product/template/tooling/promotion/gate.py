"""The promotion gate: one read-only command, PASS or FAIL with evidence.

    PYTHONPATH=tooling uv run python -m promotion gate --env test [--commit <sha>] [--out f.json]

It asks, for a target environment, whether the secure-files chain (and, where the product has it,
data import) may be *relied on* there. It never activates anything: every collector is a read (a
secret-store get, `flyctl ... list`, `gh api` GET, a read-only database transaction, files in this
checkout). Any check that cannot establish its answer FAILS; zero checks is a FAIL. No secret,
object key or file name is printed or recorded.

Checks (ids):

* ``promotion_config`` - `local/config/promotion.yaml` is present and valid. Without it nothing
  else can be asked, and that is a FAIL.
* ``activation_*`` and ``imports_off`` - `activation.py`, only for a product generated with
  `data_import` (its `promotion.yaml` has an `activation` section; a product without one reports
  ``activation_not_applicable``): the declaration, the secret store's effective value, deployment
  drift, API/worker agreement. For an environment declared `disabled`, imports must currently be
  OFF. For one declared `enabled` the check asserts the configuration is canonical and consistent.
* ``scanner_configured`` / ``scanner_healthy`` - the environment's secret store selects the
  required scanner backend (never `none`), and its scanner app exists with every machine started
  and every health check passing.
* ``immutable_finalization`` - the finalizer, the finalize-first hand-off to the scanner, the
  incoming-key ticket and the generated `SECURE_FILES = True` are present in this checkout (no
  switch: it is the only path).
* ``provider_qualification`` - a fresh record for THIS environment's store and THIS code.
* ``f1_unverified_releasable`` - `f1.py` against the environment's own database.
* ``ci_suites`` - every required CI job succeeded on the commit.
* ``import_gate_installed`` - only with `data_import`: the activation gate is in the API router,
  the worker task and its tests.
* ``security_findings`` - no unresolved Critical/High finding of type SECURITY or SECURITY-GAP in
  the product's register (the whole register, not a hand-picked subset); `register.py` is strict.

Every collector runs behind a guard: an unexpected exception becomes a FAIL naming only the
exception class.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess  # noqa: S404 - read-only `git rev-parse` / `gh api` calls, argument lists
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import activation, f1, provider_qualification, register
from .adapters import AdapterError, DeployTarget, Runner, SecretStore, build_adapters
from .config import REPO_ROOT, ConfigError, PromotionConfig, load_config
from .result import ENVIRONMENTS, Check, fail, ok, overall

#: The app slug of GitHub Actions check runs; a required name from another app is ignored.
CI_APP_SLUG = "github-actions"


class _Unreadable(Exception):
    """A collector could not establish its answer; the caller turns this into a FAIL."""


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    # cwd is the checkout: `gh api repos/{owner}/{repo}` resolves the repository from it.
    exe = shutil.which(argv[0]) or argv[0]  # a Windows .cmd shim is not found by name alone
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [exe, *argv[1:]], capture_output=True, text=True, timeout=120, check=False, cwd=REPO_ROOT
    )


def _try(runner: Runner, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return runner(argv)
    except (OSError, subprocess.SubprocessError) as exc:
        raise _Unreadable(f"{argv[0]} could not be run") from exc


# -- scanner ---------------------------------------------------------------------------


def check_scanner(
    env: str, config: PromotionConfig, store: SecretStore, deploy: DeployTarget
) -> list[Check]:
    out: list[Check] = []
    try:
        backend = store.get(env, config.scanner_backend_setting)
    except AdapterError as exc:
        return [fail("scanner_configured", f"{env}: {exc}")]
    required = config.scanner_required_backend
    if (backend or "").strip().lower() != required.lower():
        out.append(
            fail(
                "scanner_configured",
                f"{env}: {config.scanner_backend_setting} is "
                f"{'unset' if backend is None else 'not ' + required}; `none` grants no exception",
            )
        )
    else:
        out.append(
            ok("scanner_configured", f"{env}: {config.scanner_backend_setting} is {required}")
        )
    app = config.environments[env].apps["clamd"]
    try:
        machines = deploy.machines(app)
    except AdapterError as exc:
        out.append(fail("scanner_healthy", f"{env}: {exc}"))
        return out
    if not machines:
        out.append(fail("scanner_healthy", f"{app}: no machine exists"))
        return out
    bad: list[str] = []
    for m in machines:
        checks = m.get("checks")
        if m.get("state") != "started":
            bad.append("a machine is not started")
        elif not checks or any(c.get("status") != "passing" for c in checks if isinstance(c, dict)):
            bad.append("a machine reports no passing health check")
    if bad:
        out.append(fail("scanner_healthy", f"{app}: {sorted(set(bad))[0]}", machines=len(machines)))
    else:
        out.append(
            ok("scanner_healthy", f"{app}: {len(machines)} machine(s) started, checks passing")
        )
    return out


# -- static code presence --------------------------------------------------------------


def _contains(path: str, needle: str, root: Path) -> bool:
    try:
        return needle in (root / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def check_finalization(root: Path = REPO_ROOT) -> Check:
    needed = {
        "services/api/koras_api/core/secure_files.py": "SECURE_FILES = True",
        "services/worker/koras_worker/uploads/finalize.py": "class UploadFinalizer",
        "services/worker/koras_worker/tasks/finalize.py": "on_final",
        "services/worker/koras_worker/tasks/scan.py": "hand_off_to_scanner",
        "services/api/koras_api/core/upload_window.py": "def incoming_key",
        "services/api/koras_api/core/file_release.py": "RELEASABLE_SQL",
        "services/api/koras_api/routers/files.py": "incoming_key(",
    }
    missing = [p for p, n in needed.items() if not _contains(p, n, root)]
    if missing:
        return fail(
            "immutable_finalization",
            f"{len(missing)} finalization component(s) absent from this checkout",
        )
    return ok(
        "immutable_finalization",
        "ticket, finalizer and finalize-first scan hand-off present (no switch: sole path)",
    )


def check_import_gate_installed(root: Path = REPO_ROOT) -> Check:
    needed = {
        "services/api/koras_api/routers/imports.py": "require_import_activation",
        "services/worker/koras_worker/tasks/imports.py": "_refuse_while_disabled",
        "tests/unit/test_import_activation_gate.py": "def test_",
    }
    missing = [p for p, n in needed.items() if not _contains(p, n, root)]
    if missing:
        return fail("import_gate_installed", f"{len(missing)} activation gate component(s) absent")
    return ok(
        "import_gate_installed",
        "activation gate present in the API router, the worker task and its tests",
    )


# -- register --------------------------------------------------------------------------


def check_findings(config: PromotionConfig) -> Check:
    try:
        found = register.unresolved_security_findings(
            config.register_path, config.register_id_pattern, config.register_chain_ids
        )
    except register.RegisterError as exc:
        return fail("security_findings", str(exc))
    if found:
        chain = sum(1 for f in found if f["scope"] == "chain")
        return fail(
            "security_findings",
            f"{len(found)} unresolved Critical/High security finding(s) "
            f"({chain} on the upload/release/import chain)",
            findings=found,
        )
    return ok(
        "security_findings",
        "no unresolved Critical/High security finding in the register",
        findings=[],
    )


# -- CI --------------------------------------------------------------------------------


def check_ci(commit: str | None, config: PromotionConfig, runner: Runner = _run) -> Check:
    required = config.ci_required_jobs
    try:
        sha = commit
        if not sha:
            proc = _try(runner, ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"])
            sha = proc.stdout.strip() if proc.returncode == 0 else ""
        if not re.fullmatch(r"[0-9a-f]{40}", sha or ""):
            raise _Unreadable("no full commit sha to evaluate")
        proc = _try(
            runner,
            [
                "gh",
                "api",
                f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs?per_page=100",
                "--paginate",
                "--jq",
                '.check_runs[] | [.name, .status, (.conclusion // ""), (.completed_at // ""), '
                '(.app.slug // "")] | @tsv',
            ],
        )
        if proc.returncode != 0:
            raise _Unreadable(
                "the commit's check runs could not be read (not pushed, or gh unauthenticated)"
            )
    except _Unreadable as exc:
        return fail("ci_suites", str(exc))
    latest: dict[str, tuple[str, str, str]] = {}
    in_flight: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) not in (4, 5):
            continue
        if len(parts) == 5 and parts[4] and parts[4] != CI_APP_SLUG:
            continue  # a check run some other app reported under a required name
        name, status, conclusion, completed = parts[:4]
        if name in required and status != "completed":
            in_flight.add(name)
        elif name not in latest or completed >= latest[name][2]:
            latest[name] = (status, conclusion, completed)
    bad = [
        j
        for j in required
        if j in in_flight or latest.get(j, ("", "", ""))[:2] != ("completed", "success")
    ]
    if bad:
        return fail(
            "ci_suites",
            f"{len(bad)} required CI job(s) not green on {sha[:7]}: {', '.join(bad)}",
            commit=sha,
        )
    return ok(
        "ci_suites",
        f"all {len(required)} required CI jobs succeeded on {sha[:7]}",
        commit=sha,
    )


# -- provider and F1 -------------------------------------------------------------------


def check_provider(
    env: str, config: PromotionConfig, store: SecretStore, record_path: Path | None
) -> Check:
    path = record_path or provider_qualification.record_path_for(config, env)
    if not path.exists():
        return fail(
            CHECK_ID_PROVIDER,
            f"no qualification record for {env} "
            f"(run local/scripts/qualify-storage-provider.sh {env})",
        )
    return provider_qualification.verify(
        env, path, store=store, max_age_days=config.qualification_max_age_days
    )


CHECK_ID_PROVIDER = provider_qualification.CHECK_ID


# -- activation ------------------------------------------------------------------------


def check_activation(
    env: str, config: PromotionConfig, store: SecretStore, deploy: DeployTarget
) -> list[Check]:
    if config.activation is None:
        # Not applicable only when the product really has no data import. A declaration or the
        # engine package on disk with no `activation` section in promotion.yaml would otherwise
        # let the gate skip the activation checks silently: that is a FAIL.
        present = [
            p
            for p in ("local/config/import-activation.yaml", "python-packages/koras-import")
            if (config.root / p).exists()
        ]
        if present:
            return [
                fail(
                    "activation_policy",
                    "this checkout has data import (" + ", ".join(present) + ") but "
                    "promotion.yaml declares no `activation` section",
                )
            ]
        return [
            ok(
                "activation_not_applicable",
                "this product was generated without data import: there is no activation to check",
            )
        ]
    try:
        policy = activation.load_policy(config.activation.declaration)
        checks = activation.collect_checks(env, config, policy, store, deploy)
    except activation.ActivationError as exc:
        return [fail("activation_policy", str(exc))]
    consistent = all(c.passed for c in checks)
    if not policy[env]:
        off = (
            ok(
                "imports_off",
                f"{env}: declared disabled; no {activation.SETTING} in the secret store or on "
                "the apps",
            )
            if consistent
            else fail(
                "imports_off",
                f"{env}: imports are not demonstrably OFF, i.e. {activation.SETTING} is not "
                "absent everywhere (see activation checks)",
            )
        )
    else:
        off = (
            ok("imports_off", f"{env}: declared enabled; configuration canonical")
            if consistent
            else fail(
                "imports_off",
                f"{env}: activation configuration is not canonical (see activation checks)",
            )
        )
    return [*checks, off]


# -- the gate --------------------------------------------------------------------------


def _guarded(check_id: str, collector: Callable[[], Check | list[Check]]) -> list[Check]:
    """Run one collector; an unexpected exception is a FAIL naming only the exception class."""
    try:
        result = collector()
    except Exception as exc:  # noqa: BLE001 - every collector failure is a FAIL, never a crash
        return [fail(check_id, f"the collector raised {type(exc).__name__}")]
    return result if isinstance(result, list) else [result]


def evaluate(
    env: str,
    *,
    config: PromotionConfig | None = None,
    commit: str | None = None,
    qualification: Path | None = None,
    runner: Runner = _run,
    config_path: Path | str | None = None,
) -> list[Check]:
    if env not in ENVIRONMENTS:
        return [fail("environment", f"unknown environment {env!r}")]
    if config is None:
        try:
            config = load_config(config_path)
        except ConfigError as exc:
            return [fail("promotion_config", str(exc))]
    try:
        store, deploy = build_adapters(config, runner)
    except AdapterError as exc:
        return [fail("promotion_config", str(exc))]
    cfg = config
    checks: list[Check] = [ok("promotion_config", "local/config/promotion.yaml is valid")]
    checks += _guarded("activation_policy", lambda: check_activation(env, cfg, store, deploy))
    checks += _guarded("scanner_configured", lambda: check_scanner(env, cfg, store, deploy))
    checks += _guarded("immutable_finalization", check_finalization)
    checks += _guarded(
        "provider_qualification", lambda: check_provider(env, cfg, store, qualification)
    )
    checks += _guarded(f1.CHECK_ID, lambda: f1.check_for_environment(env, cfg, store))
    checks += _guarded("ci_suites", lambda: check_ci(commit, cfg, runner))
    if cfg.activation is not None:
        checks += _guarded("import_gate_installed", check_import_gate_installed)
    checks += _guarded("security_findings", lambda: check_findings(cfg))
    return checks


def record(env: str, checks: list[Check], now: datetime | None = None) -> dict[str, Any]:
    status = overall(checks)
    f1_check = next((c for c in checks if c.id == f1.CHECK_ID), None)
    return {
        "schema": "koras.promotion-gate/1",
        "environment": env,
        "evaluated_at": (now or datetime.now(UTC)).isoformat(),
        "result": status,
        "F1_UNVERIFIED_RELEASABLE_COUNT": (
            f1_check.data.get("F1_UNVERIFIED_RELEASABLE_COUNT") if f1_check else None
        ),
        "checks": [
            {"id": c.id, "status": c.status, "detail": c.detail, "data": c.data} for c in checks
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="promotion gate", description="Read-only promotion gate.")
    parser.add_argument("--env", required=True, choices=ENVIRONMENTS)
    parser.add_argument("--config", default=None)
    parser.add_argument("--commit", default=None, help="full sha to read CI for (default: HEAD)")
    parser.add_argument("--qualification", type=Path, default=None)
    parser.add_argument(
        "--out", type=Path, default=None, help="also write the evidence record here"
    )
    args = parser.parse_args(argv)
    if args.out:
        # A stale PASS must never survive a run that does not finish: remove it, then leave a FAIL
        # placeholder until the real record replaces it.
        args.out.unlink(missing_ok=True)
        placeholder = record(args.env, [fail("gate_incomplete", "the gate did not finish")])
        args.out.write_text(json.dumps(placeholder, indent=2, default=str), encoding="utf-8")
    checks = evaluate(
        args.env, commit=args.commit, qualification=args.qualification, config_path=args.config
    )
    rec = record(args.env, checks)
    for c in checks:
        print(f"{c.status} {c.id}: {c.detail}")  # noqa: T201
    print(f"{args.env.upper()}_PROMOTION_GATE = {rec['result']}")  # noqa: T201
    if args.out:
        args.out.write_text(json.dumps(rec, indent=2, default=str), encoding="utf-8")
    return 0 if rec["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
