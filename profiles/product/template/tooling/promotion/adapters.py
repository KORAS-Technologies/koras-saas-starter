"""The boundary between the generic promotion engine and a product's deployment.

Everything the engine needs from the outside world is one of three reads:

* a **setting's value** in an environment's secret store (`SecretStore.get`),
* the **secret names** (never values) an app holds, and its **machines** (`DeployTarget`),
* the **check runs** of a commit (`gh api`, in `gate.py`).

The engine never calls a vendor CLI itself. It asks an adapter, and the adapters here are the
two the Starter uses product-wide: Doppler for the secret store and Fly for the deployment. A
product on another store or host adds an adapter class and a name to `SECRET_STORES` /
`DEPLOY_TARGETS` (and to `config.SUPPORTED_*`); nothing in `activation.py`, `f1.py`,
`provider_qualification.py` or `gate.py` changes. The boundary is documented in
`docs/SECURE_FILES.md`, "Promotion tooling".

**Read-only by construction.** Each adapter issues a fixed argument list (no shell), built from
names that were validated against a strict pattern first, so a value taken from the configuration
can never become an option. Every command is one of: `doppler secrets get`, `flyctl secrets list`,
`flyctl machines list`. A test pins that allowlist and drives the whole gate through a recorder.

**Nothing secret is returned or logged except through `SecretStore.get`**, whose callers decide
what to do with a value. Fly never returns a secret's value at all; `SecretState` carries names and
the digest Fly reports.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # noqa: S404 - read-only secret-store and deploy calls, argument lists, no shell
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .config import APP_NAME, SETTING_NAME, PromotionConfig

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]

#: What `doppler secrets get` says on stderr when the secret does not exist. The one spelling.
DOPPLER_ABSENT_MARKER = "could not find requested secret"


class AdapterError(Exception):
    """A read that could not be completed. The message is safe to print (no value, no secret)."""


def default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    exe = shutil.which(argv[0]) or argv[0]  # a Windows .cmd shim is not found by name alone
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [exe, *argv[1:]], capture_output=True, text=True, timeout=60, check=False
    )


def _checked(name: str, pattern_name: str, what: str) -> str:
    pattern = APP_NAME if pattern_name == "app" else SETTING_NAME
    if not isinstance(name, str) or not pattern.fullmatch(name):
        raise AdapterError(f"{what} is not a valid name")
    return name


@dataclass(frozen=True, slots=True)
class SecretState:
    """What a deployed app holds: names, and the digest it reports for each (never a value)."""

    names: frozenset[str]
    digests: Mapping[str, str | None]


class SecretStore(Protocol):
    """An environment's secret store: the authority for a setting's value."""

    def get(self, env: str, setting: str) -> str | None:
        """The raw value, or None when the setting is ABSENT; anything else raises AdapterError."""
        ...

    def bound_environment(self, environ: Mapping[str, str]) -> str | None:
        """The environment this process is bound to by the store's own runner, or None."""
        ...


class DeployTarget(Protocol):
    """Where the services run: their secret names and their machines."""

    def secrets(self, app: str) -> SecretState: ...

    def machines(self, app: str) -> list[Mapping[str, Any]]: ...


# -- Doppler ----------------------------------------------------------------------------------


class DopplerStore:
    def __init__(
        self,
        project: str,
        configs: Mapping[str, str],
        runner: Runner = default_runner,
    ) -> None:
        self.project = _checked(project, "app", "the secret-store project")
        self._configs = dict(configs)
        self._run = runner

    def _config(self, env: str) -> str:
        if env not in self._configs:
            raise AdapterError(f"{env}: not a configured environment")
        return _checked(self._configs[env], "app", "the secret-store config")

    def get(self, env: str, setting: str) -> str | None:
        name = _checked(setting, "setting", "the setting")
        argv = [
            "doppler",
            "secrets",
            "get",
            name,
            "--plain",
            "--project",
            self.project,
            "--config",
            self._config(env),
        ]
        try:
            proc = self._run(argv)
        except (OSError, subprocess.SubprocessError) as exc:
            raise AdapterError("doppler could not be run") from exc
        if proc.returncode == 0:
            return proc.stdout.replace("\r", "").replace("\n", "")
        if DOPPLER_ABSENT_MARKER in (proc.stderr or "").lower():
            return None
        raise AdapterError("doppler could not read the setting")

    def bound_environment(self, environ: Mapping[str, str]) -> str | None:
        """`doppler run --project P --config C` sets DOPPLER_PROJECT and DOPPLER_CONFIG."""
        project = environ.get("DOPPLER_PROJECT")
        if project is not None and project != self.project:
            return None
        bound = environ.get("DOPPLER_CONFIG")
        for env, config in self._configs.items():
            if bound is not None and bound == config:
                return env
        return None


# -- Fly --------------------------------------------------------------------------------------


class FlyTarget:
    def __init__(self, runner: Runner = default_runner) -> None:
        self._run = runner

    def _json(self, argv: list[str], label: str, app: str) -> Any:  # noqa: ANN401
        try:
            proc = self._run(argv)
        except (OSError, subprocess.SubprocessError) as exc:
            raise AdapterError(f"{app}: flyctl could not be run") from exc
        if proc.returncode != 0:
            raise AdapterError(f"{app}: {label} could not be listed (app missing or unreachable)")
        try:
            return json.loads(proc.stdout or "null")
        except ValueError as exc:
            raise AdapterError(f"{app}: {label} listing was not JSON") from exc

    def secrets(self, app: str) -> SecretState:
        name = _checked(app, "app", "the app")
        rows = self._json(["flyctl", "secrets", "list", "--app", name, "--json"], "secrets", name)
        if not isinstance(rows, list):
            raise AdapterError(f"{name}: secrets listing had an unexpected shape")
        names: set[str] = set()
        digests: dict[str, str | None] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            secret = row.get("name") or row.get("Name")
            if not isinstance(secret, str):
                continue
            names.add(secret)
            digest = row.get("digest") or row.get("Digest")
            digests[secret] = digest if isinstance(digest, str) else None
        return SecretState(frozenset(names), digests)

    def machines(self, app: str) -> list[Mapping[str, Any]]:
        name = _checked(app, "app", "the app")
        rows = self._json(["flyctl", "machines", "list", "--app", name, "--json"], "machines", name)
        if not isinstance(rows, list):
            raise AdapterError(f"{name}: machines listing had an unexpected shape")
        return [r for r in rows if isinstance(r, dict)]


# -- the registries a product extends ---------------------------------------------------------

SECRET_STORES: dict[str, Callable[[PromotionConfig, Runner], SecretStore]] = {
    "doppler": lambda config, runner: DopplerStore(
        config.secret_store_project,
        {name: env.secret_store_config for name, env in config.environments.items()},
        runner,
    ),
}
DEPLOY_TARGETS: dict[str, Callable[[PromotionConfig, Runner], DeployTarget]] = {
    "fly": lambda config, runner: FlyTarget(runner),
}


def build_adapters(
    config: PromotionConfig, runner: Runner = default_runner
) -> tuple[SecretStore, DeployTarget]:
    try:
        store = SECRET_STORES[config.secret_store_provider](config, runner)
        target = DEPLOY_TARGETS[config.deploy_provider](config, runner)
    except KeyError as exc:
        raise AdapterError("the configured provider has no adapter") from exc
    return store, target
