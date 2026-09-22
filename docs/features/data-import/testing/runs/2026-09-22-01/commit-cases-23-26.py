"""F28 manual cases 23, 24, 25, 26 - the commit, against a real PostgreSQL.

Runs the product's own `commit_run` worker task: the real store, the real
state machine, the real target writer, one real transaction. The object store
is the only thing stubbed, and only because MinIO credentials are not the
property under test - the bytes it returns are a real CSV.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__)) + "/gen/f28probe"
for part in (
    "services/api",
    "services/worker",
    "python-packages/koras-import/src",
    "python-packages/koras-queue/src",
):
    sys.path.insert(0, os.path.join(ROOT, part))

DB = "postgresql+asyncpg://koras_e2e_app:koras_e2e_app@127.0.0.1:54323/f28probe"
os.environ["DATABASE_URL"] = DB
os.environ["ENVIRONMENT"] = "dev"
os.environ["ZITADEL_DOMAIN"] = "http://127.0.0.1:3212"
os.environ["ZITADEL_PROJECT_ID"] = "e2e-project"
# The worker requires one; the commit path never enqueues, so it is
# never connected to. Redis 6380 is the docoris stack, database 9.
os.environ["REDIS_URL"] = "redis://127.0.0.1:6380/9"

TENANT = "00000000-0000-4e2e-8000-000000000001"
SUBJECT = "e2e-owner"

CSV = (
    "Email,Name,Seats\n"
    "ann@example.test,Ann,3\n"
    "bo@example.test,Bo,1\n"
    "cy@example.test,Cy,7\n"
)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

AS_TENANT = text(
    "select set_config('app.provisioning', '', true), "
    "set_config('app.tenant_id', :tenant_id, true)"
)


async def seed_run(engine, *, run_id: str, file_id: str, operation: str) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_TENANT, {"tenant_id": TENANT})
        await s.execute(
            text(
                "insert into public.files (id, tenant_id, category, name, storage_key,"
                " size_bytes, content_type, status, scan_status, uploaded_by)"
                " values (cast(:id as uuid), cast(:t as uuid), 'imports', 'contacts.csv',"
                " :key, :size, 'text/csv', 'ready', 'clean', :by)"
            ),
            {
                "id": file_id,
                "t": TENANT,
                "key": "imports/" + file_id + ".csv",
                "size": len(CSV.encode()),
                "by": SUBJECT,
            },
        )
        await s.execute(
            text(
                "insert into public.import_runs (id, tenant_id, target, status, format,"
                " source_file_id, delimiter, encoding, columns, mapping, operation,"
                " rows_total, rows_valid, errors_total, requested_by, committed_by)"
                " values (cast(:id as uuid), cast(:t as uuid), 'probe.contacts',"
                " 'commit_requested', 'csv', cast(:f as uuid), ',', 'utf-8-sig',"
                " :cols, cast(:map as jsonb), :op, 3, 3, 0, :by, :by)"
            ),
            {
                "id": run_id,
                "t": TENANT,
                "f": file_id,
                "cols": ["Email", "Name", "Seats"],
                "map": '{"Email":"email","Name":"name","Seats":"seats"}',
                "op": operation,
                "by": SUBJECT,
            },
        )
        await s.commit()


async def counts(engine, run_id: str):
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_TENANT, {"tenant_id": TENANT})
        rows = (
            await s.execute(text("select count(*) from public.probe_contacts"))
        ).scalar_one()
        run = (
            await s.execute(
                text(
                    "select status, rows_valid, error from public.import_runs"
                    " where id = cast(:id as uuid)"
                ),
                {"id": run_id},
            )
        ).first()
        return rows, run


async def main() -> int:
    import koras_worker.tasks.imports as task_module
    from koras_queue import JobEnvelope

    class FakeStore:
        """The only stub: the bucket. Real bytes, real CSV."""

        async def get(self, key):
            return CSV.encode()

    task_module._object_store = lambda: FakeStore()

    engine = create_async_engine(DB)
    failures = []

    # case 23/24: a clean three-row file commits, and the rows land
    run_id, file_id = str(uuid.uuid4()), str(uuid.uuid4())
    await seed_run(engine, run_id=run_id, file_id=file_id, operation="skip_duplicate")
    before, _ = await counts(engine, run_id)
    result = await task_module.commit_run(
        {},
        JobEnvelope(
            task="import.commit",
            tenant_id=TENANT,
            payload={"run_id": run_id},
            actor_id=SUBJECT,
        ),
    )
    after, run = await counts(engine, run_id)
    print("CASE 23  worker returned", result)
    print("CASE 23  run status =", repr(run.status), " error =", repr(run.error))
    print("CASE 24  probe_contacts", before, "->", after)
    if run.status != "committed":
        failures.append("case 23: run is " + repr(run.status) + ", expected 'committed'")
    if after - before != 3:
        failures.append("case 24: " + str(after - before) + " rows written, expected 3")

    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        await s.execute(AS_TENANT, {"tenant_id": TENANT})
        attributed = (
            await s.execute(
                text(
                    "select count(*) from public.probe_contacts"
                    " where import_run_id = cast(:id as uuid)"
                ),
                {"id": run_id},
            )
        ).scalar_one()
    print("CASE 24  rows carrying the run id =", attributed)
    if attributed != 3:
        failures.append("case 24: " + str(attributed) + " rows carry the run id, expected 3")

    # case 25: the same run cannot be committed twice
    second = await task_module.commit_run(
        {},
        JobEnvelope(
            task="import.commit",
            tenant_id=TENANT,
            payload={"run_id": run_id},
            actor_id=SUBJECT,
        ),
    )
    again, _ = await counts(engine, run_id)
    print("CASE 25  second commit returned", second)
    print("CASE 25  probe_contacts after replay =", again)
    if again != after:
        failures.append("case 25: a replayed commit wrote " + str(again - after) + " more rows")

    # case 26: a writer that raises leaves zero rows and a failed run
    bad_id, bad_file = str(uuid.uuid4()), str(uuid.uuid4())
    await seed_run(engine, run_id=bad_id, file_id=bad_file, operation="skip_duplicate")
    import koras_api.imports.targets as targets

    original = targets.CONTACTS.writer

    async def explode(session, request):
        # Write two rows, then fail - the partial-write case the phase exists
        # for. Anything less would not test the transaction.
        await original(
            session,
            type(request)(
                tenant_id=request.tenant_id,
                run_id=request.run_id,
                operation=request.operation,
                match_keys=request.match_keys,
                rows=request.rows[:2],
            ),
        )
        raise RuntimeError("the writer fell over on row 3")

    object.__setattr__(targets.CONTACTS, "writer", explode)
    try:
        bad_result = await task_module.commit_run(
            {},
            JobEnvelope(
                task="import.commit",
                tenant_id=TENANT,
                payload={"run_id": bad_id},
                actor_id=SUBJECT,
            ),
        )
    finally:
        object.__setattr__(targets.CONTACTS, "writer", original)
    final, bad_run = await counts(engine, bad_id)
    print("CASE 26  worker returned", bad_result)
    print("CASE 26  run status =", repr(bad_run.status), " error =", repr(bad_run.error))
    print("CASE 26  probe_contacts", again, "->", final, " (must be unchanged)")
    if final != again:
        failures.append("case 26: " + str(final - again) + " rows survived a failed commit")
    if bad_run.status != "failed":
        failures.append("case 26: run is " + repr(bad_run.status) + ", expected 'failed'")

    await engine.dispose()
    print()
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("ALL FOUR CASES PASS")
    return 0


sys.exit(asyncio.run(main()))
