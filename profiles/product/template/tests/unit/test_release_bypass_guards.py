"""Cross-path guards for the one release rule (ADR 0013, `secure_files`), in both modes.

`core/file_release.py` is the only place that decides whether a stored file's content may be
released, and every consumer asks it. These guards keep that true as the code changes. They are
static: they read the product's own source, so they run in whichever mode the product was
generated in and assert **that mode's** shape --

* **with the capability** nothing reads bytes, signs a URL, or retrieves derived content except
  through the primitive or its HTTP gate, no module keeps a deny-list of scan states, no file hook
  can be handed a URL, and only the scanner's transitions write a verdict;
* **without it** the product is what it always was: the download is withheld by the platform
  seam's deny-list (reached through the primitive), a hook is handed a signed URL at upload, and
  the import source keeps its narrower rule -- so nothing here may drift toward the strict rule
  by accident either.

Defence in depth. The control is the runtime rule, proven per state in `test_file_release.py` and
`test_files_release_api.py`, and against a real PostgreSQL in `tests/integration/`.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from koras_api.core.secure_files import SECURE_FILES

REPO = Path(__file__).resolve().parents[2]
API = REPO / "services" / "api" / "koras_api"
PRODUCT_CODE = (API, REPO / "services" / "worker" / "koras_worker")


def _python_files() -> list[Path]:
    return [
        path
        for root in PRODUCT_CODE
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


def _names(path: Path) -> set[str]:
    """Every identifier the module uses or imports -- not prose in a docstring or comment."""
    found: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.alias):
            found.add(node.name.rsplit(".", 1)[-1])
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            found.add(node.name)
    return found


def _api(name: str) -> Path:
    return API / name


# -- 0. the mode this product was generated in -------------------------------------------------


def test_the_mode_is_the_generated_constant_and_the_capabilitys_files_agree_with_it() -> None:
    capability_only = (
        _api("core/file_release_gate.py"),
        _api("core/release_audit.py"),
        _api("core/upload_window.py"),
    )
    assert all(path.exists() is SECURE_FILES for path in capability_only)
    assert _api("core/file_release.py").exists(), "the rule is generated in both modes"


# -- 1. who may assign a scan verdict ------------------------------------------------------------

#: The statements that may assign `files.scan_status`, and the values each may assign. The scanner's
#: transitions write the verdicts; the platform's `record_scan` is dead code that writes a caller's
#: value, so it is allowed only while nothing calls it (the next test). A module that returns a
#: file to `pending` -- a restore's replacement -- is added here with the layer that introduces it.
_SCAN_STATUS_WRITERS: dict[str, frozenset[str]] = {
    "services/worker/koras_worker/scanning/transition.py": frozenset({"'infected'", "'clean'"}),
    "services/api/koras_api/core/file_scan.py": frozenset({":status"}),
}

_SET_CLAUSE = re.compile(r"\bset\b(.*?)(?:\bwhere\b|\breturning\b|$)", re.S | re.I)
_ASSIGNS_SCAN_STATUS = re.compile(r"\bscan_status\s*=\s*('[a-z]+'|:\w+)", re.I)


def _scan_status_assignments(path: Path) -> set[str]:
    """Values assigned to `scan_status` in an UPDATE of `public.files` or named in its INSERT."""
    found: set[str] = set()
    for node in ast.walk(_tree(path)):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        sql = " ".join(node.value.split())
        lowered = sql.lower()
        if "update public.files" in lowered:
            for clause in _SET_CLAUSE.findall(sql):
                found.update(match.lower() for match in _ASSIGNS_SCAN_STATUS.findall(clause))
        elif "insert into public.files" in lowered and "scan_status" in lowered:
            found.add("<insert>")
    return found


def scan_status_violations(
    sources: dict[str, Path], registry: dict[str, frozenset[str]] | None = None
) -> list[str]:
    """Violations of the writer registry for `{name: path}`; empty when every writer is allowed.

    A helper so the guard itself can be proven against synthetic modules (see
    `test_the_guard_rejects_unauthorized_scan_status_writers`): a tripwire that has never been
    seen to trip is not evidence.
    """
    allowed = _SCAN_STATUS_WRITERS if registry is None else registry
    violations: list[str] = []
    for name, path in sources.items():
        values = _scan_status_assignments(path)
        if not values:
            continue
        if name not in allowed:
            violations.append(
                f"{name} assigns files.scan_status ({sorted(values)}); only the scanner's "
                "transitions write a verdict (ADR 0013)"
            )
        elif not values <= allowed[name]:
            violations.append(f"{name} assigns {sorted(values)}, beyond {sorted(allowed[name])}")
    return violations


def test_only_the_scanner_assigns_a_scan_status() -> None:
    sources = {_rel(path): path for path in _python_files()}
    assert scan_status_violations(sources) == []
    found = {
        name: values for name, path in sources.items() if (values := _scan_status_assignments(path))
    }
    # The scan is not vacuous: the platform seam is found in every product, and the one writer
    # of verdicts is found in a product that has the scanner.
    assert found["services/api/koras_api/core/file_scan.py"] == {":status"}
    scanner = "services/worker/koras_worker/scanning/transition.py"
    assert (scanner in found) is SECURE_FILES
    if SECURE_FILES:
        assert found[scanner] == {"'clean'", "'infected'"}


def test_the_guard_rejects_unauthorized_scan_status_writers(tmp_path: Path) -> None:
    """Mutation check: the ways a later change could recreate a bypass are all reported."""
    update = "update public.files set {assign} where id = :id"
    new_module = tmp_path / "new_module.py"
    new_module.write_text(
        f'SQL = "{update.format(assign="scan_status = \'clean\'")}"\n', encoding="utf-8"
    )
    registered_clean = tmp_path / "registered_clean.py"
    registered_clean.write_text(
        f'SQL = "{update.format(assign="storage_key = :k, scan_status = \'clean\'")}"\n',
        encoding="utf-8",
    )
    unregistered_pending = tmp_path / "other.py"
    unregistered_pending.write_text(
        f'SQL = "{update.format(assign="scan_status = \'pending\'")}"\n', encoding="utf-8"
    )
    registered_pending = tmp_path / "registered_ok.py"
    registered_pending.write_text(
        f'SQL = "{update.format(assign="scan_status = \'pending\'")}"\n', encoding="utf-8"
    )
    inserted = tmp_path / "inserted.py"
    inserted.write_text(
        'SQL = "insert into public.files (id, scan_status) values (:id, \'clean\')"\n',
        encoding="utf-8",
    )
    registry = {
        "registered_clean.py": frozenset({"'pending'"}),
        "registered_ok.py": frozenset({"'pending'"}),
    }
    violations = scan_status_violations(
        {
            "new_module.py": new_module,
            "registered_clean.py": registered_clean,
            "other.py": unregistered_pending,
            "registered_ok.py": registered_pending,
            "inserted.py": inserted,
        },
        registry,
    )
    assert len(violations) == 4, violations
    assert any(v.startswith("new_module.py assigns files.scan_status") for v in violations)
    assert any(v.startswith("registered_clean.py assigns") and "beyond" in v for v in violations)
    assert any(v.startswith("other.py assigns files.scan_status") for v in violations)
    assert any(v.startswith("inserted.py assigns files.scan_status") for v in violations)
    assert not any(v.startswith("registered_ok.py") for v in violations)


def test_the_platforms_unconditional_scan_writer_is_called_by_nothing() -> None:
    """`core/file_scan.py::record_scan` sets whatever status it is handed, with no guard.

    It is the legacy scanner seam, kept byte for byte for a product that wires a scanner of its own
    to it. No module of the product itself reaches it -- the router asks the release rule, not the
    seam -- so a verdict is only ever written by the scanner's transitions (with the capability) or
    by whatever the product registers deliberately (without it, as an entry in the registry above).
    """
    callers = []
    for path in _python_files():
        if path.name == "file_scan.py":
            continue
        for node in ast.walk(_tree(path)):
            named = (
                isinstance(node, ast.ImportFrom)
                and (
                    (node.module or "").endswith("file_scan")
                    or any(alias.name in {"file_scan", "record_scan"} for alias in node.names)
                )
            ) or (isinstance(node, ast.Name | ast.Attribute) and "record_scan" in ast.unparse(node))
            if named:
                callers.append(_rel(path))
                break
    assert callers == [], f"record_scan can set `clean` without a scan; callers: {callers}"


# -- 2. every object read or signed URL is accounted for -------------------------------------------

#: By mode: every call that signs a URL for, or reads, an object -- by file, with the number of
#: calls and why each is not a release of an uploaded file's content to a person. A new call fails
#: the test until it goes through the release rule or is added here with a reason. A file the
#: product was not generated with is not expected (an optional capability's, or the other mode's).
_READS_COMMON: dict[str, tuple[int, str]] = {
    "services/api/koras_api/routers/audit_exports.py": (
        1,
        "the product's own export, not an upload",
    ),
    "services/api/koras_api/routers/reporting_schedules.py": (
        1,
        "the product's own generated export, not an upload",
    ),
    "services/worker/koras_worker/tasks/storage_backup.py": (
        2,
        "custody: a copy between buckets is not a release",
    ),
    "services/worker/koras_worker/tasks/storage_restore.py": (
        1,
        "custody: reads the backup copy for restore, not a release",
    ),
}
_READS_SECURE: dict[str, tuple[int, str]] = {
    **_READS_COMMON,
    "services/api/koras_api/routers/files.py": (
        1,
        "download: signed only after require_releasable returned. Completion signs nothing and a "
        "hook is never handed a URL",
    ),
    "services/api/koras_api/core/file_release_gate.py": (
        1,
        "the gate itself: read_releasable asks the rule on the row, and reads the object only on a "
        "yes. The assistant's indexer is its one caller",
    ),
    "services/api/koras_api/core/imports.py": (
        1,
        "import source read, after check_source applies the release rule",
    ),
    "services/worker/koras_worker/scanning/s3.py": (1, "the scanner is the gate"),
}
_READS_LEGACY: dict[str, tuple[int, str]] = {
    **_READS_COMMON,
    "services/api/koras_api/routers/files.py": (
        2,
        "download behind the platform seam's rule (through core/file_release.py), and the one "
        "URL a hook is handed at upload completion -- the behaviour of a product without the "
        "capability, which the capability exists to replace",
    ),
    "services/api/koras_api/core/imports.py": (
        1,
        "import source read, after check_source applies its deny-list of scan states",
    ),
}


def _is_store_get(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "get"
        and (
            (isinstance(node.value, ast.Name) and node.value.id == "store")
            or (isinstance(node.value, ast.Attribute) and node.value.attr == "store")
        )
    )


def _reads(path: Path) -> int:
    """Calls that sign a URL for an object, or read one."""
    count = 0
    for node in ast.walk(_tree(path)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr in {
            "presign_download",
            "get_object",
            # Spelled directly on a client rather than through the store.
            "generate_presigned_url",
            "download_file",
            "download_fileobj",
        }:
            count += 1
        elif node.func.attr == "to_thread" and any(
            _is_store_get(argument) for argument in node.args
        ):
            # `asyncio.to_thread(store.get, key)` is a read that is not spelled as a call.
            count += 1
        elif (
            node.func.attr == "get"
            and (
                (isinstance(node.func.value, ast.Name) and node.func.value.id == "store")
                or (isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "store")
            )
            and not (
                node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "session"
            )
        ):
            count += 1
    return count


def test_every_object_read_or_signed_url_is_one_the_release_rule_has_accounted_for() -> None:
    found = {
        _rel(path): count for path in _python_files() if (count := _reads(path))
    }
    table = _READS_SECURE if SECURE_FILES else _READS_LEGACY
    expected = {name: count for name, (count, _why) in table.items() if (REPO / name).exists()}
    assert found == expected, (
        "an object read or signed URL appeared or disappeared; route it through "
        "core/file_release.py (or its gate) or account for it in this test with a reason"
    )


# -- 3. which modules can reach an object store ----------------------------------------------

_STORE_REACHING_COMMON: dict[str, str] = {
    "services/api/koras_api/core/storage.py": "builds the tenant's store; reads nothing itself",
    "services/api/koras_api/routers/files.py": "upload tickets; download behind the release rule",
    "services/api/koras_api/routers/audit_exports.py": "the product's own export, not an upload",
    "services/api/koras_api/routers/reporting.py": "writes the product's own report export",
    "services/api/koras_api/routers/reporting_schedules.py": "the product's own export",
    "services/worker/koras_worker/worker.py": "registers the tasks below; reads no object",
    "services/worker/koras_worker/tasks/storage_backup.py": "custody copy between buckets",
    "services/worker/koras_worker/tasks/storage_restore.py": "custody: restore writes pending",
    "services/worker/koras_worker/tasks/storage_lifecycle.py": "deletes expired objects only",
    "services/worker/koras_worker/tasks/storage_reconcile.py": "lists keys; reads no object",
    "services/worker/koras_worker/tasks/governance_expiry.py": "deletes expired objects only",
}
_STORE_REACHING_OPTIONAL: dict[str, str] = {
    "services/api/koras_api/core/ai.py": "the indexer's store; with the capability, read only "
    "through read_releasable",
    "services/api/koras_api/ai/tools.py": "safe_filename and the delete tool; reads no object",
    "services/api/koras_api/routers/imports.py": "import source, after the release rule",
    "services/worker/koras_worker/tasks/imports.py": "import source, after the release rule",
}
_STORE_REACHING_SECURE: dict[str, str] = {
    "services/worker/koras_worker/scanning/s3.py": "the scanner is the gate",
    "services/worker/koras_worker/tasks/scan.py": "settings for the scanner; reads nothing",
    "services/worker/koras_worker/tasks/finalize.py": "custody: the finalizer's store; no bytes",
    "services/worker/koras_worker/uploads/finalize.py": (
        "custody: copies an incoming object to a final key and reads no bytes"
    ),
}


def _reaches_a_store(path: Path) -> bool:
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "koras_storage" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = {alias.name for alias in node.names}
            if (
                module == "koras_storage"
                or module.endswith("core.storage")
                or (node.level > 0 and module == "storage")
                or module.endswith("storage_backup")
                or (module.endswith("core") and "storage" in names)
            ):
                return True
    return False


def test_the_modules_that_can_reach_an_object_store_are_the_ones_accounted_for() -> None:
    found = {_rel(path) for path in _python_files() if _reaches_a_store(path)}
    accounted = {**_STORE_REACHING_COMMON, **_STORE_REACHING_OPTIONAL}
    if SECURE_FILES:
        accounted.update(_STORE_REACHING_SECURE)
    expected = {name for name in accounted if (REPO / name).exists()}
    assert found == expected, (
        "a module that can hold an object store appeared or disappeared. A read or a signed URL "
        "must go through core/file_release.py (see the reads table above); add the module here "
        f"with its reason once that is true. Difference: {sorted(found ^ expected)}"
    )


# -- 4. what a response may name -------------------------------------------------------------------

_KEY_FIELDS = frozenset({"storage_key", "object_key", "backup_key", "source_key"})


def test_no_route_model_carries_an_object_key() -> None:
    """Any class in `routers/` -- whatever its base -- is part of what a client can see or send."""
    offenders = []
    for path in (API / "routers").rglob("*.py"):
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ClassDef):
                continue
            for statement in node.body:
                if (
                    isinstance(statement, ast.AnnAssign)
                    and isinstance(statement.target, ast.Name)
                    and statement.target.id in _KEY_FIELDS
                ):
                    offenders.append(f"{_rel(path)}::{node.name}.{statement.target.id}")
    assert offenders == [], f"an object key must not reach a client: {offenders}"


# -- 5. every consumer asks the one rule, and none keeps one of its own ----------------------

#: Identifiers that spell a rule of the platform seam's or of a product's own. With the
#: capability no consumer may use one; the seam (`file_scan.py`) and the rule's own legacy
#: constants are the only places they live.
_OWN_RULES = frozenset({"WITHHELD", "withheld", "UNPARSEABLE_SCANS"})


def test_no_consumer_keeps_a_rule_of_its_own_when_secure() -> None:
    offenders = [
        _rel(path)
        for path in _python_files()
        if path.name not in {"file_scan.py"} and _names(path) & _OWN_RULES
    ]
    if SECURE_FILES:
        assert not offenders, f"these modules use a release rule of their own: {sorted(offenders)}"
    else:
        # The legacy import gate keeps its deny-list; nothing else may name one.
        assert set(offenders) <= {"services/api/koras_api/core/imports.py"}, offenders


def test_the_download_route_asks_the_one_rule_in_either_mode() -> None:
    names = _names(_api("routers/files.py"))
    assert "withheld" not in names
    assert ("require_releasable" in names) is SECURE_FILES
    assert ("releasable" in names) is (not SECURE_FILES)


def test_every_consumer_that_reads_or_derives_content_names_the_rule() -> None:
    """Each consumer present in this product refers to the primitive or its gate, by name."""
    required = {
        "routers/files.py": (
            {"require_releasable", "row_releasable"} if SECURE_FILES else {"releasable"}
        ),
        "core/imports.py": {"releasable"} if SECURE_FILES else {"UNPARSEABLE_SCANS"},
        "core/ai.py": {"read_releasable", "RELEASABLE_SQL"},
        "core/knowledge.py": {"RELEASABLE_SQL"},
        "ai/tools.py": {"row_releasable"},
    }
    for name, identifiers in required.items():
        path = _api(name)
        if not path.exists():
            continue
        if not SECURE_FILES and name in {"core/ai.py", "core/knowledge.py", "ai/tools.py"}:
            # Without the capability the assistant's derived content was never gated.
            assert not _names(path) & {"read_releasable", "RELEASABLE_SQL", "row_releasable"}, name
            continue
        assert identifiers <= _names(path), (name, identifiers - _names(path))


# -- 6. file hooks: with the capability none is ever handed a way to read ----------------


def test_no_hook_is_handed_a_url_or_an_upload_when_secure() -> None:
    router = _names(_api("routers/files.py"))
    hooks = _names(_api("core/file_hooks.py"))
    if SECURE_FILES:
        assert "for_upload" not in router and "run_after_upload" not in router
        assert not hooks & {"after_upload", "for_upload", "run_after_upload"}
        assert {"after_clean", "for_clean", "run_after_clean", "due"} <= hooks
    else:
        assert {"for_upload", "run_after_upload"} <= router
        assert {"after_upload", "for_upload", "run_after_upload"} <= hooks
        assert not hooks & {"after_clean", "for_clean", "run_after_clean"}


def test_the_indexer_never_fetches_a_url_when_secure() -> None:
    ai = _api("core/ai.py")
    if not ai.exists():
        return  # no assistant in this product, so there is no indexer to guard
    source = ai.read_text(encoding="utf-8")
    functions = {
        node.name for node in ast.walk(_tree(ai)) if isinstance(node, ast.AsyncFunctionDef)
    }
    if SECURE_FILES:
        assert "httpx" not in source
        assert "presign_download" not in source
        assert {"index_clean_file", "_index_clean_file"} <= functions
        assert not functions & {"index_uploaded_file", "_index_uploaded_file"}
    else:
        assert {"index_uploaded_file", "_index_uploaded_file"} <= functions
        assert not functions & {"index_clean_file", "_index_clean_file"}


def test_no_file_chunk_is_written_except_through_the_guarded_writer_when_secure() -> None:
    """`index_document` is the unguarded one; only generic non-file sources may use it."""
    knowledge = API / "core" / "knowledge.py"
    if not knowledge.exists() or not SECURE_FILES:
        return
    for path in API.rglob("*.py"):
        if "__pycache__" in path.parts or path == knowledge:
            continue
        calls = {
            ast.unparse(node.func) for node in ast.walk(_tree(path)) if isinstance(node, ast.Call)
        }
        assert not any(call.endswith("index_document") for call in calls), path.name
    ai_calls = {
        ast.unparse(node.func)
        for node in ast.walk(_tree(API / "core" / "ai.py"))
        if isinstance(node, ast.Call)
    }
    assert any(call.endswith("index_file_document") for call in ai_calls)
