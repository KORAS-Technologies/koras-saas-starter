"""`file.scan`: scan one finalized file (ADR 0013, `secure_files`).

The handler is the thin edge of `scanning/runtime.py`. It validates the job,
builds the three things a run needs from this worker's own configuration -- a
database session, the platform default bucket and the configured scanner -- and
hands them over. **No security rule is decided here.**

**Three enqueuers and nothing else.** The upload finalizer (`tasks/finalize.py`, the moment a
file is on its final key), the reconciliation sweep (`tasks/scan_sweep.py`) and, in a product
with restore, the restore's own follow-up (`tasks/restore_scan.py`, for a file a restore has just
written) put a job on the queue, all through `core/scan_enqueue.py`; there is no admin trigger,
no API route and no other caller. A worker with the
backend `none` does not start in a product with the capability; and a job that somehow ran
with no scanner resolves one that answers `MISCONFIGURED` and records a hold: it cannot
release a file.

**What a job may carry.** `{"file_id": "<uuid>"}` on an envelope that names the
tenant, and nothing else. A payload with any other key, a file or tenant that is
not a canonical UUID, or an idempotency key that is not `scan:<file_id>` is
refused with no read and no write. The object key comes from the tenant's own
row and is validated against the tenant and file; no bucket, host, URL or
credential can arrive on the queue.

**The tenant is declared, not provisioning.** The run binds `app.tenant_id` and
leaves the provisioning flag off, as an import does. A job naming another
tenant's file finds no row.

**Retries.** The declaration says once (`koras_api/core/scan_jobs.py`). A
handler that raises is recorded by the queue as failed and the file stays
`pending`; the retry is the sweep's, with a back-off that caps at an hour. A job
the queue cancels (its timeout) records `scan_interrupted` first; see `runtime.py`.

**Configuration.** `FILE_SCAN_*` through `ScannerSettings`. The attempt threshold handed
to the transitions is `ScannerSettings.file_scan_max_attempts` read from this worker's
environment, the one place it is read; it must be the same on every worker, or
`scan_exhausted` can be written twice, or never, for one file.
"""

from __future__ import annotations

import importlib
import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from arq.constants import result_key_prefix
from koras_queue import BoundTask, JobEnvelope, job_id_for, queue_for
from koras_storage import StorageSettings
from pydantic_settings import SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from ..scanning import ObjectReader, ScannerSettings, resolve_scanner
from ..scanning.objects import ObjectIdentity, ObjectSource, ObjectSourceError, OpenedObject
from ..scanning.runtime import ScanRun, scan_file
from ..scanning.s3 import default_bucket_source
from ..settings import SweepSettings, settings

logger = logging.getLogger(__name__)


class ScanStorageSettings(SweepSettings):
    """The platform default bucket the worker already reads, for a scan's read only."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    storage_endpoint: str = ""
    storage_bucket: str = ""
    storage_region: str = "us-east-1"
    storage_access_key: str = ""
    storage_secret_key: str = ""


class _LazySource:
    """The default-bucket source, built on first use.

    A worker with no storage configured must still be able to *hold* a file, not
    crash on it. Construction failing is reported the way the store being
    unreachable is: as `ObjectSourceError`, which the reader turns into an
    `UNREACHABLE` admission and the run records as `object_unreachable`.
    """

    def __init__(self) -> None:
        self._source: ObjectSource | None = None
        self._lock = threading.Lock()

    def _built(self) -> ObjectSource:
        with self._lock:
            if self._source is None:
                try:
                    config = ScanStorageSettings()
                    self._source = default_bucket_source(
                        StorageSettings(
                            endpoint=config.storage_endpoint,
                            bucket=config.storage_bucket,
                            region=config.storage_region,
                            access_key=config.storage_access_key,
                            secret_key=config.storage_secret_key,
                        )
                    )
                except Exception as error:
                    raise ObjectSourceError("the object store is not configured") from error
            return self._source

    def stat(self, key: str) -> ObjectIdentity | None:
        return self._built().stat(key)

    def open(self, key: str) -> OpenedObject:
        return self._built().open(key)


def _engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )


def _canonical(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return value if str(uuid.UUID(value)) == value else None
    except ValueError:
        return None


def declaration() -> Any:  # noqa: ANN401 - a module, reached by name
    """The API's `file.scan` declaration, by name. Missing is an error, not a skip.

    Unlike the import task's registry, which degrades to a skipped job, a missing
    declaration here would leave a task name the worker's `functions` list could
    not bind; failing at import is what keeps that from being a silent no-op.
    """
    try:
        return importlib.import_module("koras_api.core.scan_jobs")
    except ImportError as error:
        raise RuntimeError("the file.scan declaration is not on this worker's path") from error


def bound() -> list[BoundTask]:
    return [BoundTask(declaration().FILE_SCAN, scan_file_task)]


def _enqueue_module() -> Any:  # noqa: ANN401 - a module, reached by name
    """The API's `scan_enqueue`, by name. Missing is an error, not a skip."""
    try:
        return importlib.import_module("koras_api.core.scan_enqueue")
    except ImportError as error:
        raise RuntimeError("the scan enqueue module is not on this worker's path") from error


async def hand_off_to_scanner(ctx: dict[str, Any], tenant_id: str, file_id: str) -> bool:
    """Put `file.scan` on the queue for a file that has just reached its final key.

    Called by the upload finalizer and by nothing else but the sweep's own enqueue. **It
    never raises and never changes the file**: a failed enqueue is logged by name only and
    the reconciliation sweep recovers the file, which stays `pending` (withheld) meanwhile.
    Returns whether a job is now queued (a duplicate of one already queued counts).
    """
    try:
        contract = declaration()
        redis = ctx.get("redis")
        if redis is not None:
            # A scan of this file that ran before has left a retained result under this job
            # id, and the queue refuses to enqueue an id it still holds a result for.
            key = contract.scan_idempotency_key(file_id)
            await redis.delete(result_key_prefix + job_id_for(contract.FILE_SCAN, tenant_id, key))
        queue = queue_for(str(settings.redis_url))
        try:
            queued = await _enqueue_module().enqueue_scan(
                queue, tenant_id=tenant_id, file_id=file_id
            )
        finally:
            await queue.aclose()
    except Exception as error:  # noqa: BLE001 - the file is final; the sweep recovers this
        logger.error(
            "file.scan hand-off failed for file %s of tenant %s (%s); the sweep will recover it",
            file_id,
            tenant_id,
            type(error).__name__,
        )
        return False
    return bool(queued is not None and not queued.simulated)


def _refused(reason: str) -> dict[str, Any]:
    logger.error("file.scan refused a job: %s", reason)
    return {"status": "refused", "reason": reason}


async def scan_file_task(ctx: dict[str, Any], envelope: JobEnvelope) -> dict[str, Any]:
    """Scan one file. Returns a small closed-vocabulary summary and no file content."""
    del ctx
    contract = declaration()
    tenant_id = _canonical(envelope.tenant_id)
    if tenant_id is None:
        return _refused("the tenant is not a canonical id")
    if set(envelope.payload) != {contract.PAYLOAD_KEY}:
        return _refused("the payload carries something other than a file id")
    file_id = _canonical(envelope.payload.get(contract.PAYLOAD_KEY))
    if file_id is None:
        return _refused("the file is not a canonical id")
    if envelope.idempotency_key and envelope.idempotency_key != contract.scan_idempotency_key(
        file_id
    ):
        return _refused("the job identity does not match its file")

    if not settings.database_url:
        logger.error("file.scan skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}

    config = ScannerSettings()
    scanner = resolve_scanner(config)
    reader = ObjectReader(_LazySource(), max_bytes=config.file_scan_max_bytes)

    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            run = await scan_file(
                session,
                tenant_id=tenant_id,
                file_id=file_id,
                reader=reader,
                scanner=scanner,
                max_attempts=config.file_scan_max_attempts,
                now=datetime.now(UTC),
            )
    finally:
        await engine.dispose()
    return _summary(run)


def _summary(run: ScanRun) -> dict[str, Any]:
    summary: dict[str, Any] = {"status": run.disposition.value}
    if run.failure is not None:
        summary["failure"] = run.failure.value
    if run.attempts is not None:
        summary["attempts"] = run.attempts
    if run.opens_at is not None:
        summary["opens_at"] = run.opens_at.isoformat()
    return summary
