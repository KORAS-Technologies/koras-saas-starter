"""Load a generated product's `core/file_release.py` without importing the product.

`file_release.py` is standard library only on purpose (the worker image carries it), so it
can be loaded from its path beside the generated `core/secure_files.py` under a stub package,
with no dependency of the product installed.

    release_rule.py sql  <secure product>
        print the secure product's RELEASABLE_SQL (the statement spelling of the rule)

    release_rule.py rows <secure product> <default product> <database>
        evaluate BOTH products' `releasable()` against every row of `public.files` of
        <database> (the upgraded legacy rows) and assert:
          * the secure rule releases none of them, whatever their stored verdict;
          * the default product's rule answers exactly as the legacy rule always did.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from typing import Any


def load(product: str, alias: str) -> Any:
    core = Path(product) / "services" / "api" / "koras_api" / "core"
    package = types.ModuleType(alias)
    package.__path__ = [str(core)]
    sys.modules[alias] = package
    spec = importlib.util.spec_from_file_location(f"{alias}.file_release", core / "file_release.py")
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {core / 'file_release.py'}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def rows(database: str) -> list[dict[str, str]]:
    out = subprocess.run(  # noqa: S603
        [
            "psql", "-X", "-v", "ON_ERROR_STOP=1", "-q", "-tA", "-F", "|", "-d", database, "-c",
            "select id, tenant_id, status, scan_status, storage_key, coalesce(scan_object_etag, '') "
            "from public.files order by id",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    names = ("id", "tenant_id", "status", "scan_status", "storage_key", "etag")
    return [dict(zip(names, line.split("|"), strict=True)) for line in out.splitlines() if line]


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "sql":
        secure = load(argv[2], "secure_core")
        print(secure.RELEASABLE_SQL)
        return 0
    if len(argv) != 5 or argv[1] != "rows":
        print(__doc__)
        return 2
    secure, legacy = load(argv[2], "secure_core"), load(argv[3], "default_core")
    failures: list[str] = []
    if secure.SECURE_FILES is not True:
        failures.append("the secure product's SECURE_FILES is not True")
    if legacy.SECURE_FILES is not False:
        failures.append("the default product's SECURE_FILES is not False")
    legacy_refused = {"download": {"infected"}, "import": {"pending", "skipped", "infected"}}
    seen = rows(argv[4])
    if not seen:
        failures.append("no upgraded rows to evaluate")
    for row in seen:
        for consumer in ("download", "import", "indexing", "listing"):
            released = secure.releasable(
                status=row["status"],
                scan_status=row["scan_status"],
                consumer=consumer,
                tenant_id=row["tenant_id"],
                row_tenant_id=row["tenant_id"],
                storage_key=row["storage_key"],
                scan_object_etag=row["etag"] or None,
            )
            if released:
                failures.append(f"secure rule releases {row['id']} ({row['scan_status']}) to {consumer}")
            expected = row["scan_status"] not in legacy_refused.get(consumer, legacy_refused["download"])
            got = legacy.releasable(
                status=row["status"], scan_status=row["scan_status"], consumer=consumer
            )
            if got is not expected:
                failures.append(f"legacy rule changed for {row['scan_status']} / {consumer}")
    for failure in failures:
        print(f"::error::{failure}")
    if not failures:
        print(
            f"  ok    C: the secure rule releases none of {len(seen)} upgraded rows to any consumer;"
            " the default product's rule answers as it always did"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
