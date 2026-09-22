"""F28: the report cursor (IMP2-05) and the target permission (IMP2-03).

Both against a real PostgreSQL. The cursor case is the one that cannot be
decided by reading: the defect was that the browser paged on a number from a
different scale than the route's, and whether that truncates or repeats depends
on where the table's identity sequence happens to be.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

ROOT = os.environ["PROBE_PRODUCT"]
for part in (
    "services/api",
    "services/worker",
    "python-packages/koras-import/src",
    "python-packages/koras-queue/src",
):
    sys.path.insert(0, os.path.join(ROOT, part))

DB = os.environ["PROBE_DB"]
os.environ["DATABASE_URL"] = DB
os.environ["ENVIRONMENT"] = "dev"
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6380/9")
os.environ.setdefault("ZITADEL_DOMAIN", "http://127.0.0.1:3212")
os.environ.setdefault("ZITADEL_PROJECT_ID", "e2e-project")

TENANT = "00000000-0000-4e2e-8000-000000000001"
SUBJECT = "e2e-owner"

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

AS_TENANT = text(
    "select set_config('app.provisioning', '', true), "
    "set_config('app.tenant_id', :tenant_id, true)"
)


async def seed_report(engine, *, problems: int, offset_rows: int) -> str:
    """A run with `problems` row errors, whose file row numbers start high.

    `offset_rows` is what makes this a real test rather than a coincidence: the
    defect only shows when the file's row numbers and the table's identity
    column are on different scales, which is every database that has ever run
    another import.
    """
    run_id, file_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_TENANT, {"tenant_id": TENANT})
        await s.execute(
            text(
                "insert into public.files (id, tenant_id, category, name, storage_key,"
                " size_bytes, content_type, status, scan_status, uploaded_by)"
                " values (cast(:id as uuid), cast(:t as uuid), 'imports', 'r.csv',"
                " :k, 10, 'text/csv', 'ready', 'clean', :by)"
            ),
            {"id": file_id, "t": TENANT, "k": f"imports/{file_id}.csv", "by": SUBJECT},
        )
        await s.execute(
            text(
                "insert into public.import_runs (id, tenant_id, target, status, format,"
                " source_file_id, columns, mapping, operation, rows_total, rows_valid,"
                " errors_total, requested_by)"
                " values (cast(:id as uuid), cast(:t as uuid), 'probe.contacts',"
                " 'validation_failed', 'csv', cast(:f as uuid), :cols,"
                " cast('{}' as jsonb), 'skip_duplicate', :n, 0, :n, :by)"
            ),
            {"id": run_id, "t": TENANT, "f": file_id, "cols": ["Email"],
             "n": problems, "by": SUBJECT},
        )
        for i in range(problems):
            await s.execute(
                text(
                    "insert into public.import_row_errors"
                    " (run_id, tenant_id, row_number, column_name, field, code, value)"
                    " values (cast(:r as uuid), cast(:t as uuid), :row, 'Email',"
                    " 'email', 'import.error.email', :v)"
                ),
                {"r": run_id, "t": TENANT, "row": offset_rows + i, "v": f"bad{i}"},
            )
        await s.commit()
    return run_id


async def page_like_the_browser(engine, run_id: str, *, cursor_field: str, limit: int):
    """Exactly what `allErrors` does, with the cursor field swapped.

    `cursor` is the fix; `row` is what shipped. Running both against the same
    data is the only way to show the difference is real rather than theoretical.
    """
    import koras_api.core.imports as store

    collected: list = []
    after = 0
    guard = 0
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_TENANT, {"tenant_id": TENANT})
        while True:
            guard += 1
            if guard > 200:
                return collected, "LOOPED"
            page = await store.errors(s, run_id, limit=limit, after=after)
            collected.extend(page)
            if len(page) < limit:
                break
            last = page[-1]
            nxt = last.cursor if cursor_field == "cursor" else last.problem.row
            if nxt <= after:
                break
            after = nxt
    return collected, "ok"


async def main() -> int:
    engine = create_async_engine(DB)
    failures = []

    # ── IMP2-05: the report download must contain every problem, once ────────
    # Row numbers start at 10_000: a file whose bad rows are late in it, which
    # is ordinary, and which puts them far ahead of the table's own ids.
    run_id = await seed_report(engine, problems=620, offset_rows=10_000)

    fixed, status_fixed = await page_like_the_browser(
        engine, run_id, cursor_field="cursor", limit=500
    )
    shipped, status_shipped = await page_like_the_browser(
        engine, run_id, cursor_field="row", limit=500
    )

    rows_fixed = [r.problem.row for r in fixed]
    rows_shipped = [r.problem.row for r in shipped]
    print("CASE 36  problems recorded              : 620")
    print(f"CASE 36  paging on `cursor` (the fix)   : {len(fixed)} rows, "
          f"{len(set(rows_fixed))} distinct  [{status_fixed}]")
    print(f"CASE 36  paging on `row`    (as shipped): {len(shipped)} rows, "
          f"{len(set(rows_shipped))} distinct  [{status_shipped}]")

    if len(fixed) != 620 or len(set(rows_fixed)) != 620:
        failures.append(
            f"case 36: the fix returned {len(fixed)} rows "
            f"({len(set(rows_fixed))} distinct), expected 620 of each"
        )
    if len(shipped) == 620 and len(set(rows_shipped)) == 620:
        failures.append(
            "case 36: paging on `row` also returned every problem, so this "
            "database does not reproduce the defect and the comparison proves "
            "nothing"
        )
    # In file order, and every row present exactly once.
    if rows_fixed != sorted(rows_fixed):
        failures.append("case 36: the report is not in file order")

    # ── IMP2-03: the target's own permission ─────────────────────────────────
    from koras_api.routers.imports import _require_target
    from koras_import import FieldKind, FieldSpec, ImportTarget

    gated = ImportTarget(
        key="probe.payroll",
        label_key="k",
        permission="payroll.manage",
        fields=(FieldSpec("email", "k", kind=FieldKind.EMAIL, required=True),),
        match_keys=("email",),
    )

    class Claims:
        def __init__(self, roles):
            self.roles = roles

    refused = None
    try:
        _require_target(Claims(["member"]), gated)
    except Exception as exc:  # noqa: BLE001
        refused = exc
    print(f"CASE 39  a member without payroll.manage: "
          f"{'refused' if refused is not None else 'ALLOWED'}")
    if refused is None:
        failures.append("case 39: a caller without the target's permission was allowed")
    status = getattr(refused, "status_code", None)
    if status != 403:
        failures.append(f"case 39: refused with {status}, expected 403")

    # The positive half needs a permission the product's catalogue actually
    # grants, or it proves only that an invented one is held by nobody.
    held = ImportTarget(
        key="probe.ordinary",
        label_key="k",
        permission="imports.manage",
        fields=(FieldSpec("email", "k", kind=FieldKind.EMAIL, required=True),),
        match_keys=("email",),
    )
    allowed = True
    try:
        _require_target(Claims(["organization_owner"]), held)
    except Exception:  # noqa: BLE001
        allowed = False
    print(f"CASE 39  an organization_owner holding it: "
          f"{'allowed' if allowed else 'REFUSED'}")
    if not allowed:
        failures.append("case 39: an owner holding the permission was refused")

    await engine.dispose()
    print()
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("BOTH CASES PASS")
    return 0


sys.exit(asyncio.run(main()))
