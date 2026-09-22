"""The dry run: read the file, check every row, write nothing.

**The first enqueued job in this product.** Everything else the worker does
either runs on a clock or is a sweep across every tenant; this is work a person
asked for and is waiting on, handed over by a request. That is what PLAT-F1
exists for, and this is its first caller.

Three properties it has to keep, and each is a line somewhere below.

**It writes nothing of the target table.** A run reaching `validated` has read
the file and stored counts and row errors, and touched no customer record. The
state machine is what enforces it — there is no edge from `validating` to
anything that writes.

**It runs as the tenant, not as provisioning.** Unlike every other task here,
this one belongs to one organisation, so it sets `app.tenant_id` for the
transaction and leaves the provisioning flag off. A sweep that reached every
tenant would be the wrong shape for work one customer asked for.

**A failure is a run somebody can find.** Anything that goes wrong becomes
`failed` with a safe sentence, because a job that dies silently leaves a run in
`validating` forever and a person watching a spinner.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from koras_import import (
    MappingRefused,
    Operation,
    ReadRefused,
    TargetRegistry,
    WriteRefused,
    WriteRequest,
    check_total,
    rows_from,
)
from koras_queue import BoundTask, JobEnvelope
from koras_storage import ObjectStore, S3ObjectStore, StorageSettings, resolve_destination
from pydantic_settings import SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from ..settings import SweepSettings, settings

logger = logging.getLogger(__name__)


class ImportSettings(SweepSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    storage_endpoint: str = ""
    storage_bucket: str = ""
    storage_region: str = "us-east-1"
    storage_access_key: str = ""
    storage_secret_key: str = ""


imports = ImportSettings()

_AS_TENANT = text(
    "select set_config('app.provisioning', '', true), "
    "set_config('app.tenant_id', :tenant_id, true)"
)


def _engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )


def _object_store() -> ObjectStore:
    """The platform's own default destination.

    A tenant on its own bucket is not read here, for the same reason the
    reconciliation sweep does not read one: the per-tenant policy lives behind
    the platform contract with the caller's token, and a worker has no token.
    A product whose customers hold their own buckets cannot import from them
    until that is solved, and this comment is where that is written down.
    """
    destination = resolve_destination(
        None,
        StorageSettings(
            endpoint=imports.storage_endpoint,
            bucket=imports.storage_bucket,
            region=imports.storage_region,
            access_key=imports.storage_access_key,
            secret_key=imports.storage_secret_key,
        ),
    )
    return S3ObjectStore(destination)


def _registry() -> TargetRegistry | None:
    """The product's import targets, from the API's own package.

    The worker does not depend on the API's distribution and must not, so the
    dependency check would rightly refuse a plain import. What the image
    carries is `koras_api/imports` alone, put on the path by the Dockerfile —
    the same arrangement the scheduled-report task uses for the report
    catalogue, and the same graceful failure when it is missing.
    """
    try:
        module = importlib.import_module("koras_api.imports")
    except ImportError:
        logger.error("import validation: the product's targets are not on this worker's path")
        return None
    registry = getattr(module, "registry", None)
    if not isinstance(registry, TargetRegistry):
        logger.error("import validation: koras_api.imports has no registry")
        return None
    return registry


def _run_store() -> Any | None:  # noqa: ANN401 - a module, reached by name
    """The API's own run store, by name rather than by import.

    **Not `from koras_api.core import imports`**, and the difference is
    load-bearing: the worker does not depend on the API's distribution and the
    declared-dependency test rightly refuses a plain import of it. What the
    image carries is two paths the Dockerfile copies, and `importlib` is how
    the scheduled-report task already reaches the one it needs.

    The alternative — reimplementing the run store here — would be two
    implementations of the same state machine, and the one that drifts would be
    the one nobody reads.
    """
    try:
        return importlib.import_module("koras_api.core.imports")
    except ImportError:
        logger.error("import validation: the run store is not on this worker's path")
        return None


async def validate_run(ctx: dict[str, Any], envelope: JobEnvelope) -> dict[str, Any]:
    """Check one run's file, and record what was wrong with it."""
    del ctx
    run_id = str(envelope.payload.get("run_id") or "")
    if not run_id:
        # A job with no subject. Not retried: it will be no better next time.
        logger.error("import validation: a job arrived with no run id")
        return {"status": "skipped", "reason": "no run"}

    if not settings.database_url:
        logger.error("import validation skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}

    registry = _registry()
    if registry is None:
        return {"status": "skipped", "reason": "no targets"}

    store = _run_store()
    if store is None:
        return {"status": "skipped", "reason": "no store"}

    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(_AS_TENANT, {"tenant_id": envelope.tenant_id})
            run = await store.get(session, run_id)
            if run is None:
                logger.error("import validation: run %s is not visible to its tenant", run_id)
                return {"status": "skipped", "reason": "no run"}

            try:
                target = registry.require(run.target)
            except KeyError:
                await store.fail(session, run, "this product no longer accepts that import")
                await session.commit()
                return {"status": "failed", "reason": "unknown target"}

            try:
                raw = await store.source_bytes(session, _object_store(), run.source_file_id)
                result = store.check(raw, target, run)
            except store.SourceRefused as refused:
                await store.fail(session, run, _sentence(str(refused)))
                await session.commit()
                return {"status": "failed", "reason": str(refused)}
            except (ReadRefused, MappingRefused) as refused:
                # The file or the mapping, not the data. A run that fails for
                # this reason goes back to being mapped by a person.
                await store.fail(session, run, str(refused)[:400])
                await session.commit()
                return {"status": "failed", "reason": "unreadable"}
            except Exception:
                logger.exception("import validation: run %s could not be checked", run_id)
                await store.fail(session, run, "the file could not be checked")
                await session.commit()
                return {"status": "failed", "reason": "error"}

            landed = await store.record_validation(
                session, run, tenant_id=envelope.tenant_id, result=result
            )
            await session.commit()
    finally:
        await engine.dispose()

    logger.info(
        "import validation: run %s is %s -- %d row(s), %d valid, %d error(s)",
        run_id,
        landed.value,
        result.rows,
        result.valid,
        len(result.errors),
    )
    return {
        "status": "ok",
        "run": run_id,
        "state": landed.value,
        "rows": result.rows,
        "valid": result.valid,
        "errors": len(result.errors),
    }


def _sentence(code: str) -> str:
    """A refusal a person can act on, from the code the store raised."""
    return {
        "import.source.missing": "the file this import was started against is gone",
        "import.source.not_ready": "the file was not finished uploading",
        "import.source.unscanned": (
            "the file has not been checked for malware, and an import will not "
            "read a file nobody has looked at"
        ),
    }.get(code, "the file could not be read")


async def commit_run(ctx: dict[str, Any], envelope: JobEnvelope) -> dict[str, Any]:
    """Write the rows a person confirmed -- all of them, or none of them.

    **The acceptance criterion is one sentence: a commit that raises on row 900
    of 1000 leaves zero rows.** Everything here is arranged around it.

    One transaction holds the writer's work *and* the run's own committed row.
    The second half matters as much as the first: a run marked committed whose
    rows rolled back claims an import that did not happen, and rows that landed
    under a run still `committing` can be committed again and go in twice.

    A failure is therefore recorded in a **second** transaction, opened after
    the first has rolled back -- the only arrangement where a failure is both
    recorded and leaves nothing behind. A failure written inside the transaction
    that failed rolls back with it, and the run sits in `committing` forever,
    indistinguishable from a worker that died.

    It runs as the tenant, like the dry run and unlike every sweep here: these
    are one organisation's records, and row-level security is what keeps it
    that way while somebody else's code runs.
    """
    del ctx
    run_id = str(envelope.payload.get("run_id") or "")
    if not run_id:
        logger.error("import commit: a job arrived with no run id")
        return {"status": "skipped", "reason": "no run"}

    if not settings.database_url:
        logger.error("import commit skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}

    registry = _registry()
    if registry is None:
        return {"status": "skipped", "reason": "no targets"}

    store = _run_store()
    if store is None:
        return {"status": "skipped", "reason": "no store"}

    engine = _engine()
    written: Any = None
    failure: str | None = None
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(_AS_TENANT, {"tenant_id": envelope.tenant_id})
            run = await store.get(session, run_id)
            if run is None:
                logger.error("import commit: run %s is not visible to its tenant", run_id)
                return {"status": "skipped", "reason": "no run"}

            try:
                target = registry.require(run.target)
            except KeyError:
                failure = "this product no longer accepts that import"
            else:
                if not target.committable:
                    # A target that can be checked and not written is legitimate
                    # -- it is what every target was before the commit existed.
                    # The route refuses one; this is the second gate, for a
                    # target that lost its writer between the two.
                    failure = "this import can be checked but not written"

            if failure is None:
                # **The run is claimed before anything is written, in its own
                # committed transaction.** `record_commit` moves
                # `committing -> committed`, and the machine has no edge from
                # `commit_requested` to `committed`: without this step the
                # writer's rows are rolled back on every run of every product,
                # which is what Phase 2 did from the day it shipped until
                # 2026-09-22. IMP2-01 in
                # `docs/features/data-import/phase-2-review.md`.
                #
                # Separate and committed rather than folded into the write
                # below, for two reasons that are not style. The page polls on
                # `committing`, so a run that reached it is a run somebody can
                # watch; and a failure needs a state it may legally leave, which
                # `commit_requested` is not for everything that can go wrong
                # here.
                try:
                    await store.begin_commit(session, run)
                    await session.commit()
                except Exception:
                    # A concurrent cancellation is the ordinary way here: the
                    # run left `commit_requested` between the enqueue and this
                    # statement. Nothing has been written and nothing is owed.
                    await session.rollback()
                    logger.exception("import commit: run %s could not be claimed", run_id)
                    return {"status": "skipped", "reason": "not claimable"}

                # **The tenant is declared again, and leaving it out hid the
                # run.** `_AS_TENANT` uses `set_config(..., true)`, which is
                # transaction-local: the commit above ended the transaction the
                # settings belonged to, so the next statement runs with no
                # tenant and row-level security matches nothing. The symptom is
                # not an error -- it is `store.get` answering `None` for a run
                # that is plainly there, which reads as "the run vanished".
                # Found by running this against a real PostgreSQL rather than
                # against the state machine alone.
                await session.execute(_AS_TENANT, {"tenant_id": envelope.tenant_id})

                # Re-read, because `Run` is a frozen snapshot and `_advance`
                # does not refresh it: `record_commit` below checks the state it
                # is given, not the state in the table.
                claimed = await store.get(session, run_id)
                if claimed is None:
                    logger.error("import commit: run %s vanished after it was claimed", run_id)
                    return {"status": "skipped", "reason": "no run"}
                run = claimed

                try:
                    written = await _write(session, store, target, run, envelope.tenant_id)
                    await store.record_commit(
                        session,
                        run,
                        created=written.created,
                        updated=written.updated,
                        skipped=written.skipped,
                    )
                    # The one commit: the product's rows and the run's own
                    # state, together or not at all.
                    await session.commit()
                except WriteRefused as refused:
                    await session.rollback()
                    failure = str(refused)[:400]
                except (ReadRefused, MappingRefused) as refused:
                    await session.rollback()
                    failure = str(refused)[:400]
                except store.SourceRefused as refused:
                    await session.rollback()
                    failure = _sentence(str(refused))
                except Exception:
                    await session.rollback()
                    logger.exception("import commit: run %s could not be written", run_id)
                    failure = "the records could not be written"

        if failure is not None:
            # A second transaction, after the first has rolled back.
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(_AS_TENANT, {"tenant_id": envelope.tenant_id})
                run = await store.get(session, run_id)
                if run is not None:
                    # **Guarded, and the guard is not belt-and-braces.** This
                    # raised for every failed commit until 2026-09-22, and
                    # because nothing caught it the exception escaped past the
                    # notification below: the run was stranded *and* silent. A
                    # recorded failure nobody is told about is the worse half.
                    try:
                        await store.fail(session, run, failure)
                        await session.commit()
                    except Exception:
                        await session.rollback()
                        logger.exception(
                            "import commit: run %s failed and the failure could not be "
                            "recorded; it stays in %s",
                            run_id,
                            run.status,
                        )

        # **A third transaction, and the last thing that happens.** A
        # notification must never be able to undo an import: by this point the
        # rows are either written and committed or rolled back, and nothing
        # below can change either. It runs on both paths -- a person who
        # confirmed an import that failed is the one who most needs telling.
        await _tell(engine, envelope.tenant_id, run_id, written, failure)
    finally:
        await engine.dispose()

    if failure is not None:
        logger.warning("import commit: run %s failed -- %s", run_id, failure)
        return {"status": "failed", "run": run_id, "reason": failure}

    logger.info(
        "import commit: run %s created %d, updated %d, skipped %d",
        run_id,
        written.created,
        written.updated,
        written.skipped,
    )
    return {
        "status": "ok",
        "run": run_id,
        "created": written.created,
        "updated": written.updated,
        "skipped": written.skipped,
    }


async def _write(
    session: Any,  # noqa: ANN401 - the caller's open session, passed to the product
    store: Any,  # noqa: ANN401 - a module, reached by name
    target: Any,  # noqa: ANN401 - a product's own target
    run: Any,  # noqa: ANN401 - the store's own row type
    tenant_id: str,
) -> Any:  # noqa: ANN401 - whatever the product's writer reported
    """Read the file again, check it again, and hand the rows to the product.

    **Read again rather than carried from the dry run.** The validation stored
    counts and errors, not rows; carrying a file's worth of parsed records
    between two jobs would mean either a queue payload the size of the upload or
    a second copy of the data in the database. Reading it again costs one fetch,
    and the file cannot have changed underneath: an object under a run is
    immutable, and the scan gate has already passed.
    """
    raw = await store.source_bytes(session, _object_store(), run.source_file_id)
    verdict, mapped = store.prepare(raw, target, run)
    if not verdict.ok:
        # The dry run said this was clean and this pass disagrees. Refused
        # rather than written around: the rows a person approved are not the
        # rows in front of us, and writing only the good ones is the partial
        # commit the requirements forbid.
        raise WriteRefused(
            f"{len(verdict.errors)} row(s) no longer pass validation; "
            "check the file again before committing it"
        )

    request = WriteRequest(
        tenant_id=tenant_id,
        run_id=run.id,
        operation=Operation(run.operation),
        match_keys=tuple(target.match_keys),
        rows=rows_from(mapped, ceiling=target.max_rows),
    )
    written = await target.writer(session, request)
    # Cheap, and it catches what a writer is most likely to get wrong: a filter
    # that skips rows without counting them, which would report a clean import
    # of fewer records than the file held.
    check_total(request, written)
    return written

async def _tell(
    engine: Any,  # noqa: ANN401 - the engine the commit used
    tenant_id: str,
    run_id: str,
    written: Any,  # noqa: ANN401 - whatever the product's writer reported, or None
    failure: str | None,
) -> None:
    """Tell whoever started and whoever confirmed the run that it is over.

    IMPORT-US-018. Swallows everything: a notification that cannot be raised
    must not turn a finished import into a failed job, and a retried job would
    write the rows again. The import is already committed when this runs, so
    there is nothing here worth retrying for.

    In-app only -- `core/import_notify` says why, and it is a property of the
    template rather than a decision taken here.
    """
    try:
        notify = importlib.import_module("koras_api.core.import_notify")
        dispatch = importlib.import_module("koras_api.core.dispatch")
    except Exception:
        logger.warning("import commit: the notice modules are not on this worker's path")
        return

    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(_AS_TENANT, {"tenant_id": tenant_id})
            store = _run_store()
            run = await store.get(session, run_id) if store else None
            if run is None:
                return
            audience = notify.audience_for(run.requested_by, run.committed_by)
            if audience is None:
                logger.info("import commit: run %s names nobody to tell", run_id)
                return
            outcome = notify.Outcome(
                created=getattr(written, "created", 0),
                updated=getattr(written, "updated", 0),
                skipped=getattr(written, "skipped", 0),
                # The run's own recorded sentence, not the local variable: the
                # `fail` above may have been refused by the state machine, and
                # the message must say what the run says.
                error=run.error if failure is not None else None,
            )
            await dispatch.dispatch(
                session,
                dispatch.Event(
                    kind=notify.IMPORT_FINISHED.key,
                    tenant_id=tenant_id,
                    audience=audience,
                    render=notify.finished_notice(outcome),
                ),
            )
            await session.commit()
    except Exception:
        logger.exception("import commit: run %s finished but could not be announced", run_id)

#: Bound here and spliced into the worker's function list.
#:
#: The declaration is in `koras_import`, not here: the API enqueues by it, and
#: a name declared in the worker would make the API import the worker.
def bound() -> list[BoundTask]:
    from koras_import import COMMIT_RUN, VALIDATE_RUN

    return [BoundTask(VALIDATE_RUN, validate_run), BoundTask(COMMIT_RUN, commit_run)]
