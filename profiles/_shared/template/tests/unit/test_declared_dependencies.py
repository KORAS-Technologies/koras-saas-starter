"""Every module a package imports must be declared as its dependency.

Four defects of exactly this shape have been found so far: the OTLP exporter
(R-34), httpx and python-jose (R-39), asyncpg (R-43), and email-validator
(R-45). Each was invisible locally because the monorepo shares one virtual
environment -- some other package declared the dependency, so the import
resolved and nothing complained. They surface at deploy time, in a container
built from one manifest, or at the first request that touches a lazily imported
name.

This is a static check rather than a per-service install: it reads the imports
out of the source and compares them against the manifest. That is fast enough to
run on every commit, which a set of throwaway virtual environments would not be.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Distributions every package may use without declaring: they come from the
# workspace dev group and are never imported by shipped code.
DEV_ONLY = {"pytest", "mypy", "ruff"}


def _packages() -> list[Path]:
    """Every distributable in the workspace, each with its own manifest."""
    found = [p.parent for p in REPO_ROOT.glob("python-packages/*/pyproject.toml")]
    found += [p.parent for p in REPO_ROOT.glob("services/*/pyproject.toml")]
    return sorted(found)


def _declared(package: Path) -> set[str]:
    manifest = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))
    project = manifest.get("project", {})
    names = set()
    for entry in project.get("dependencies", []):
        # "python-jose[cryptography]>=3.3.0" -> "python-jose"
        name = entry.split(";")[0].split("[")[0]
        for separator in (">=", "<=", "==", "~=", "!=", ">", "<"):
            name = name.split(separator)[0]
        names.add(_normalise(name.strip()))
    names.add(_normalise(project.get("name", "")))
    return names


def _normalise(name: str) -> str:
    return name.lower().replace("_", "-")


def _own_modules(package: Path) -> set[str]:
    """The importable packages this distributable itself provides.

    A service imports itself absolutely in places -- `koras_api.main:app` is how
    uvicorn is told what to run -- and a package need not declare itself. Read
    from the directory rather than assumed from the manifest name: the two
    differ by design, since a distribution is `koras-control-plane-api` and its
    module is `koras_api`.
    """
    return {
        child.name
        for child in package.iterdir()
        if child.is_dir() and (child / "__init__.py").exists()
    } | {
        child.parent.name
        for child in package.glob("src/*/__init__.py")
    }


def _imported_modules(package: Path) -> set[str]:
    """Top-level modules imported by this package, excluding relative imports."""
    modules: set[str] = set()
    for source in package.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                # level > 0 is a relative import, which needs no declaration.
                if node.level == 0 and node.module:
                    modules.add(node.module.split(".")[0])
    return modules


def _distributions_for(module: str) -> list[str]:
    """Which distributions provide this module.

    Editable workspace installs do not always appear in the metadata index, so
    first-party packages are resolved by convention: koras_auth is koras-auth.

    A list rather than one name, because a namespace package is provided by
    several. Nine distributions contribute to ``opentelemetry``, and taking the
    first the metadata index happened to list reported a package that declares
    ``opentelemetry-api`` as importing something undeclared -- a failure that
    depended on install order rather than on the manifest.
    """
    if module.startswith("koras_"):
        return [_normalise(module)]
    return [_normalise(name) for name in packages_distributions().get(module, [])]


@pytest.mark.parametrize("package", _packages(), ids=lambda p: p.name)
def test_every_import_is_declared(package: Path) -> None:
    declared = _declared(package)
    undeclared: list[str] = []

    for module in sorted(_imported_modules(package)):
        # The package's own top-level module. It was "src" for every service,
        # which is the collision that made a repo-wide mypy run abort on
        # duplicate modules and why each is now named after itself.
        if module in sys.stdlib_module_names or module in _own_modules(package):
            continue
        providers = _distributions_for(module)
        if not providers:
            # Not installed at all, so nothing can be concluded about the
            # manifest; the import would already be failing.
            continue
        if any(name in DEV_ONLY or name in declared for name in providers):
            continue
        undeclared.append(f"{module} (provided by {', '.join(providers)})")

    assert not undeclared, (
        f"{package.relative_to(REPO_ROOT)} imports these without declaring them: "
        + ", ".join(undeclared)
    )
