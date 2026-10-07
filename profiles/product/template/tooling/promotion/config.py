"""`local/config/promotion.yaml`: everything the promotion tooling needs that is the product's.

The tooling is generic; the product is not. Which secret-store project holds an environment's
settings, what its deployed apps are called, which CI jobs a commit needs, where the security
register lives and which environments may ever be activated are all *configuration*, declared in
one reviewed file and validated strictly here. Nothing in `tooling/promotion` names a product, an
app or a secret-store project.

Strict on purpose: an unknown key, a missing key, a wrong type, a path that leaves the repository
and a pattern that does not compile are all `ConfigError`, which the gate turns into a FAIL. There
is no default that quietly stands in for a missing declaration.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .result import ENVIRONMENTS

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "local" / "config" / "promotion.yaml"

#: Names that reach a command line are checked against these first, so a value read from the file
#: can never be an option (`--app`, `-X`) or carry a space, a quote or a path separator.
APP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")
SETTING_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_JOB_NAME = re.compile(r"[^\x00-\x1f\x7f]{1,100}")
SUPPORTED_SECRET_STORES = ("doppler",)
SUPPORTED_DEPLOY_TARGETS = ("fly",)
SUPPORTED_CI = ("github",)
APPS = ("api", "worker", "clamd")


class ConfigError(Exception):
    """The configuration cannot be trusted. The message is safe to print."""


@dataclass(frozen=True, slots=True)
class EnvironmentConfig:
    name: str
    secret_store_config: str
    apps: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ActivationConfig:
    """Present only in a product generated with `data_import`."""

    declaration: Path
    #: The ONLY environments whose declaration may say `enabled`. A second, separate edit from the
    #: declaration itself: editing the declaration alone can never activate an environment.
    activatable_environments: frozenset[str]


@dataclass(frozen=True, slots=True)
class PromotionConfig:
    root: Path
    secret_store_provider: str
    secret_store_project: str
    deploy_provider: str
    environments: Mapping[str, EnvironmentConfig]
    scanner_backend_setting: str
    scanner_required_backend: str
    database_admin_url_setting: str
    ci_provider: str
    ci_required_jobs: tuple[str, ...]
    register_path: Path
    register_id_pattern: str
    register_chain_ids: frozenset[str]
    f1_dispositions: Path
    qualification_dir: Path
    qualification_max_age_days: int
    activation: ActivationConfig | None

    def secret_store_config(self, env: str) -> str:
        return self.environments[env].secret_store_config


def _mapping(
    value: object, where: str, required: tuple[str, ...], optional: tuple[str, ...] = ()
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a mapping")
    keys = {str(k) for k in value}
    missing = [k for k in required if k not in keys]
    if missing:
        raise ConfigError(f"{where} is missing: {', '.join(missing)}")
    extra = sorted(keys - set(required) - set(optional))
    if extra:
        raise ConfigError(f"{where} has unknown key(s): {', '.join(extra)}")
    return value


def _text(value: object, where: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ConfigError(f"{where} is not a valid name")
    return value


def _choice(value: object, where: str, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ConfigError(f"{where} must be one of: {', '.join(allowed)}")
    return value


def _path(root: Path, value: object, where: str) -> Path:
    """A repository-relative path that stays inside the repository."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ConfigError(f"{where} must be a repository-relative path")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ConfigError(f"{where} must be a repository-relative path inside the repository")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ConfigError(f"{where} leaves the repository")
    return root / candidate


def _environments(raw: object) -> dict[str, EnvironmentConfig]:
    envs = _mapping(raw, "environments", ENVIRONMENTS)
    out: dict[str, EnvironmentConfig] = {}
    for name in ENVIRONMENTS:
        entry = _mapping(envs[name], f"environments.{name}", ("secret_store_config", "apps"))
        apps = _mapping(entry["apps"], f"environments.{name}.apps", APPS)
        out[name] = EnvironmentConfig(
            name=name,
            secret_store_config=_text(
                entry["secret_store_config"], f"environments.{name}.secret_store_config", APP_NAME
            ),
            apps={
                app: _text(apps[app], f"environments.{name}.apps.{app}", APP_NAME) for app in APPS
            },
        )
    return out


def parse_config(raw: object, root: Path = REPO_ROOT) -> PromotionConfig:
    top = _mapping(
        raw,
        "promotion.yaml",
        (
            "version",
            "secret_store",
            "deploy",
            "environments",
            "scanner",
            "database",
            "ci",
            "register",
            "f1",
            "qualification",
        ),
        ("activation",),
    )
    if top["version"] != 1 or isinstance(top["version"], bool):
        raise ConfigError("promotion.yaml: version must be 1")
    store = _mapping(top["secret_store"], "secret_store", ("provider", "project"))
    deploy = _mapping(top["deploy"], "deploy", ("provider",))
    scanner = _mapping(top["scanner"], "scanner", ("backend_setting", "required_backend"))
    database = _mapping(top["database"], "database", ("admin_url_setting",))
    ci = _mapping(top["ci"], "ci", ("provider", "required_jobs"))
    register = _mapping(top["register"], "register", ("path", "id_pattern"), ("chain_ids",))
    f1 = _mapping(top["f1"], "f1", ("dispositions",))
    qualification = _mapping(top["qualification"], "qualification", ("directory", "max_age_days"))

    jobs = ci["required_jobs"]
    if not isinstance(jobs, list) or not jobs:
        raise ConfigError("ci.required_jobs must be a non-empty list")
    required_jobs = tuple(_text(j, "ci.required_jobs entry", _JOB_NAME) for j in jobs)
    if len(set(required_jobs)) != len(required_jobs):
        raise ConfigError("ci.required_jobs names a job twice")

    pattern = register["id_pattern"]
    if not isinstance(pattern, str) or not pattern:
        raise ConfigError("register.id_pattern must be a regular expression")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ConfigError("register.id_pattern does not compile") from exc
    chain = register.get("chain_ids", [])
    if not isinstance(chain, list) or not all(isinstance(c, str) and c for c in chain):
        raise ConfigError("register.chain_ids must be a list of ids")

    age = qualification["max_age_days"]
    if isinstance(age, bool) or not isinstance(age, int) or not 1 <= age <= 90:
        raise ConfigError("qualification.max_age_days must be a whole number from 1 to 90")

    activation: ActivationConfig | None = None
    if "activation" in top:
        act = _mapping(top["activation"], "activation", ("declaration", "activatable_environments"))
        listed = act["activatable_environments"]
        if not isinstance(listed, list) or any(e not in ENVIRONMENTS for e in listed):
            raise ConfigError(
                f"activation.activatable_environments must be a list of: {', '.join(ENVIRONMENTS)}"
            )
        activation = ActivationConfig(
            declaration=_path(root, act["declaration"], "activation.declaration"),
            activatable_environments=frozenset(listed),
        )

    return PromotionConfig(
        root=root,
        secret_store_provider=_choice(
            store["provider"], "secret_store.provider", SUPPORTED_SECRET_STORES
        ),
        secret_store_project=_text(store["project"], "secret_store.project", APP_NAME),
        deploy_provider=_choice(deploy["provider"], "deploy.provider", SUPPORTED_DEPLOY_TARGETS),
        environments=_environments(top["environments"]),
        scanner_backend_setting=_text(
            scanner["backend_setting"], "scanner.backend_setting", SETTING_NAME
        ),
        scanner_required_backend=_text(
            scanner["required_backend"], "scanner.required_backend", APP_NAME
        ),
        database_admin_url_setting=_text(
            database["admin_url_setting"], "database.admin_url_setting", SETTING_NAME
        ),
        ci_provider=_choice(ci["provider"], "ci.provider", SUPPORTED_CI),
        ci_required_jobs=required_jobs,
        register_path=_path(root, register["path"], "register.path"),
        register_id_pattern=pattern,
        register_chain_ids=frozenset(chain),
        f1_dispositions=_path(root, f1["dispositions"], "f1.dispositions"),
        qualification_dir=_path(root, qualification["directory"], "qualification.directory"),
        qualification_max_age_days=age,
        activation=activation,
    )


def load_config(path: Path | str | None = None, root: Path = REPO_ROOT) -> PromotionConfig:
    """Read and validate the file. Raises `ConfigError` for anything but a complete declaration."""
    target = Path(path) if path is not None else root / "local" / "config" / "promotion.yaml"
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError("the promotion configuration file is missing") from exc
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ConfigError("the promotion configuration file cannot be parsed") from exc
    return parse_config(raw, root)
