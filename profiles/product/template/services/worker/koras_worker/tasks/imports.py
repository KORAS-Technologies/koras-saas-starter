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

from koras_import import MappingRefused, ReadRefused, TargetRegistry
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


#: Bound here and spliced into the worker's function list.
#:
#: The declaration is in `koras_import`, not here: the API enqueues by it, and
#: a name declared in the worker would make the API import the worker.
def bound() -> list[BoundTask]:
    from koras_import import VALIDATE_RUN

    return [BoundTask(VALIDATE_RUN, validate_run)]
