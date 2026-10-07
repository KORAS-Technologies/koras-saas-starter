"""Import activation is explicit per environment, and the deploy proves it (ADR 0013 section 7).

`local/config/import-activation.yaml` declares, for each environment, whether data import is meant
to be on. This module compares that declaration with what the environment will actually run:

- The secret store is the authority for the value (the deploy imports its config into the app), so
  its value must parse to exactly the declared answer.
- An app holding an `IMPORTS_ENABLED` secret that the store does not hold is DRIFT (it was set by
  hand, survives every deploy, and the store is then not the authority). Names only.
- A DISABLED environment holds NO `IMPORTS_ENABLED` at all: not in the store (not even `false`) and
  not on the api or worker app. Absent == off is the single declaration of "off", so there is one
  spelling to audit and no "set to false" state to drift from.
- The API and the worker must agree.
- The declaration alone can never activate an environment: `enabled` is honoured only for
  `activation.activatable_environments` in `local/config/promotion.yaml`, a second, separate edit.
  The Starter ships that list empty.

Everything is read-only. No value is ever printed or put in a `Check`; only names, booleans and a
digest comparison result. Unknown (CLI missing, app unreachable, store error) is FAIL, never a
pass. An app that exists but holds no `IMPORTS_ENABLED` is not an error: it holds none, which is
the required answer for a disabled environment and drift-free for an enabled one that the store
holds (the deploy imports it). An app that does not exist is FAIL: nothing can be said about it.

    python -m promotion.activation <env> [--skip-fly] [--config PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

import yaml

from .adapters import (
    AdapterError,
    DeployTarget,
    Runner,
    SecretState,
    SecretStore,
    build_adapters,
    default_runner,
)
from .config import ConfigError, PromotionConfig, load_config
from .result import ENVIRONMENTS, Check, fail, ok, overall

SETTING = "IMPORTS_ENABLED"

_ENABLED = "enabled"
_DISABLED = "disabled"


class ActivationError(Exception):
    """A declaration or a read that cannot be trusted. The message is safe to print."""


def effective(raw: str | None) -> bool:
    """What the API and worker would resolve from this stored value (absent => off).

    The API's and the worker's own parser, so there is one spelling list.
    """
    try:
        from koras_import import parse_import_activation  # noqa: PLC0415
    except ImportError as exc:
        raise ActivationError(
            "the import activation parser (koras_import) is not installed"
        ) from exc
    return parse_import_activation(raw)


# -- the declaration ------------------------------------------------------------------


def load_policy(path: Path | str) -> dict[str, bool]:
    """env -> activated. Raises `ActivationError` for anything but a complete, exact declaration."""
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ActivationError("activation declaration file is missing") from exc
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ActivationError("activation declaration file cannot be parsed") from exc
    if not isinstance(raw, dict) or set(raw) != {"environments"}:
        raise ActivationError("activation declaration must contain exactly one key: environments")
    envs = raw["environments"]
    if not isinstance(envs, dict):
        raise ActivationError("activation declaration 'environments' must be a mapping")
    unknown = sorted(str(k) for k in set(envs) - set(ENVIRONMENTS))
    if unknown:
        raise ActivationError(
            f"activation declaration names unknown environment(s): {', '.join(unknown)}"
        )
    missing = [e for e in ENVIRONMENTS if e not in envs]
    if missing:
        raise ActivationError(
            f"activation declaration is missing environment(s): {', '.join(missing)}"
        )
    policy: dict[str, bool] = {}
    for env in ENVIRONMENTS:
        entry = envs[env]
        if not isinstance(entry, dict) or set(entry) != {"import_activation"}:
            raise ActivationError(f"{env}: must contain exactly one key: import_activation")
        value = entry["import_activation"]
        if not isinstance(value, str) or value not in (_ENABLED, _DISABLED):
            raise ActivationError(f"{env}: import_activation must be exactly enabled or disabled")
        policy[env] = value == _ENABLED
    return policy


# -- the checks -----------------------------------------------------------------------


def check_policy_allowed(policy: Mapping[str, bool], activatable: Collection[str]) -> Check:
    over = sorted(e for e, on in policy.items() if on and e not in activatable)
    if over:
        return fail(
            "activation_policy_allowed",
            "declared enabled outside activation.activatable_environments: " + ", ".join(over),
            environments=over,
        )
    return ok(
        "activation_policy_allowed",
        "no environment is enabled beyond activation.activatable_environments",
    )


def check_activation_config(  # noqa: PLR0913
    env: str,
    policy: Mapping[str, bool],
    activatable: Collection[str],
    store_value: str | None,
    api: SecretState | None,
    worker: SecretState | None,
    *,
    include_deploy: bool = True,
) -> list[Check]:
    """`api` / `worker` None means the app could not be read: that is a FAIL, not a pass."""
    if env not in ENVIRONMENTS or env not in policy:
        return [fail("activation_policy", f"{env}: not a declared environment")]
    want = policy[env]
    got = effective(store_value)
    present = store_value is not None
    checks = [check_policy_allowed(policy, activatable)]

    if not want:
        # A disabled environment holds NO setting at all; "false" is not the declaration of off.
        if present:
            checks.append(
                fail(
                    "activation_secret_store",
                    f"{env}: declared disabled but the secret store holds {SETTING}; a disabled "
                    "environment holds none (absent is the one way to say off)",
                    declared=want,
                    effective=got,
                    store_holds=True,
                )
            )
        else:
            checks.append(
                ok(
                    "activation_secret_store",
                    f"{env}: the secret store holds no {SETTING}, as a disabled environment must",
                    declared=want,
                    effective=got,
                )
            )
    elif got == want:
        checks.append(
            ok(
                "activation_secret_store",
                f"{env}: the secret store resolves to enabled, as declared",
                declared=want,
                effective=got,
            )
        )
    else:
        checks.append(
            fail(
                "activation_secret_store",
                f"{env}: declared enabled but the secret store resolves to disabled "
                f"({SETTING} {'set' if present else 'not set'} in the secret store)",
                declared=want,
                effective=got,
                store_holds=present,
            )
        )
    if not include_deploy:
        return checks

    apps = {"api": api, "worker": worker}
    for label, state in apps.items():
        if state is None:
            checks.append(fail(f"activation_app_{label}", f"{env}: {label} app could not be read"))
        elif SETTING in state.names and not want:
            checks.append(
                fail(
                    f"activation_app_{label}",
                    f"{env}: {label} app holds {SETTING} but the environment is declared "
                    "disabled; it must hold none (unset it on the app)",
                    drift=True,
                )
            )
        elif SETTING in state.names and not present:
            checks.append(
                fail(
                    f"activation_app_{label}",
                    f"{env}: DRIFT - {label} app holds {SETTING} but the secret store does not",
                    drift=True,
                )
            )
        else:
            checks.append(
                ok(f"activation_app_{label}", f"{env}: {label} app has no unmanaged {SETTING}")
            )

    if api is not None and worker is not None:
        api_has, worker_has = SETTING in api.names, SETTING in worker.names
        api_digest = api.digests.get(SETTING)
        worker_digest = worker.digests.get(SETTING)
        if api_has != worker_has:
            checks.append(
                fail(
                    "activation_api_worker_agree",
                    f"{env}: {SETTING} is held by {'api' if api_has else 'worker'} only",
                )
            )
        elif api_has and (api_digest is None or api_digest != worker_digest):
            checks.append(
                fail(
                    "activation_api_worker_agree",
                    f"{env}: api and worker hold different {SETTING} values",
                )
            )
        else:
            checks.append(ok("activation_api_worker_agree", f"{env}: api and worker agree"))
    else:
        checks.append(
            fail("activation_api_worker_agree", f"{env}: cannot compare, an app was unreadable")
        )
    return checks


# -- read-only collectors -------------------------------------------------------------


def collect_checks(
    env: str,
    config: PromotionConfig,
    policy: Mapping[str, bool],
    store: SecretStore,
    deploy: DeployTarget,
    *,
    include_deploy: bool = True,
) -> list[Check]:
    assert config.activation is not None  # noqa: S101 - the caller checked; a bug, not input
    try:
        value = store.get(env, SETTING)
    except AdapterError as exc:
        return [fail("activation_secret_store", f"{env}: {exc}")]
    api: SecretState | None = None
    worker: SecretState | None = None
    errors: list[Check] = []
    if include_deploy:
        apps = config.environments[env].apps
        for label in ("api", "worker"):
            try:
                state = deploy.secrets(apps[label])
            except AdapterError as exc:
                errors.append(fail(f"activation_app_{label}_read", str(exc)))
                continue
            if label == "api":
                api = state
            else:
                worker = state
    checks = check_activation_config(
        env,
        policy,
        config.activation.activatable_environments,
        value,
        api,
        worker,
        include_deploy=include_deploy,
    )
    return checks + errors


def evaluate(
    env: str,
    config: PromotionConfig,
    store: SecretStore,
    deploy: DeployTarget,
    *,
    include_deploy: bool = True,
) -> list[Check]:
    """Every activation check for `env`, or one FAIL naming why none could be made."""
    if config.activation is None:
        return [fail("activation_policy", "this product's promotion.yaml declares no activation")]
    try:
        policy = load_policy(config.activation.declaration)
        return collect_checks(env, config, policy, store, deploy, include_deploy=include_deploy)
    except ActivationError as exc:
        return [fail("activation_policy", str(exc))]


def cli(argv: Sequence[str] | None = None, *, runner: Runner = default_runner) -> int:
    parser = argparse.ArgumentParser(prog="promotion.activation")
    parser.add_argument("environment", choices=ENVIRONMENTS)
    parser.add_argument("--config", default=None)
    parser.add_argument(
        "--skip-fly",
        "--skip-deploy",
        dest="skip_deploy",
        action="store_true",
        help="declaration and secret store only (a pre-deploy job has no access to the host)",
    )
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        store, deploy = build_adapters(config, runner)
        checks = evaluate(
            args.environment, config, store, deploy, include_deploy=not args.skip_deploy
        )
    except (ConfigError, AdapterError) as exc:
        checks = [fail("activation_policy", str(exc))]
    status = overall(checks)
    print(  # noqa: T201
        json.dumps(
            {
                "environment": args.environment,
                "status": status,
                "checks": [
                    {"id": c.id, "status": c.status, "detail": c.detail, "data": c.data}
                    for c in checks
                ],
            },
            indent=2,
        )
    )
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(cli())
