# ruff: noqa: ANN001, ANN202, S105, ANN201, ANN401, E501
"""`local/config/promotion.yaml`: strict, fail-closed, and the generated file is valid."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from promotion.config import (
    CONFIG_PATH,
    REPO_ROOT,
    ConfigError,
    load_config,
    parse_config,
)
from promotion_support import make_config, raw_config


def test_a_complete_declaration_parses(tmp_path: Path) -> None:
    config = make_config(tmp_path, activation=True)
    assert config.secret_store_project == "shop"
    assert config.environments["prod"].apps["clamd"] == "shop-clamd-prod"
    assert config.secret_store_config("stg") == "stg"
    assert config.activation is not None
    assert config.activation.activatable_environments == {"dev"}
    assert config.register_path == tmp_path / "docs/security/REGISTER.md"
    assert make_config(tmp_path).activation is None


def _drop(*path: str):
    def edit(raw: dict[str, Any]) -> None:
        node = raw
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]

    return edit


def _set(*path_and_value: Any):
    *path, value = path_and_value

    def edit(raw: dict[str, Any]) -> None:
        node = raw
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return edit


INVALID = {
    "an unknown top-level key": _set("surprise", 1),
    "a missing section": _drop("scanner"),
    "a missing key": _drop("ci", "required_jobs"),
    "an unknown key in a section": _set("scanner", "extra", "x"),
    "a wrong version": _set("version", 2),
    "a boolean version": _set("version", True),
    "a string version": _set("version", "1"),
    "an unknown secret store": _set("secret_store", "provider", "vault"),
    "an unknown deploy target": _set("deploy", "provider", "heroku"),
    "an unknown CI provider": _set("ci", "provider", "jenkins"),
    "a missing environment": _drop("environments", "prod"),
    "an extra environment": _set("environments", "qa", {}),
    "an app name that is an option": _set("environments", "dev", "apps", "api", "--app"),
    "an app name with a space": _set("environments", "dev", "apps", "api", "a b"),
    "an app name with a slash": _set("environments", "dev", "apps", "worker", "a/b"),
    "an app name with a semicolon": _set("environments", "dev", "apps", "clamd", "a;rm"),
    "an empty app name": _set("environments", "dev", "apps", "api", ""),
    "a non-string app name": _set("environments", "dev", "apps", "api", 5),
    "a missing app": _drop("environments", "test", "apps", "clamd"),
    "an unknown app": _set("environments", "test", "apps", "cron", "x"),
    "a project that is an option": _set("secret_store", "project", "-p"),
    "a lower-case setting name": _set("scanner", "backend_setting", "file_scan_backend"),
    "a setting name with a dash": _set("database", "admin_url_setting", "DATABASE-URL"),
    "an empty CI job list": _set("ci", "required_jobs", []),
    "a CI job list that is not a list": _set("ci", "required_jobs", "Lint"),
    "a duplicated CI job": _set("ci", "required_jobs", ["Lint", "Lint"]),
    "a CI job with a control character": _set("ci", "required_jobs", ["Li\x00nt"]),
    "a register pattern that does not compile": _set("register", "id_pattern", "[A-Z"),
    "an empty register pattern": _set("register", "id_pattern", ""),
    "chain ids that are not a list": _set("register", "chain_ids", "SEC-1"),
    "an absolute register path": _set("register", "path", "/etc/passwd"),
    "a register path that climbs out": _set("register", "path", "../outside.md"),
    "a register path that climbs out in the middle": _set("register", "path", "docs/../../x.md"),
    "a register path with a NUL": _set("register", "path", "docs/\x00x.md"),
    "an empty dispositions path": _set("f1", "dispositions", ""),
    "a qualification age of zero": _set("qualification", "max_age_days", 0),
    "a qualification age beyond the limit": _set("qualification", "max_age_days", 91),
    "a boolean qualification age": _set("qualification", "max_age_days", True),
    "a fractional qualification age": _set("qualification", "max_age_days", 1.5),
}


@pytest.mark.parametrize("name", sorted(INVALID))
def test_an_invalid_declaration_is_refused(name: str, tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        make_config(tmp_path, edit=INVALID[name])


INVALID_ACTIVATION = {
    "an unknown activatable environment": _set("activation", "activatable_environments", ["qa"]),
    "activatable environments that are not a list": _set(
        "activation", "activatable_environments", "dev"
    ),
    "no activatable environments key": _drop("activation", "activatable_environments"),
    "no declaration path": _drop("activation", "declaration"),
    "a declaration that climbs out": _set("activation", "declaration", "../x.yaml"),
    "an unknown activation key": _set("activation", "enabled", True),
}


@pytest.mark.parametrize("name", sorted(INVALID_ACTIVATION))
def test_an_invalid_activation_section_is_refused(name: str, tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        make_config(tmp_path, activation=True, edit=INVALID_ACTIVATION[name])


@pytest.mark.parametrize("raw", [None, [], "text", 3, {}])
def test_a_document_that_is_not_a_mapping_of_the_right_shape_is_refused(
    raw: object, tmp_path: Path
) -> None:
    with pytest.raises(ConfigError):
        parse_config(raw, tmp_path)


def test_the_file_is_read_strictly(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="missing"):
        load_config(tmp_path / "absent.yaml")
    broken = tmp_path / "broken.yaml"
    broken.write_text("a: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot be parsed"):
        load_config(broken)
    binary = tmp_path / "binary.yaml"
    binary.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(ConfigError):
        load_config(binary)
    good = tmp_path / "good.yaml"
    good.write_text(yaml.safe_dump(raw_config()), encoding="utf-8")
    assert load_config(good, tmp_path).secret_store_provider == "doppler"


def test_the_shipped_declaration_is_valid() -> None:
    config = load_config(CONFIG_PATH)
    assert config.root == REPO_ROOT
    assert set(config.environments) == {"dev", "test", "stg", "prod"}
    text = CONFIG_PATH.read_text(encoding="utf-8")
    assert "{{" not in text and "}}" not in text, "an unrendered template placeholder"
    # Every path the declaration names stays inside the repository and the register exists.
    for path in (config.register_path, config.f1_dispositions):
        assert path.resolve().is_relative_to(REPO_ROOT.resolve())
    assert config.register_path.is_file()
