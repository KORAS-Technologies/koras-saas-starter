# ruff: noqa: ANN001, ANN003, ANN202, ANN201, ANN401, E501
"""Import activation, checked against its declaration: absent means off, drift fails, and the
declaration alone can never activate an environment (ADR 0013 section 7).

Generated only for a product with `secure_files` AND `data_import`: it needs the shared parse rule.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from koras_import import IMPORTS_ENABLED_SETTING, parse_import_activation
from promotion import activation, gate
from promotion.activation import SETTING, check_activation_config, load_policy
from promotion.adapters import SecretState, build_adapters
from promotion.config import PromotionConfig
from promotion.result import overall
from promotion_support import ERROR, FakeRunner, make_config

ENVS = ("dev", "test", "stg", "prod")
OFF = {e: False for e in ENVS}
DEV_ON = {**OFF, "dev": True}


def state(*names: str, digest: str | None = "d1") -> SecretState:
    return SecretState(frozenset(names), {SETTING: digest} if SETTING in names else {})


NONE_HELD = state("OTHER")
HOLDS = state(SETTING, "OTHER")


def run(env: str, policy: dict[str, bool], value: str | None, api, worker, **kw: Any):
    activatable = kw.pop("activatable", {"dev"})
    return check_activation_config(env, policy, activatable, value, api, worker, **kw)


def failed(checks) -> set[str]:
    return {c.id for c in checks if not c.passed}


def test_the_setting_is_the_one_the_runtime_reads() -> None:
    assert SETTING == IMPORTS_ENABLED_SETTING


# -- the decision table ------------------------------------------------------------------------
#
# (env, declaration, secret-store value, api app, worker app, activatable) -> the checks that fail
# `None` for a value is ABSENT. `None` for an app is "could not be read".

TABLE = [
    # a disabled environment holds NOTHING anywhere: absent means off
    ("test", OFF, None, NONE_HELD, NONE_HELD, {"dev"}, set()),
    ("prod", OFF, None, NONE_HELD, NONE_HELD, set(), set()),
    # ... and `false` is not the way to say off
    ("test", OFF, "false", NONE_HELD, NONE_HELD, {"dev"}, {"activation_secret_store"}),
    ("test", OFF, "", NONE_HELD, NONE_HELD, {"dev"}, {"activation_secret_store"}),
    ("test", OFF, "true", NONE_HELD, NONE_HELD, {"dev"}, {"activation_secret_store"}),
    # drift: the app holds it, the store does not (or the environment is disabled)
    (
        "test",
        OFF,
        None,
        HOLDS,
        NONE_HELD,
        {"dev"},
        {"activation_app_api", "activation_api_worker_agree"},
    ),
    (
        "test",
        OFF,
        None,
        NONE_HELD,
        HOLDS,
        {"dev"},
        {"activation_app_worker", "activation_api_worker_agree"},
    ),
    ("test", OFF, None, HOLDS, HOLDS, {"dev"}, {"activation_app_api", "activation_app_worker"}),
    # an enabled, activatable environment: the store resolves to on, the apps hold nothing of their own
    ("dev", DEV_ON, "true", NONE_HELD, NONE_HELD, {"dev"}, set()),
    ("dev", DEV_ON, " YES ", NONE_HELD, NONE_HELD, {"dev"}, set()),
    ("dev", DEV_ON, "1", NONE_HELD, NONE_HELD, {"dev"}, set()),
    ("dev", DEV_ON, "on", HOLDS, HOLDS, {"dev"}, set()),
    # enabled but the store says nothing, or says something that is not "on"
    ("dev", DEV_ON, None, NONE_HELD, NONE_HELD, {"dev"}, {"activation_secret_store"}),
    ("dev", DEV_ON, "false", NONE_HELD, NONE_HELD, {"dev"}, {"activation_secret_store"}),
    ("dev", DEV_ON, "tru", NONE_HELD, NONE_HELD, {"dev"}, {"activation_secret_store"}),
    ("dev", DEV_ON, "2", NONE_HELD, NONE_HELD, {"dev"}, {"activation_secret_store"}),
    # enabled and held by an app that the store does not hold
    (
        "dev",
        DEV_ON,
        None,
        HOLDS,
        HOLDS,
        {"dev"},
        {"activation_secret_store", "activation_app_api", "activation_app_worker"},
    ),
    # the API and the worker must agree
    ("dev", DEV_ON, "true", HOLDS, NONE_HELD, {"dev"}, {"activation_api_worker_agree"}),
    ("dev", DEV_ON, "true", NONE_HELD, HOLDS, {"dev"}, {"activation_api_worker_agree"}),
    (
        "dev",
        DEV_ON,
        "true",
        state(SETTING, digest="a"),
        state(SETTING, digest="b"),
        {"dev"},
        {"activation_api_worker_agree"},
    ),
    (
        "dev",
        DEV_ON,
        "true",
        state(SETTING, digest=None),
        state(SETTING, digest=None),
        {"dev"},
        {"activation_api_worker_agree"},
    ),
    ("dev", DEV_ON, "true", state(SETTING, digest="a"), state(SETTING, digest="a"), {"dev"}, set()),
    # an app that could not be read is never a pass
    (
        "test",
        OFF,
        None,
        None,
        NONE_HELD,
        {"dev"},
        {"activation_app_api", "activation_api_worker_agree"},
    ),
    (
        "test",
        OFF,
        None,
        NONE_HELD,
        None,
        {"dev"},
        {"activation_app_worker", "activation_api_worker_agree"},
    ),
    (
        "test",
        OFF,
        None,
        None,
        None,
        {"dev"},
        {"activation_app_api", "activation_app_worker", "activation_api_worker_agree"},
    ),
    # the declaration alone can never activate an environment
    (
        "test",
        {**OFF, "test": True},
        "true",
        NONE_HELD,
        NONE_HELD,
        {"dev"},
        {"activation_policy_allowed"},
    ),
    ("dev", DEV_ON, "true", NONE_HELD, NONE_HELD, set(), {"activation_policy_allowed"}),
    (
        "prod",
        {**OFF, "prod": True},
        "true",
        NONE_HELD,
        NONE_HELD,
        set(),
        {"activation_policy_allowed"},
    ),
    # an environment that is enabled elsewhere does not excuse this one
    ("test", {**OFF, "dev": True}, None, NONE_HELD, NONE_HELD, {"dev"}, set()),
    (
        "test",
        {**OFF, "dev": True},
        "true",
        NONE_HELD,
        NONE_HELD,
        {"dev"},
        {"activation_secret_store"},
    ),
]


@pytest.mark.parametrize(
    ("env", "policy", "value", "api", "worker", "activatable", "expected"), TABLE
)
def test_the_decision_table(env, policy, value, api, worker, activatable, expected) -> None:
    checks = run(env, policy, value, api, worker, activatable=activatable)
    assert failed(checks) == expected, [c for c in checks if not c.passed]


def test_a_disabled_environment_is_not_checked_against_the_hosts_when_asked_not_to() -> None:
    checks = run("test", OFF, None, None, None, include_deploy=False)
    assert overall(checks) == "PASS" and {c.id for c in checks} == {
        "activation_policy_allowed",
        "activation_secret_store",
    }


@pytest.mark.parametrize("env", ["qa", "", "DEV"])
def test_an_undeclared_environment_fails(env) -> None:
    assert failed(run(env, OFF, None, NONE_HELD, NONE_HELD)) == {"activation_policy"}


def test_no_value_is_ever_put_in_a_check() -> None:
    checks = run("dev", DEV_ON, "SECRET-VALUE-yes", NONE_HELD, NONE_HELD)
    assert "SECRET-VALUE" not in json.dumps([c.detail for c in checks] + [c.data for c in checks])


@pytest.mark.parametrize(
    "value", [None, "", " ", "true", "TRUE", " yes ", "On", "1", "0", "false", "nope", "tru", "2"]
)
def test_the_effective_value_is_the_runtimes_own_parse(value) -> None:
    assert activation.effective(value) == parse_import_activation(value)


# -- the declaration ---------------------------------------------------------------------------


def declaration(**envs: Any) -> str:
    body = {e: {"import_activation": "disabled"} for e in ENVS}
    body.update(envs)
    return yaml.safe_dump({"environments": body})


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "import-activation.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_complete_declaration_loads(tmp_path: Path) -> None:
    assert load_policy(write(tmp_path, declaration(dev={"import_activation": "enabled"}))) == DEV_ON


BAD_DECLARATIONS = {
    "an empty file": "",
    "not yaml": "a: [unclosed",
    "a list": "- dev\n",
    "an extra top-level key": "environments: {}\nextra: 1\n",
    "environments that is not a mapping": "environments: [dev]\n",
    "a missing environment": yaml.safe_dump(
        {"environments": {e: {"import_activation": "disabled"} for e in ENVS[:3]}}
    ),
    "an unknown environment": declaration(qa={"import_activation": "disabled"}),
    "an extra key in an environment": declaration(dev={"import_activation": "enabled", "x": 1}),
    "an environment with another key": declaration(dev={"enabled": True}),
    "an environment that is a string": declaration(dev="enabled"),
    "a boolean in place of enabled": declaration(dev={"import_activation": True}),
    "yes in place of enabled": declaration(dev={"import_activation": "yes"}),
    "a capitalised value": declaration(dev={"import_activation": "Enabled"}),
    "a padded value": declaration(dev={"import_activation": "enabled "}),
    "an empty value": declaration(dev={"import_activation": ""}),
    "a null value": declaration(dev={"import_activation": None}),
}


@pytest.mark.parametrize("name", sorted(BAD_DECLARATIONS))
def test_a_malformed_declaration_is_refused_never_read_as_off_or_on(name, tmp_path: Path) -> None:
    with pytest.raises(activation.ActivationError):
        load_policy(write(tmp_path, BAD_DECLARATIONS[name]))


def test_a_missing_or_binary_declaration_is_refused(tmp_path: Path) -> None:
    with pytest.raises(activation.ActivationError, match="missing"):
        load_policy(tmp_path / "absent.yaml")
    binary = tmp_path / "b.yaml"
    binary.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(activation.ActivationError):
        load_policy(binary)


def test_the_shipped_declaration_loads() -> None:
    from promotion.config import REPO_ROOT

    policy = load_policy(REPO_ROOT / "local/config/import-activation.yaml")
    assert set(policy) == set(ENVS)


# -- end to end through the adapters, as the CLI does it ----------------------------------------


def _setup(
    tmp_path: Path, declared: str, *, store=None, secrets=None
) -> tuple[PromotionConfig, FakeRunner]:
    config = make_config(tmp_path, activation=True)
    path = tmp_path / "local/config"
    path.mkdir(parents=True, exist_ok=True)
    (path / "import-activation.yaml").write_text(declared, encoding="utf-8")
    runner = FakeRunner(
        store=store or {},
        secrets=secrets
        or {f"shop-{s}-{e}": [{"name": "OTHER"}] for e in ENVS for s in ("api", "worker")},
    )
    return config, runner


def _evaluate(config, runner, env, **kw):
    store, deploy = build_adapters(config, runner)
    checks = activation.evaluate(env, config, store, deploy, **kw)
    assert runner.violations() == []
    return checks


@pytest.mark.parametrize("env", ENVS)
def test_the_shipped_default_every_environment_disabled_and_nothing_set_passes_everywhere(
    env, tmp_path
) -> None:
    config, runner = _setup(tmp_path, declaration())
    assert overall(_evaluate(config, runner, env)) == "PASS"


def test_a_secret_store_that_fails_is_a_fail_not_an_assumed_off(tmp_path) -> None:
    config, runner = _setup(tmp_path, declaration(), store={("test", SETTING): ERROR})
    assert failed(_evaluate(config, runner, "test")) == {"activation_secret_store"}


def test_an_app_that_does_not_exist_is_a_fail(tmp_path) -> None:
    config, runner = _setup(tmp_path, declaration(), secrets={"shop-worker-test": []})
    assert "activation_app_api_read" in failed(_evaluate(config, runner, "test"))


def test_a_declaration_that_enables_an_environment_nobody_listed_fails(tmp_path) -> None:
    config, runner = _setup(
        tmp_path,
        declaration(test={"import_activation": "enabled"}),
        store={("test", SETTING): "true"},
    )
    assert failed(_evaluate(config, runner, "test")) == {"activation_policy_allowed"}


def test_listing_an_environment_as_activatable_is_a_second_separate_edit(tmp_path) -> None:
    def edit(raw):
        raw["activation"]["activatable_environments"] = ["dev", "test"]

    config = make_config(tmp_path, activation=True, edit=edit)
    (tmp_path / "local/config").mkdir(parents=True)
    (tmp_path / "local/config/import-activation.yaml").write_text(
        declaration(test={"import_activation": "enabled"}), encoding="utf-8"
    )
    runner = FakeRunner(
        store={("test", SETTING): "true"},
        secrets={f"shop-{s}-test": [] for s in ("api", "worker")},
    )
    assert overall(_evaluate(config, runner, "test")) == "PASS"


def test_a_missing_declaration_or_missing_section_is_a_fail(tmp_path) -> None:
    config = make_config(tmp_path, activation=True)
    store, deploy = build_adapters(config, FakeRunner())
    assert failed(activation.evaluate("dev", config, store, deploy)) == {"activation_policy"}
    plain = make_config(tmp_path)
    assert failed(activation.evaluate("dev", plain, store, deploy)) == {"activation_policy"}


def test_the_gate_reports_off_for_a_disabled_environment_and_names_what_it_checked(
    tmp_path,
) -> None:
    config, runner = _setup(tmp_path, declaration())
    store, deploy = build_adapters(config, runner)
    checks = gate.check_activation("test", config, store, deploy)
    assert overall(checks) == "PASS" and checks[-1].id == "imports_off"
    assert "disabled" in checks[-1].detail


def test_the_gate_cannot_call_a_hand_set_value_off(tmp_path) -> None:
    config, runner = _setup(
        tmp_path,
        declaration(),
        secrets={f"shop-{s}-test": [{"name": SETTING}] for s in ("api", "worker")},
    )
    store, deploy = build_adapters(config, runner)
    checks = gate.check_activation("test", config, store, deploy)
    assert overall(checks) == "FAIL" and checks[-1].id == "imports_off" and not checks[-1].passed


def test_the_cli_prints_json_and_exits_nonzero_on_a_fail(tmp_path, capsys, monkeypatch) -> None:
    from promotion_support import raw_config

    _config, runner = _setup(tmp_path, declaration(), store={("test", SETTING): "false"})
    path = tmp_path / "promotion.yaml"
    path.write_text(yaml.safe_dump(raw_config(activation=True)), encoding="utf-8")
    original = activation.load_config
    # the declaration the config names is resolved against the repository root: use the temp tree
    monkeypatch.setattr(activation, "load_config", lambda p=None: original(path, tmp_path))
    code = activation.cli(["test"], runner=runner)
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out["status"] == "FAIL" and out["environment"] == "test"
    assert runner.violations() == []


def test_the_cli_fails_on_a_configuration_it_cannot_read(tmp_path, capsys) -> None:
    assert activation.cli(["test", "--config", str(tmp_path / "none.yaml")]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
