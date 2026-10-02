"""The worker image carries every module the worker reaches.

IMPORT-DEF-020. The worker does not depend on the API's distribution. What it
needs of the API it reaches by name -- `importlib.import_module("koras_api...")`
-- and the Dockerfile copies those files into the image one line at a time. A
module one of them imports, and no line copies, is not a build error and not
an import error at start-up: it is whatever the job does when the import
fails, and for `importlib` behind a graceful `except` that has twice been
nothing at all.

On 2026-10-02 the product's own image was run for the first time rather than
its source tree. The audit sink imported `core/database.py` inside the
function that runs after it commits; the image had never carried that file;
so every dry run in a deployed worker was recorded as a failed job after its
run had been committed `validated`. Every suite was green, because every
suite runs where the whole tree is on the path.

So this walks the imports. From each module the worker names, through every
`import` of `koras_api` in it -- at the top of the file or inside a function
-- to everything those reach, and asserts the Dockerfile copies each one.

**An import inside a function is followed too**, which is the point: that is
the shape the defect had. The one that is allowed not to be in the image is
named below with its reason, and may only ever be an import inside a function.

`.github/` builds the image and runs a dry run and a commit in it, which is
the other half: this says the files are there, and that says they load.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "services" / "worker"
API = ROOT / "services" / "api"
DOCKERFILE = WORKER / "Dockerfile"

if not DOCKERFILE.is_file():
    pytest.skip("this product was generated without a worker", allow_module_level=True)

#: Reached only inside a function the worker's path never calls, and not in
#: the image on purpose. An entry here is a claim, so each says why.
NOT_IN_THE_IMAGE = {
    # `core/recipients._platform()`: the platform's member list, which needs a
    # caller's token. A worker has none; the import notice names its audience
    # by subject and never asks for a role's members. The module builds the
    # API's `Settings()` at import, which is why it is reached lazily at all.
    "koras_api.core.platform",
}


def _file_of(module: str) -> Path | None:
    base = API.joinpath(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _named_by_the_worker() -> set[str]:
    """Every `koras_api` module a worker file passes to `import_module`."""
    named: set[str] = set()
    for path in (WORKER / "koras_worker").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and str(node.args[0].value).startswith("koras_api")
            ):
                named.add(str(node.args[0].value))
    return named


def _imports(module: str, path: Path) -> list[tuple[str, bool]]:
    """The `koras_api` modules a file imports, and whether each is at the top of it."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    found: list[tuple[str, bool]] = []

    def visit(node: ast.AST, top: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If) and "TYPE_CHECKING" in ast.unparse(child.test):
                # Never executed, so never needed.
                continue
            inner = top and not isinstance(
                child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
            )
            if isinstance(child, ast.Import):
                found.extend((alias.name, top) for alias in child.names)
            elif isinstance(child, ast.ImportFrom):
                base = child.module or ""
                if child.level:
                    parts = package.split(".")
                    parent = ".".join(parts[: len(parts) - (child.level - 1)])
                    base = f"{parent}.{base}" if base else parent
                found.append((base, top))
                # `from . import outbox` names a module; `from .x import y`
                # names one only when `y` is a file.
                found.extend(
                    (f"{base}.{alias.name}", top)
                    for alias in child.names
                    if _file_of(f"{base}.{alias.name}") is not None
                )
            visit(child, inner)

    visit(tree, True)
    return [(name, top) for name, top in found if name.split(".")[0] == "koras_api"]


def _needed() -> dict[str, Path]:
    """Every file the worker can come to import, by module."""
    needed: dict[str, Path] = {}
    queue = sorted(_named_by_the_worker())
    while queue:
        module = queue.pop()
        if module in needed:
            continue
        path = _file_of(module)
        if path is None:
            # A name that is not a module.
            continue
        if path.name == "__init__.py" and not path.read_text(encoding="utf-8").strip():
            # An empty package marker. The image has none of them and needs
            # none: `koras_api` and `koras_api.core` are namespaces there. One
            # with a statement in it is a module like any other, and is needed.
            continue
        needed[module] = path
        for name, top in _imports(module, path):
            if name in NOT_IN_THE_IMAGE:
                assert not top, (
                    f"{module} imports {name} at the top of the file, and the image has no such "
                    "module: the worker cannot import it at all"
                )
                continue
            queue.append(name)
    return needed


_COPY = re.compile(r"^COPY\s+services/api/(koras_api/\S+)\s", re.MULTILINE)


def _missing(dockerfile: str) -> list[str]:
    """The modules the worker needs and this Dockerfile does not copy."""
    copied = _COPY.findall(dockerfile)
    missing = []
    for module, path in sorted(_needed().items()):
        relative = path.relative_to(API).as_posix()
        if not any(
            relative.startswith(entry) if entry.endswith("/") else relative == entry
            for entry in copied
        ):
            missing.append(f"{module} ({relative})")
    return missing


def test_the_image_carries_every_module_the_worker_reaches() -> None:
    missing = _missing(DOCKERFILE.read_text(encoding="utf-8"))

    assert not missing, (
        "the worker's Dockerfile copies none of these, and the worker can import each of them: "
        + ", ".join(missing)
    )


def test_the_audit_sink_is_whole_inside_the_image() -> None:
    """The instance, by name: what the sink calls after it commits is in the image."""
    if "koras_api.core.audit" not in _named_by_the_worker():
        pytest.skip("this product's worker records no audit event through the API's sink")
    needed = _needed()

    assert "koras_api.core.rebind" in needed
    assert "koras_api.core.database" not in needed, (
        "the audit sink reaches the request's sessions again, which the worker image has never "
        "carried and cannot: they import FastAPI and build the API's Settings()"
    )


def test_every_copy_is_one_the_check_above_would_miss() -> None:
    """The check can fail, line by line: remove any one copy and something is missing.

    Which also says the Dockerfile copies nothing of the API it does not
    need -- a line nothing reaches is how an image comes to carry a module
    with the API's settings behind it.
    """
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    lines = [match.group(0) for match in _COPY.finditer(dockerfile)]
    if not lines:
        pytest.skip("this product's worker reaches nothing of the API")

    for line in lines:
        assert _missing(dockerfile.replace(line, "", 1)), (
            f"nothing the worker reaches needs this line: {line.strip()}"
        )


def test_an_import_inside_a_function_is_followed(tmp_path: Path) -> None:
    """The shape IMPORT-DEF-020 had, against the walker rather than the product."""
    module = tmp_path / "sink.py"
    module.write_text(
        "from typing import TYPE_CHECKING\n"
        "from . import outbox\n"
        "if TYPE_CHECKING:\n"
        "    from .never import Thing\n"
        "async def rebind():\n"
        "    from .database import rebind_tenant\n",
        encoding="utf-8",
    )

    found = _imports("koras_api.core.sink", module)

    assert ("koras_api.core.database", False) in found
    assert ("koras_api.core", True) in found
    assert "koras_api.core.never" not in [name for name, _ in found]
