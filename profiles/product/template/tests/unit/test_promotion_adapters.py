# ruff: noqa: ANN001, ANN003, ANN202, ANN201, ANN401, E501
"""The secret-store and deploy adapters: read-only, validated, and every failure is an error."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from promotion.adapters import (
    AdapterError,
    DopplerStore,
    FlyTarget,
    build_adapters,
)
from promotion_support import ERROR, FakeRunner, is_read_only, make_config, proc

CONFIGS = {"dev": "dev", "test": "test", "stg": "stg", "prod": "prd"}


def _store(runner) -> DopplerStore:
    return DopplerStore("shop", CONFIGS, runner)


def test_a_value_is_returned_without_its_line_endings_and_the_argv_is_exact() -> None:
    runner = FakeRunner(store={("prd", "X_SETTING"): "a-value"})
    assert _store(runner).get("prod", "X_SETTING") == "a-value"
    assert runner.calls == [
        [
            "doppler", "secrets", "get", "X_SETTING", "--plain",
            "--project", "shop", "--config", "prd",
        ]
    ]  # fmt: skip


def test_an_absent_setting_is_none_and_any_other_failure_is_an_error() -> None:
    assert _store(FakeRunner()).get("dev", "X_SETTING") is None
    with pytest.raises(AdapterError, match="could not read"):
        _store(FakeRunner(store={("dev", "X_SETTING"): ERROR})).get("dev", "X_SETTING")


@pytest.mark.parametrize("error", [OSError("no doppler"), subprocess.TimeoutExpired("doppler", 1)])
def test_a_command_that_cannot_run_is_an_error_not_an_absence(error) -> None:
    def boom(argv):
        raise error

    with pytest.raises(AdapterError, match="could not be run"):
        _store(boom).get("dev", "X_SETTING")


@pytest.mark.parametrize(
    "name", ["--config", "-x", "x_setting", "A B", "A;B", "A/B", "", "1A", "A" * 65, "A\nB"]
)
def test_a_setting_name_that_could_be_an_option_or_inject_is_refused_before_a_command_runs(
    name: str,
) -> None:
    runner = FakeRunner()
    with pytest.raises(AdapterError):
        _store(runner).get("dev", name)
    assert runner.calls == []


@pytest.mark.parametrize("env", ["qa", "", "DEV", "dev ", "../dev"])
def test_an_environment_that_is_not_configured_is_refused(env: str) -> None:
    runner = FakeRunner()
    with pytest.raises(AdapterError):
        _store(runner).get(env, "X_SETTING")
    assert runner.calls == []


@pytest.mark.parametrize("project", ["--x", "a b", "", "a/b"])
def test_a_bad_project_is_refused_at_construction(project: str) -> None:
    with pytest.raises(AdapterError):
        DopplerStore(project, CONFIGS, FakeRunner())


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"DOPPLER_CONFIG": "dev"}, "dev"),
        ({"DOPPLER_CONFIG": "prd"}, "prod"),
        ({"DOPPLER_CONFIG": "dev", "DOPPLER_PROJECT": "shop"}, "dev"),
        ({"DOPPLER_CONFIG": "dev", "DOPPLER_PROJECT": "another"}, None),
        ({"DOPPLER_CONFIG": "prod"}, None),
        ({"DOPPLER_CONFIG": ""}, None),
        ({}, None),
    ],
)
def test_the_environment_a_process_is_bound_to(environ, expected) -> None:
    assert _store(FakeRunner()).bound_environment(environ) == expected


# -- Fly -------------------------------------------------------------------------------------


def test_secret_names_and_digests_are_read_and_no_value_exists_to_read() -> None:
    rows = [
        {"name": "IMPORTS_ENABLED", "digest": "abc"},
        {"Name": "OTHER", "Digest": "def"},
        {"name": "NO_DIGEST"},
        "not a row",
        {"name": 5},
    ]
    state = FlyTarget(FakeRunner(secrets={"shop-api-dev": rows})).secrets("shop-api-dev")
    assert state.names == {"IMPORTS_ENABLED", "OTHER", "NO_DIGEST"}
    assert state.digests == {"IMPORTS_ENABLED": "abc", "OTHER": "def", "NO_DIGEST": None}


@pytest.mark.parametrize(
    "runner",
    [
        FakeRunner(),  # the app does not exist
        lambda argv: proc("not json"),
        lambda argv: proc('{"a": 1}'),
        lambda argv: proc("", 1, "boom"),
    ],
)
def test_an_unreadable_app_is_an_error_never_an_empty_answer(runner) -> None:
    with pytest.raises(AdapterError):
        FlyTarget(runner).secrets("shop-api-dev")
    with pytest.raises(AdapterError):
        FlyTarget(runner).machines("shop-api-dev")


def test_a_command_that_cannot_run_is_an_error() -> None:
    def boom(argv):
        raise OSError("no flyctl")

    with pytest.raises(AdapterError, match="could not be run"):
        FlyTarget(boom).secrets("shop-api-dev")


def test_machines_are_listed() -> None:
    runner = FakeRunner(machines={"shop-clamd-dev": [{"state": "started"}, "junk"]})
    assert FlyTarget(runner).machines("shop-clamd-dev") == [{"state": "started"}]


@pytest.mark.parametrize("app", ["--app", "-x", "a b", "a;b", "", "a/b", "A" * 64])
def test_an_app_name_that_could_be_an_option_is_refused_before_a_command_runs(app: str) -> None:
    runner = FakeRunner()
    with pytest.raises(AdapterError):
        FlyTarget(runner).secrets(app)
    with pytest.raises(AdapterError):
        FlyTarget(runner).machines(app)
    assert runner.calls == []


# -- the boundary ----------------------------------------------------------------------------


def test_every_command_the_adapters_issue_is_on_the_read_only_allowlist(tmp_path) -> None:
    runner = FakeRunner(
        store={("dev", "A"): "1"},
        secrets={"shop-api-dev": []},
        machines={"shop-clamd-dev": []},
    )
    store, target = build_adapters(make_config(tmp_path), runner)
    store.get("dev", "A")
    target.secrets("shop-api-dev")
    target.machines("shop-clamd-dev")
    assert len(runner.calls) == 3
    assert runner.violations() == []


def test_the_allowlist_accepts_the_reads_and_refuses_anything_else() -> None:
    for ok_argv in (
        ["doppler", "secrets", "get", "X", "--plain", "--project", "p", "--config", "dev"],
        ["flyctl", "secrets", "list", "--app", "a", "--json"],
        ["flyctl", "machines", "list", "--app", "a", "--json"],
        ["gh", "api", "repos/{owner}/{repo}/commits/x/check-runs", "--paginate", "--jq", "."],
        ["git", "-C", "/x", "rev-parse", "HEAD"],
    ):
        assert is_read_only(ok_argv), ok_argv
    for bad_argv in (
        ["doppler", "secrets", "set", "X=1"],
        ["doppler", "secrets", "delete", "X"],
        ["flyctl", "secrets", "set", "X=1", "--app", "a"],
        ["flyctl", "secrets", "unset", "X", "--app", "a"],
        ["flyctl", "secrets", "import"],
        ["flyctl", "deploy"],
        ["flyctl", "machines", "stop", "m"],
        ["gh", "api", "x", "--method", "POST"],
        ["gh", "api", "x", "-X", "PATCH"],
        ["gh", "api", "x", "-XPOST"],
        ["gh", "api", "x", "--method=DELETE"],
        ["gh", "api", "x", "-f", "a=b"],
        ["gh", "pr", "merge", "1"],
        ["git", "push"],
        ["git", "checkout", "main"],
        ["rm", "-rf", "/"],
    ):
        assert not is_read_only(bad_argv), bad_argv


def test_an_unknown_provider_has_no_adapter(tmp_path) -> None:
    config = make_config(tmp_path)
    object.__setattr__(config, "secret_store_provider", "vault")
    with pytest.raises(AdapterError, match="no adapter"):
        build_adapters(config, FakeRunner())


def test_the_adapter_module_names_no_write_command() -> None:
    """A source-level guard: the verbs that change anything do not appear in the adapters."""
    import promotion.adapters as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for verb in ('"set"', '"unset"', '"delete"', '"import"', '"deploy"', '"destroy"', '"stop"'):
        assert verb not in source, verb
