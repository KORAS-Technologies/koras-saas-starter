"""The per-environment import activation declaration: its schema, and that the setting is declared.

`local/config/import-activation.yaml` says which environments are meant to have data import
on (ADR 0013 section 7). It ships with every environment `disabled`; a reviewed commit changes
that. These tests hold the *shape* of the file, not its values, so a product that has
activated an environment keeps a green suite -- the vocabulary and the set of environments
are the contract.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DECLARATION = REPO / "local" / "config" / "import-activation.yaml"
DRIFT_SCRIPT = REPO / "local" / "scripts" / "import-activation-drift.sh"
MANIFEST = REPO / "local" / "config" / "secrets.manifest"

ENVIRONMENTS = {"dev", "test", "stg", "prod"}
VOCABULARY = {"enabled", "disabled"}


def _declared() -> dict[str, str]:
    """`{environment: value}` from the two-level mapping, without a YAML dependency."""
    found: dict[str, str] = {}
    current: str | None = None
    in_block = False
    for line in DECLARATION.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("environments:"):
            in_block = True
            continue
        if not in_block:
            continue
        if env := re.fullmatch(r"  ([a-z]+):\s*", line):
            current = env.group(1)
            continue
        if (value := re.fullmatch(r"    import_activation:\s*(\S+)\s*", line)) and current:
            assert current not in found, f"{current} is declared twice"
            found[current] = value.group(1)
            continue
        raise AssertionError(f"not part of the schema: {line!r}")
    return found


def test_the_declaration_names_exactly_the_four_environments() -> None:
    assert set(_declared()) == ENVIRONMENTS


def test_every_environment_is_enabled_or_disabled_and_nothing_else() -> None:
    for environment, value in _declared().items():
        assert value in VOCABULARY, f"{environment}: {value!r} is not enabled or disabled"


def test_the_setting_is_declared_optional_in_the_manifest() -> None:
    lines = MANIFEST.read_text(encoding="utf-8").splitlines()
    assert any(re.fullmatch(r"IMPORTS_ENABLED optional.*", line) for line in lines)


def test_the_manifest_never_supplies_the_setting() -> None:
    """`supplied` would make an unset value a startup failure; absent must mean off."""
    assert not any(
        line.startswith("IMPORTS_ENABLED supplied")
        for line in MANIFEST.read_text(encoding="utf-8").splitlines()
    )


def test_the_drift_script_reads_names_only_and_is_valid_shell() -> None:
    text = DRIFT_SCRIPT.read_text(encoding="utf-8")
    assert 'setting="IMPORTS_ENABLED"' in text
    assert "set -eu" in text and "set +x" in text
    bash = shutil.which("bash")
    if bash is None:
        pytest.fail("bash is required to check the drift script's syntax")
    subprocess.run([bash, "-n", str(DRIFT_SCRIPT)], check=True)  # noqa: S603
