# ruff: noqa: ANN401
"""Shared fixtures for the promotion tooling's unit suites: a valid configuration, a fake runner.

The fake runner stands in for every external command the tooling may issue (the secret store, the
deploy host, GitHub, git) and RECORDS each argv, so a suite can assert both the answer and that no
command outside the read-only allowlist was ever issued.
"""

from __future__ import annotations

import copy
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from promotion.config import PromotionConfig, parse_config

ENVIRONMENTS = ("dev", "test", "stg", "prod")
PROJECT = "shop"
SHA = "a" * 40


def proc(out: str = "", code: int = 0, err: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, out, err)


def raw_config(*, activation: bool = False) -> dict[str, Any]:
    """A complete, valid `promotion.yaml` as a mapping (what `yaml.safe_load` would return)."""
    raw: dict[str, Any] = {
        "version": 1,
        "secret_store": {"provider": "doppler", "project": PROJECT},
        "deploy": {"provider": "fly"},
        "environments": {
            env: {
                "secret_store_config": env,
                "apps": {
                    "api": f"{PROJECT}-api-{env}",
                    "worker": f"{PROJECT}-worker-{env}",
                    "clamd": f"{PROJECT}-clamd-{env}",
                },
            }
            for env in ENVIRONMENTS
        },
        "scanner": {"backend_setting": "FILE_SCAN_BACKEND", "required_backend": "clamd"},
        "database": {"admin_url_setting": "DATABASE_ADMIN_URL"},
        "ci": {"provider": "github", "required_jobs": ["Lint", "Test", "Build"]},
        "register": {
            "path": "docs/security/REGISTER.md",
            "id_pattern": "[A-Z]+-[0-9]+",
            "chain_ids": ["SEC-1"],
        },
        "f1": {"dispositions": "local/config/f1-dispositions.yaml"},
        "qualification": {"directory": "local/.qualification", "max_age_days": 14},
    }
    if activation:
        raw["activation"] = {
            "declaration": "local/config/import-activation.yaml",
            "activatable_environments": ["dev"],
        }
    return raw


def make_config(root: Path, *, activation: bool = False, edit: Any = None) -> PromotionConfig:
    """`edit(raw)` may mutate the mapping before it is parsed."""
    raw = copy.deepcopy(raw_config(activation=activation))
    if edit is not None:
        edit(raw)
    return parse_config(raw, root)


ABSENT = None  # a setting the secret store does not hold
ERROR = object()  # a read that fails for any reason other than absence


class FakeRunner:
    """Answers `doppler`, `flyctl`, `gh` and `git` plausibly and records every argv."""

    def __init__(
        self,
        *,
        store: Mapping[tuple[str, str], Any] | None = None,
        secrets: Mapping[str, Any] | None = None,
        machines: Mapping[str, Any] | None = None,
        ci: Sequence[tuple[str, ...]] | None = None,
        sha: str = SHA,
    ) -> None:
        self.store = dict(store or {})
        self.secrets = dict(secrets or {})
        self.machines = dict(machines or {})
        self.ci = list(ci or [])
        self.sha = sha
        self.calls: list[list[str]] = []

    @staticmethod
    def _option(argv: Sequence[str], name: str) -> str:
        return argv[list(argv).index(name) + 1]

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        argv = list(argv)
        self.calls.append(argv)
        head = argv[0]
        if head == "doppler" and argv[1:3] == ["secrets", "get"]:
            key = (self._option(argv, "--config"), argv[3])
            value = self.store.get(key, ABSENT)
            if value is ERROR:
                return proc("", 1, "Doppler Error: boom")
            if value is ABSENT:
                return proc("", 1, "Doppler Error: Could not find requested secret 'X'")
            return proc(f"{value}\n")
        if head == "flyctl" and argv[1:3] == ["secrets", "list"]:
            rows = self.secrets.get(self._option(argv, "--app"))
            if rows is None:
                return proc("", 1, "app not found")
            return proc(json.dumps(rows))
        if head == "flyctl" and argv[1:3] == ["machines", "list"]:
            rows = self.machines.get(self._option(argv, "--app"))
            if rows is None:
                return proc("", 1, "app not found")
            return proc(json.dumps(rows))
        if head == "gh":
            return proc("\n".join("\t".join(r) for r in self.ci))
        if head == "git":
            return proc(self.sha)
        return proc("", 1, "unexpected command")

    def violations(self) -> list[list[str]]:
        return [c for c in self.calls if not is_read_only(c)]


_WRITE_FLAGS = {"-X", "--method", "-f", "-F", "--field", "--raw-field", "--input"}


def is_read_only(argv: Sequence[str]) -> bool:
    """The allowlist: the only external commands the promotion tooling may ever issue."""
    a = list(argv)
    if a[:3] == ["doppler", "secrets", "get"]:
        return True
    if a[:3] in (["flyctl", "secrets", "list"], ["flyctl", "machines", "list"]):
        return True
    if a[:2] == ["gh", "api"]:
        return not any(t in _WRITE_FLAGS or t.startswith(("--method=", "-X")) for t in a[2:])
    if a[:1] == ["git"]:
        return "rev-parse" in a[1:4] and not any(t.startswith("--") and t != "--" for t in a[1:])
    return False


def green_ci(jobs: Sequence[str], app: str = "github-actions") -> list[tuple[str, ...]]:
    return [(j, "completed", "success", "2026-10-06T10:00:00Z", app) for j in jobs]
