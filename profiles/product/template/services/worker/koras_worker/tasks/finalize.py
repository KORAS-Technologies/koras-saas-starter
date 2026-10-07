"""`file.finalize`: copy a confirmed upload to a key no ticket was signed for, and verify it.

The handler is the thin edge of `uploads/finalize.py`, which holds every rule. This
module validates the job, builds what a run needs from this worker's own configuration (a
database session and the platform's default bucket), counts the attempt, hands the run to
`UploadFinalizer`, and records a hold when the finalizer refuses. **No security rule is
decided here** (ADR 0013, `secure_files`).

**Two callers and nothing else.** Upload confirmation puts a job on the queue
(`koras_api/core/finalize_enqueue.py`, deferred to the end of the upload window), and the
sweep below runs the same function for any upload whose job was lost, never ran or failed
for a reason that can pass. There is no admin trigger.

**What a job may carry.** `{"file_id": "<uuid>"}` on an envelope that names the tenant, and
nothing else. A payload with any other key, a file or tenant that is not a canonical UUID, or
an idempotency key that is not `finalize:<file_id>` is refused with no read and no write. The
object key comes from the tenant's own row and is validated against the tenant and file; no
bucket, host, URL or credential can arrive on the queue.

**The tenant is declared, not provisioning.** A run binds `app.tenant_id` and leaves the
provisioning flag off, so a job naming another tenant's file finds no row. Only the sweep's
*selection* reads across tenants, on the provisioning context, and it reads ids and nothing
else; every file it finds is then finalized as its own tenant.

**What stays true when this does not run.** Nothing here makes a file releasable. A file
whose finalizer never ran, failed, or was cancelled is still on its incoming key, which a
client can write and nothing may serve, and it still carries `scan_status = 'pending'`.
That is the fail-closed state: the absence of a worker is an upload that never becomes
available, never an unverified one that does.

**The hand-off to the scanner.** A file that is final -- finalized by this run, or found
already final -- is put on the scan queue (`tasks/scan.py::hand_off_to_scanner`), after the
swap has committed and never before. It is best effort and changes nothing about the file:
a lost hand-off leaves the file `pending` on a final key, which is exactly what the scan
sweep selects. The finalizer still decides nothing about the content.

**Holds.** A finalization the finalizer refuses is recorded on the file as a closed
`scan_failure` word (migration 00039) with one `storage.upload.held` audit event when the
word is new or changed, so an outage is one event however many attempts it spans. The file
stays `pending` and on its incoming key. `integrity_mismatch` is final: the bytes are not
the claim, nothing about a retry changes that, and the sweep does not select it. Every other
reason is retried by the sweep after a back-off, up to a bounded number of attempts, and
then waits for a person.

**Configuration.** The object store is the product's default bucket (`STORAGE_*`, the same
four settings the API signs against). `FILE_FINALIZE_SWEEP_BATCH`, `FILE_FINALIZE_RETRY_SECONDS`
and `FILE_FINALIZE_MAX_ATTEMPTS` bound how much one sweep does and how patient it is; they
tune throughput and patience, and none of them can make a file releasable that the finalizer
refused.
"""

from __future__ import annotations

import importlib
import logging
import threading
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from koras_queue import BoundTask, JobEnvelope
from koras_storage import S3ObjectStore, StorageSettings, resolve_destination
from pydantic import Field
from pydantic_settings import SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from ..settings import SweepSettings, settings
from ..uploads._audit import emit_and_commit
from ..uploads.finalize import (
    Finalization,
    FinalizeFailure,
    FinalizeKind,
    FinalizeStoreUnavailable,
    UploadFinalizer,
)

logger = logging.getLogger(__name__)

#: The ceiling of `files.scan_attempts` (a smallint). The counter saturates here.
_MAX_RECORDED_ATTEMPTS = 32767

#: Where this module records that a finalization was refused, and under what action.
HELD_ACTION = "storage.upload.held"


class FinalizeSettings(SweepSettings):
    """The default bucket the worker already reads, and how patient the sweep is."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    storage_endpoint: str = ""
    storage_bucket: str = ""
    storage_region: str = "us-east-1"
    storage_access_key: str = ""
    storage_secret_key: str = ""

    #: How many files one sweep run takes. A run is bounded so a backlog is worked
    #: through over several runs rather than holding the worker for one long one.
    file_finalize_sweep_batch: int = Field(default=25, ge=1, le=500)
    #: Seconds a file whose last attempt failed for a reason that can pass is left
    #: alone before the sweep tries it again.
    file_finalize_retry_seconds: int = Field(default=900, ge=60, le=86_400)
    #: Attempts after which a file waits for a person instead of being retried.
    file_finalize_max_attempts: int = Field(default=8, ge=1, le=100)


class _LazyFinalizeStore:
    """The platform default bucket, with the five calls finalization makes, built on first use.

    A worker with no object store configured must still be able to *hold* a file rather than
    crash on it: construction failing is reported as `FinalizeStoreUnavailable`. It never
    signs a URL, and it is the only thing in this process that copies and deletes.
    """

    def __init__(self) -> None:
        self._store: S3ObjectStore | None = None
        self._lock = threading.Lock()

    def _built(self) -> S3ObjectStore:
        with self._lock:
            if self._store is None:
                try:
                    config = FinalizeSettings()
                    self._store = S3ObjectStore(
                        resolve_destination(
                            None,
                            StorageSettings(
                                endpoint=config.storage_endpoint,
                                bucket=config.storage_bucket,
                                region=config.storage_region,
                                access_key=config.storage_access_key,
                                secret_key=config.storage_secret_key,
                            ),
                        )
                    )
                except Exception as error:
                    raise FinalizeStoreUnavailable("the object store is not configured") from error
            return self._store

    def head(self, key: str) -> int | None:
        return self._built().head(key)

    def copy(self, source_key: str, dest_key: str) -> None:
        self._built().copy(source_key, dest_key)

    def delete(self, key: str) -> None:
        self._built().delete(key)

    def provenance(self, key: str) -> str | None:
        return self._built().provenance(key)

    def sha256(self, key: str) -> str | None:
        return self._built().sha256(key)


_AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)
_AS_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")

#: Count one attempt, before anything is read, so a crash still counts it. Saturates, never wraps.
_ATTEMPT = text(
    "update public.files "
    "set scan_attempts = least(scan_attempts + 1, :ceiling), scan_attempted_at = :now "
    "where id = cast(:file_id as uuid) and tenant_id = cast(:tenant_id as uuid) "
    "and status = 'ready' and scan_status = 'pending' "
    "returning scan_attempts"
)
#: The ticket's issue time, read before an attempt is counted: a file whose window has not
#: closed is deferred, and a deferral is not an attempt.
_PEEK = text(
    "select created_at from public.files "
    "where id = cast(:file_id as uuid) and tenant_id = cast(:tenant_id as uuid) "
    "and status = 'ready' and scan_status = 'pending'"
)
_LOCK = text(
    "select scan_attempts, scan_failure from public.files "
    "where id = cast(:file_id as uuid) and tenant_id = cast(:tenant_id as uuid) "
    "and status = 'ready' and scan_status = 'pending' "
    "for update"
)
_FAILURE = text(
    "update public.files set scan_failure = :failure "
    "where id = cast(:file_id as uuid) and tenant_id = cast(:tenant_id as uuid) "
    "and status = 'ready' and scan_status = 'pending'"
)
#: The file is final, so a reason it was once held for finalization no longer applies. Only
#: the finalization words are cleared, never one a scanner wrote.
_CLEAR = text(
    "update public.files set scan_failure = null "
    "where id = cast(:file_id as uuid) and tenant_id = cast(:tenant_id as uuid) "
    "and status = 'ready' and scan_status = 'pending' "
    "and scan_failure = any(cast(:words as text[])) "
    "and position('/incoming/' in storage_key) = 0"
)
#: Files that are confirmed, unverified and still on a key a client could write, whose
#: finalization is due. Ids only: the finalizer re-reads everything it uses, as the tenant.
_DUE = text(
    "select id, tenant_id from public.files "
    "where status = 'ready' and scan_status = 'pending' "
    "and position('/incoming/' in storage_key) > 0 "
    "and created_at <= :due_before "
    "and scan_attempts < :max_attempts "
    "and (scan_failure is null or "
    "     (scan_failure <> 'integrity_mismatch' "
    "      and (scan_attempted_at is null or scan_attempted_at <= :retry_before))) "
    "order by created_at, id "
    "limit :batch"
)

_FINALIZE_WORDS = [failure.value for failure in FinalizeFailure]


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
    """The API's `file.finalize` declaration, by name. Missing is an error, not a skip.

    A missing declaration would leave a task name the worker's `functions` list could not
    bind; failing at import is what keeps that from being a silent no-op.
    """
    try:
        return importlib.import_module("koras_api.core.finalize_jobs")
    except ImportError as error:
        raise RuntimeError("the file.finalize declaration is not on this worker's path") from error


def bound() -> list[BoundTask]:
    return [BoundTask(declaration().FILE_FINALIZE, finalize_file_task)]


def _refused(reason: str) -> dict[str, Any]:
    logger.error("file.finalize refused a job: %s", reason)
    return {"status": "refused", "reason": reason}


def _window() -> Any:  # noqa: ANN401 - a module, reached by name
    """The API's shared upload-window module. Missing means nothing may be finalized."""
    try:
        return importlib.import_module("koras_api.core.upload_window")
    except ImportError as error:
        raise FinalizeStoreUnavailable(
            "the shared upload-window module is not on this worker's path"
        ) from error


async def _peek(
    session: Any,  # noqa: ANN401 - an open session with no uncommitted work
    tenant_id: str,
    file_id: str,
) -> datetime | None:
    """When this file's ticket was issued, or `None` when it is not ready and pending."""
    try:
        await session.execute(_AS_TENANT, {"tenant_id": tenant_id})
        found = (
            await session.execute(_PEEK, {"tenant_id": tenant_id, "file_id": file_id})
        ).first()
        await session.rollback()
    except BaseException:
        await session.rollback()
        raise
    return None if found is None else found[0]


async def _count_attempt(
    session: Any,  # noqa: ANN401 - an open session with no uncommitted work
    tenant_id: str,
    file_id: str,
    now: datetime,
) -> int | None:
    """Count one attempt and commit it. `None` when the file is no longer eligible."""
    try:
        await session.execute(_AS_TENANT, {"tenant_id": tenant_id})
        found = (
            await session.execute(
                _ATTEMPT,
                {
                    "tenant_id": tenant_id,
                    "file_id": file_id,
                    "ceiling": _MAX_RECORDED_ATTEMPTS,
                    "now": now,
                },
            )
        ).first()
        if found is None:
            await session.rollback()
            return None
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    return int(found[0])


async def _record_hold(
    session: Any,  # noqa: ANN401
    tenant_id: str,
    file_id: str,
    failure: FinalizeFailure,
) -> None:
    """Record why a file was not finalized. The file stays `pending` on its incoming key.

    One audit event, written in the same transaction as the word, and only when the word is
    new or different from the one the file already carries.
    """
    try:
        await session.execute(_AS_TENANT, {"tenant_id": tenant_id})
        row = (
            (await session.execute(_LOCK, {"tenant_id": tenant_id, "file_id": file_id}))
            .mappings()
            .first()
        )
        if row is None or row["scan_failure"] == failure.value:
            await session.rollback()
            return
        await session.execute(
            _FAILURE, {"tenant_id": tenant_id, "file_id": file_id, "failure": failure.value}
        )
        await emit_and_commit(
            session,
            tenant_id=tenant_id,
            action=HELD_ACTION,
            file_id=file_id,
            outcome="failed",
            reason=failure.value,
        )
    except BaseException:
        await session.rollback()
        raise


async def _clear_hold(
    session: Any,  # noqa: ANN401
    tenant_id: str,
    file_id: str,
) -> None:
    """Best effort: a stale finalization word on a file that is final is noise, not danger."""
    try:
        await session.execute(_AS_TENANT, {"tenant_id": tenant_id})
        await session.execute(
            _CLEAR, {"tenant_id": tenant_id, "file_id": file_id, "words": _FINALIZE_WORDS}
        )
        await session.commit()
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        logger.warning(
            "finalize: file %s is final but its old hold was not cleared (%s)",
            file_id,
            type(error).__name__,
        )


async def finalize_one(
    session: Any,  # noqa: ANN401 - the caller's session, with no uncommitted work
    finalizer: UploadFinalizer,
    *,
    tenant_id: str,
    file_id: str,
    now: datetime,
    max_attempts: int,
    on_final: Callable[[str, str], Awaitable[object]] | None = None,
) -> dict[str, Any]:
    """Run one finalization attempt for one file and return a closed-vocabulary summary.

    `on_final(tenant_id, file_id)` is called once the file is on its final key (finalized now,
    or found already final): it is the hand-off to the scanner. It is awaited and its answer
    is ignored, and an exception from it is logged and swallowed, because a lost hand-off
    leaves the file `pending` and the scan sweep recovers it. It runs after the swap and the
    hold's clearing have committed, never before.
    """
    issued = await _peek(session, tenant_id, file_id)
    if issued is None:
        return {"status": FinalizeKind.NOT_ELIGIBLE.value}
    opens_at = _window().earliest_finalization(issued)
    if now < opens_at:
        return {"status": FinalizeKind.POSTPONED.value, "opens_at": opens_at.isoformat()}
    attempts = await _count_attempt(session, tenant_id, file_id, now)
    if attempts is None:
        return {"status": FinalizeKind.NOT_ELIGIBLE.value}
    if attempts > max_attempts:
        # Past what the sweep is willing to retry: it waits for a person. Counted, so the
        # number a person reads is the number of times anything looked.
        return {"status": "exhausted", "attempts": attempts}
    outcome: Finalization = await finalizer.finalize(
        session, tenant_id=tenant_id, file_id=file_id, now=now
    )
    summary: dict[str, Any] = {"status": outcome.kind.value, "attempts": attempts}
    if outcome.kind is FinalizeKind.HELD:
        failure = outcome.failure or FinalizeFailure.OBJECT_UNREACHABLE
        await _record_hold(session, tenant_id, file_id, failure)
        summary["failure"] = failure.value
    elif outcome.kind in (FinalizeKind.FINALIZED, FinalizeKind.ALREADY_FINAL):
        await _clear_hold(session, tenant_id, file_id)
        if on_final is not None:
            try:
                await on_final(tenant_id, file_id)
            except Exception as error:  # noqa: BLE001 - never turns a finalized file into a failure
                logger.error(
                    "finalize: the scanner hand-off for file %s raised %s; the sweep recovers it",
                    file_id,
                    type(error).__name__,
                )
    elif outcome.kind is FinalizeKind.POSTPONED and outcome.opens_at is not None:
        summary["opens_at"] = outcome.opens_at.isoformat()
    return summary


async def finalize_file_task(ctx: dict[str, Any], envelope: JobEnvelope) -> dict[str, Any]:
    """Finalize one file. Returns a small closed-vocabulary summary and no file content."""
    contract = declaration()
    tenant_id = _canonical(envelope.tenant_id)
    if tenant_id is None:
        return _refused("the tenant is not a canonical id")
    if set(envelope.payload) != {contract.PAYLOAD_KEY}:
        return _refused("the payload carries something other than a file id")
    file_id = _canonical(envelope.payload.get(contract.PAYLOAD_KEY))
    if file_id is None:
        return _refused("the file is not a canonical id")
    if envelope.idempotency_key and envelope.idempotency_key != contract.finalize_idempotency_key(
        file_id
    ):
        return _refused("the job identity does not match its file")

    if not settings.database_url:
        logger.error("file.finalize skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}

    config = FinalizeSettings()
    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await finalize_one(
                session,
                UploadFinalizer(_LazyFinalizeStore()),
                tenant_id=tenant_id,
                file_id=file_id,
                now=datetime.now(UTC),
                max_attempts=config.file_finalize_max_attempts,
                on_final=_hand_off(ctx),
            )
    finally:
        await engine.dispose()


def _hand_off(ctx: dict[str, Any]) -> Callable[[str, str], Awaitable[object]]:
    """The scanner hand-off, bound to this worker's context. Imported when first needed."""

    async def hand_off(tenant_id: str, file_id: str) -> object:
        from .scan import hand_off_to_scanner

        return await hand_off_to_scanner(ctx, tenant_id, file_id)

    return hand_off


async def sweep_finalize(ctx: dict[str, Any]) -> dict[str, Any]:
    """Finalize what no job did: lost enqueues, a worker that was down, a failure that passed.

    Selects ids across tenants on the provisioning context and finalizes each as its own
    tenant. A file the finalizer refuses is recorded and left; nothing here ever releases
    anything. Skips, and says so, with no database.
    """
    if not settings.database_url:
        logger.info("file.finalize sweep skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}

    config = FinalizeSettings()
    now = datetime.now(UTC)
    due_before = now - timedelta(seconds=_window().FINALIZE_DELAY_SECONDS)
    retry_before = now - timedelta(seconds=config.file_finalize_retry_seconds)

    engine = _engine()
    summary: dict[str, int] = {}
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            try:
                await session.execute(_AS_PROVISIONING)
                due = (
                    (
                        await session.execute(
                            _DUE,
                            {
                                "due_before": due_before,
                                "retry_before": retry_before,
                                "max_attempts": config.file_finalize_max_attempts,
                                "batch": config.file_finalize_sweep_batch,
                            },
                        )
                    )
                    .mappings()
                    .all()
                )
                await session.rollback()
            except BaseException:
                await session.rollback()
                raise
            finalizer = UploadFinalizer(_LazyFinalizeStore())
            for row in due:
                try:
                    one = await finalize_one(
                        session,
                        finalizer,
                        tenant_id=str(row["tenant_id"]),
                        file_id=str(row["id"]),
                        now=datetime.now(UTC),
                        max_attempts=config.file_finalize_max_attempts,
                        on_final=_hand_off(ctx),
                    )
                except Exception as error:  # noqa: BLE001 - one file never stops the others
                    await session.rollback()
                    logger.error("file.finalize sweep: one file failed (%s)", type(error).__name__)
                    one = {"status": "error"}
                summary[one["status"]] = summary.get(one["status"], 0) + 1
    finally:
        await engine.dispose()
    return {"status": "ran", "considered": sum(summary.values()), "outcomes": summary}
