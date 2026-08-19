"""Guards on the generated scaffold.

These exist partly so that `make test` passes on a freshly generated project --
pytest exits non-zero when it collects nothing -- and partly because each one
has failed for real at some point.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_the_manifest_records_the_generating_profile() -> None:
    manifest = yaml.safe_load((REPO_ROOT / ".koras" / "project.yaml").read_text(encoding="utf-8"))
    assert manifest["project"]["profile"] in {"product", "control-plane"}


def _makefile_list(name: str) -> list[str]:
    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(rf"^{name} := (.*)$", text, re.MULTILINE)
    assert match is not None, f"Makefile no longer declares {name}"
    return match.group(1).split()


def test_every_vercel_app_points_at_a_real_directory() -> None:
    """Component keys need not match their directory, so the map must be right.

    terraform.tfvars carries application_source_dirs, and the Vercel module uses
    it for root_directory. A path that does not exist produces a project whose
    builds cannot find their source, which surfaces only at deploy time.
    """
    tfvars = (REPO_ROOT / "infrastructure" / "terraform" / "terraform.tfvars").read_text(
        encoding="utf-8"
    )
    match = re.search(r"application_source_dirs\s*=\s*\{(.*?)\}", tfvars, re.DOTALL)
    assert match is not None, "terraform.tfvars declares no application_source_dirs"
    pairs = re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', match.group(1))
    assert pairs, "application_source_dirs is empty"
    for key, path in pairs:
        assert (REPO_ROOT / path).is_dir(), f"app {key} maps to {path}, which does not exist"


def test_every_service_has_a_directory() -> None:
    for service in _makefile_list("SERVICES"):
        assert (REPO_ROOT / "services" / service).is_dir()


def test_every_service_is_startable_by_make_dev() -> None:
    """`make dev` runs `turbo run dev`, which only sees pnpm workspace members.

    A Python service with no package.json is skipped in silence while the
    command reports success.
    """
    import json

    for service in _makefile_list("SERVICES"):
        manifest = REPO_ROOT / "services" / service / "package.json"
        assert manifest.is_file(), f"services/{service} has no package.json; turbo cannot run it"
        scripts = json.loads(manifest.read_text(encoding="utf-8")).get("scripts", {})
        assert "dev" in scripts, f"services/{service} defines no dev script"


def test_every_compose_port_is_resolved_by_ports_sh() -> None:
    """Host ports are machine-global; an unresolved one falls back to a literal.

    Two KORAS stacks then race for the same number and the loser silently
    connects to the winner's container.
    """
    compose = (REPO_ROOT / "local" / "docker-compose.yml").read_text(encoding="utf-8")
    ports_sh = (REPO_ROOT / "local" / "scripts" / "ports.sh").read_text(encoding="utf-8")
    declared = set(re.findall(r"^(KORAS_PORT_[A-Z0-9_]+)\s+\d+$", ports_sh, re.MULTILINE))
    used = set(re.findall(r"\$\{(KORAS_PORT_[A-Z0-9_]+)", compose))
    unresolved = sorted(used - declared)
    assert not unresolved, f"used in compose but not resolved by ports.sh: {unresolved}"
