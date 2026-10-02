"""Running an approved restore: read the copy, check it, then write it.

**The route approves; this runs.** A person approving a restore does not wait
for a bucket, and a request that was approved and then lost to a crashed process
is a row somebody can find rather than an approval that evaporated. The sweep
picks up anything `approved`, which makes the approval durable and the execution
retryable without either being a special case.

**It verifies before it writes, and that is the whole reason this is safe.** The
bytes are hashed here, and compared with the digest the backup run recorded. A
copy that does not match is a failure -- the object stays gone, which is
recoverable, rather than being replaced by something that is not it, which is
not. Where no digest was ever recorded the restore still runs, because refusing
would mean refusing the only copy of an object whose provider never computed
one, and the audit row says plainly that nothing was compared.

**Non-overwriting by default.** A restore writes a new object under a new file
id and destroys nothing. Overwriting is a separate decision taken twice, at the
request and at the approval, and only then does this reuse the original key.

**One object in hand at a time, and never beside an import.** Since GR-352E
each request is run inside the worker's heavy gate -- `koras_worker/heavy.py`
-- and the gate is taken *before the request is claimed*. A restore that is
waiting for an import to finish is therefore still `approved`: if the queue
cancels the sweep while it waits, or the worker is replaced, the request is
exactly where the next pass looks for it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any, Protocol

from koras_storage import Category, ObjectStore, S3ObjectStore, object_key
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..heavy import RESTORE, heavy
from ..settings import settings
from .storage_backup import backup as backup_settings
from .storage_backup import destination_from

logger = logging.getLogger(__name__)


class ApprovedRestore(Protocol):
    """One row of the approved-and-joined query.

    A protocol rather than `Any`, so that renaming a column in the statement
    above and not here is a type error rather than an attribute error at three
    in the morning on the one night somebody needed their file back.
    """

    id: str
    tenant_id: str
    file_id: str
    overwrite: bool
    backup_key: str
    backup_digest: str | None
    size_bytes: int | None

#: The largest object this process will read into memory. The same ceiling the
#: cross-provider backup uses, for the same reason: a worker holding a gigabyte
#: to move it is a worker that falls over on the night it mattered.
RESTORE_CEILING = 64 * 1024 * 1024

#: How many approved requests one pass runs. A ceiling rather than a target.
RESTORE_LIMIT = 50

_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")
_AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)

_APPROVED = text(
    "select r.id::text as id, r.tenant_id::text as tenant_id, r.file_id::text as file_id, "
    " r.overwrite, b.backup_key, b.backup_digest, b.size_bytes, b.source_key "
    "from public.restore_requests r "
    "join public.file_backups b on b.id = r.backup_id "
    "where r.status = 'approved' order by r.approved_at limit :limit"
)

_CLAIM = text(
    "update public.restore_requests set status = 'restoring' "
    "where id = cast(:id as uuid) and status = 'approved' returning id"
)
_FINISH = text(
    "update public.restore_requests set status = :status, error = :error, "
    " restored_file_id = cast(:restored as uuid), finished_at = now() "
    "where id = cast(:id as uuid)"
)

#: The object being restored, where it still exists. An overwrite needs its key
#: and its metadata; a new object needs the metadata alone.
#:
#: Tenant-scoped, and it was not. The request that reaches here cannot name
#: another tenant's file today -- `routers/restore.py` resolves the backup
#: through `available_backup(tenant_id=...)` -- but that made a Python check the
#: only thing between a crafted row and this statement reading another tenant's
#: metadata under a context that sees every tenant. A predicate here costs
#: nothing and does not depend on the route staying correct.
_ORIGINAL = text(
    "select name, content_type, size_bytes, classification, category, uploaded_by, storage_key "
    "from public.files "
    "where id = cast(:file_id as uuid) and tenant_id = cast(:tenant_id as uuid)"
)
_INSERT_FILE = text(
    "insert into public.files "
    " (id, tenant_id, name, storage_key, content_type, size_bytes, status, uploaded_by, "
    "  category, classification, checksum_sha256) "
    "values (cast(:id as uuid), cast(:tenant_id as uuid), :name, :storage_key, :content_type, "
    " :size_bytes, 'ready', :uploaded_by, :category, :classification, :checksum)"
)
_TOUCH_FILE = text(
    "update public.files set size_bytes = :size_bytes, checksum_sha256 = :checksum, "
    " status = 'ready' "
    "where id = cast(:file_id as uuid) and tenant_id = cast(:tenant_id as uuid)"
)

_AUDIT_INSERT = text(
    "insert into public.audit_events "
    " (tenant_id, actor_id, action, target_type, target_id, outcome, details, classification) "
    "values (cast(:tenant_id as uuid), 'system', :action, 'file', :target_id, :outcome, "
    " cast(:details as jsonb), 'administrative')"
)


def _engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )


def _primary() -> ObjectStore:
    """The bucket objects live in. Where a restore puts them back."""
    from .storage_backup import _store

    return _store(backup_settings)


async def _record(
    session: AsyncSession,
    tenant_id: str,
    *,
    action: str,
    target_id: str,
    outcome: str,
    details: dict[str, Any],
) -> None:
    await session.execute(_AS_TENANT, {"tenant_id": tenant_id})
    await session.execute(
        _AUDIT_INSERT,
        {
            "tenant_id": tenant_id,
            "action": action,
            "target_id": target_id,
            "outcome": outcome,
            "details": json.dumps(details),
        },
    )


def read_and_check(
    store: ObjectStore, key: str, expected: str | None, size_bytes: int | None
) -> tuple[bytes | None, str, str | None]:
    """Fetch the copy and decide whether it is the object it claims to be.

    Returns the bytes, the digest of what was read, and a refusal where there
    is one. A mismatch returns no bytes: the object stays gone, which is
    recoverable, rather than being replaced by something that is not it.
    """
    if size_bytes is not None and size_bytes > RESTORE_CEILING:
        return None, "", "the object is larger than this process will read in one piece"
    content = store.get(key)
    if content is None:
        return None, "", "the backup copy is no longer at the destination"
    digest = hashlib.sha256(content).hexdigest()
    if expected and digest != expected:
        return None, digest, "the backup copy does not match the digest recorded for it"
    return content, digest, None


async def run_one(
    session: AsyncSession, source: ObjectStore, target: ObjectStore, row: ApprovedRestore
) -> tuple[str, str | None, str | None]:
    """One approved request. Returns its outcome, the new file id and any error."""
    content, digest, refusal = read_and_check(
        source, row.backup_key, row.backup_digest, row.size_bytes
    )
    if refusal is not None:
        return "failed", None, refusal

    original = (
        await session.execute(
            _ORIGINAL, {"file_id": row.file_id, "tenant_id": row.tenant_id}
        )
    ).first()

    # The index row is written as the tenant, never as the platform, and this
    # is the whole correctness of the function.
    #
    # `files` has no provisioning insert policy and `00021` says the omission
    # is deliberate; `files_update_provisioning` additionally refuses a row
    # whose status is `purged`. So a worker on the provisioning context could
    # write the bytes and then fail to write the row -- leaving an object with
    # no index entry at all, which is outside retention, outside every hold,
    # outside the purge sweep, and which reconciliation reports without ever
    # removing. Restored content, usually content the tenant had purged,
    # resurrected into live storage permanently and invisibly.
    #
    # A restored object belongs to the tenant exactly as an uploaded one does,
    # so it is written under the tenant's own policies. That is also what the
    # audit inserts in every other sweep already do.
    await session.execute(_AS_TENANT, {"tenant_id": row.tenant_id})

    if row.overwrite:
        if original is None:
            # Approved as an overwrite and there is nothing to overwrite. Not a
            # silent downgrade to a new object: the approval was for a
            # different act than the one now available.
            return "failed", None, "the object to overwrite no longer exists"
        target.put(original.storage_key, content or b"", original.content_type)
        touched = await session.execute(
            _TOUCH_FILE,
            {
                "file_id": row.file_id,
                "tenant_id": row.tenant_id,
                "size_bytes": len(content or b""),
                "checksum": digest,
            },
        )
        # `rowcount` is on the cursor result rather than the typed `Result`
        # facade, which is why this reads it dynamically. Zero is the case that
        # matters: `files_update_provisioning` refuses a row whose status is
        # `purged`, so an approved overwrite of a stranded object would
        # otherwise write the bytes back, update nothing, and report success.
        if getattr(touched, "rowcount", 0) != 1:
            # Reported `completed` while updating nothing, which is the worst
            # shape a destructive operation can take: the bytes are back in the
            # bucket, the index still says what it said, and the next sweep
            # removes them again. A row that could not be updated is a failure
            # and the request says so.
            return (
                "failed",
                None,
                "the object could not be brought back into the index; nothing was changed",
            )
        return "completed", row.file_id, None

    # A new object, which destroys nothing. Its own id and its own key, so the
    # restored copy and anything still at the original key are distinguishable.
    new_id = str(uuid.uuid4())
    name = original.name if original is not None else f"restored-{row.file_id}"
    content_type = original.content_type if original is not None else "application/octet-stream"
    category = Category(original.category) if original is not None else Category.DOCUMENTS
    key = object_key(row.tenant_id, new_id, name, category=category)
    target.put(key, content or b"", content_type)
    await session.execute(
        _INSERT_FILE,
        {
            "id": new_id,
            "tenant_id": row.tenant_id,
            "name": name,
            "storage_key": key,
            "content_type": content_type,
            "size_bytes": len(content or b""),
            "uploaded_by": original.uploaded_by if original is not None else "system",
            "category": str(category),
            "classification": (
                original.classification if original is not None else "standard"
            ),
            "checksum": digest,
        },
    )
    return "completed", new_id, None


async def run_restores(ctx: dict[str, Any]) -> dict[str, Any]:
    """Every approved request, read and checked before anything is written."""
    del ctx
    if not settings.database_url:
        logger.warning("restore skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}
    if not backup_settings.storage_bucket or not backup_settings.storage_access_key:
        logger.warning("restore skipped: the worker has no storage credentials")
        return {"status": "skipped", "reason": "no storage"}
    try:
        backup_destination = destination_from(backup_settings)
    except ValueError as problem:
        # Enabled approvals with nowhere to read from. Loud, and not a skip: a
        # restore reported as nothing-to-do is a restore nobody chases.
        logger.error("restore cannot run: %s", problem)
        return {"status": "failed", "reason": str(problem)}

    source = S3ObjectStore(backup_destination)
    target = _primary()
    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            done, failed = await restore_approved(session, source, target)
    finally:
        await engine.dispose()

    logger.info("restore: %d completed, %d failed", done, failed)
    return {"status": "ok", "completed": done, "failed": failed}


async def restore_approved(
    session: AsyncSession, source: ObjectStore, target: ObjectStore
) -> tuple[int, int]:
    """Every approved request on this session. Returns how many completed and failed."""
    done = 0
    failed = 0
    await session.execute(_PROVISIONING)
    approved = (await session.execute(_APPROVED, {"limit": RESTORE_LIMIT})).all()
    # Ended here, so that a wait for the gate is not a transaction held open.
    await session.commit()
    for row in approved:
        # The gate first, then the claim. A request that waits here for an
        # import to finish has not been claimed, so a sweep the queue cancels
        # while it waits leaves an `approved` row for the next pass rather
        # than a `restoring` one nothing will ever pick up. GR-352E.
        async with heavy(RESTORE):
            await session.execute(_PROVISIONING)
            # Claimed before anything is read, so two workers cannot run the
            # same request.
            claimed = (await session.execute(_CLAIM, {"id": row.id})).first()
            await session.commit()
            await session.execute(_PROVISIONING)
            if claimed is None:
                await session.commit()
                continue

            try:
                outcome, restored, error = await run_one(session, source, target, row)
            except Exception:
                logger.exception("a restore failed")
                await session.rollback()
                await session.execute(_PROVISIONING)
                outcome, restored, error = "failed", None, "the restore could not be completed"

        # Outside the gate: the object has been written and is no longer in
        # hand, and what is left is two rows.
        #
        # Back to the platform's context before touching the request
        # row. `run_one` ends on the tenant's, because the index row it
        # writes belongs to the tenant -- and `_FINISH` is written
        # against `restore_requests_run_provisioning`, which is the
        # policy that admits `restoring` -> `completed`. Leaving the
        # tenant context set would have it permitted by the tenant's
        # own policy instead: the same outcome today, by a rule nobody
        # chose, and a silent failure the day either policy changes.
        await session.execute(_PROVISIONING)
        await session.execute(
            _FINISH,
            {
                "id": row.id,
                "status": outcome,
                "error": error,
                "restored": restored,
            },
        )
        await _record(
            session,
            row.tenant_id,
            action=f"storage.restore.{outcome}",
            target_id=row.file_id,
            outcome="ok" if outcome == "completed" else "failed",
            details={
                "overwrite": bool(row.overwrite),
                # Whether anything was compared, and never the digest
                # itself: it identifies the bytes.
                "verified": bool(row.backup_digest),
            },
        )
        # The last statement of a request: nothing is left open for the next
        # one's wait.
        await session.commit()
        done += outcome == "completed"
        failed += outcome == "failed"
    return done, failed
