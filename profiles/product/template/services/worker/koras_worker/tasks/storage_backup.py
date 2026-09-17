"""The nightly copy, and the comparison that makes it a backup.

**A copy is not a backup until its integrity is verified.** A provider
acknowledging a copy tells you the request was accepted, not that the bytes
match. Every object this touches ends at `copied`, `verified` or `failed`, and
only the second is a backup. ADR 0006 decision 1, and the reason the digest work
was built before this.

**An object neither end can produce a comparable digest for stays `copied`.**
Not `failed`. A multipart entity tag is a digest of digests and a provider only
computes a SHA-256 when the upload asked it to, so "no digest" is the ordinary
case rather than the alarming one. Calling it a mismatch would report every
large object as corrupt and teach whoever reads the console to ignore the
number. ADR 0006 decision 2.

**The run walks the index, not the bucket.** The index knows which objects are
supposed to exist. A run driven by a listing would faithfully copy an orphan and
miss a row whose object was already gone. ADR 0006 decision 3.

**A partial run is never recorded as complete**, the rule reconciliation follows
for the same reason: a count from an unfinished pass, presented as a total, is
worse than no count.

**Same provider or another one, and the difference is visible here.** Where the
destination shares an endpoint with the source, the provider copies server-side
and no byte reaches this process. Where it does not -- a bucket at R2 while the
objects are at Supabase -- no single provider can make that copy, so the object
passes through the worker. That is bounded: an object larger than
`STREAM_CEILING` is left for a person to decide about rather than pulled into a
worker's memory, and a run that leaves any is partial.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from koras_storage import (
    S3_COMPATIBLE,
    CopyRefused,
    Destination,
    IntegrityRefused,
    ObjectStore,
    Provider,
    S3ObjectStore,
    StorageSettings,
    resolve_destination,
)
from pydantic_settings import SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..settings import SweepSettings, settings


class BackupSettings(SweepSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    #: Off unless asked for. A copy costs storage at a second destination, and a
    #: product that has not decided where that is should not be billed for one.
    storage_backup_enabled: bool = False

    #: Where the copy goes. A second bucket in the same project is the minimum
    #: that means anything; a bucket at another provider is the version that
    #: survives an account.
    storage_backup_bucket: str = ""
    #: Unset means the same endpoint and region as the source, which is the
    #: same-project case and the one the provider can serve server-side.
    storage_backup_endpoint: str = ""
    storage_backup_region: str = ""
    #: Which provider the destination is, as a label rather than as behaviour:
    #: every provider this estate serves speaks the same S3 dialect, and the
    #: endpoint is what actually routes. It exists so that a catalogue row and
    #: a console read the truth rather than a default somebody guessed from a
    #: hostname. Unset means the same provider as the source.
    storage_backup_provider: str = ""
    #: Unset means the source's own pair. That works only while the destination
    #: is in the same project -- and a separate pair is also what stops one
    #: compromised credential reaching both the original and the copy.
    storage_backup_access_key: str = ""
    storage_backup_secret_key: str = ""

    #: How long a copy outlives the object it copies. Thirty days when unset:
    #: insurance against losing something recently, not a second archive.
    storage_backup_retention_days: int = 30

    #: Objects one nightly pass copies at most. A ceiling, so the first run on a
    #: large tenant does not become the provider bill nobody predicted.
    storage_backup_limit: int = 2000

    storage_endpoint: str = ""
    storage_bucket: str = ""
    storage_region: str = ""
    storage_access_key: str = ""
    storage_secret_key: str = ""


backup = BackupSettings()

logger = logging.getLogger(__name__)

#: The largest object this process will read into memory for a cross-provider
#: copy. Above it the object is left alone and the run reports itself partial:
#: a worker holding a gigabyte in memory to move it between two providers is a
#: worker that falls over on the night the backup mattered.
STREAM_CEILING = 64 * 1024 * 1024

_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")
_AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)

#: Ready objects with no good copy. `failed` is included deliberately: a
#: mismatch on one night is a reason to try again on the next, not a verdict.
_DUE = text(
    "select id::text as id, tenant_id::text as tenant_id, storage_key, size_bytes, "
    " checksum_sha256 "
    "from public.files "
    "where status in ('ready', 'archived') and backup_status in ('none', 'failed') "
    "  and storage_key is not null "
    "order by created_at limit :limit"
)

_CATALOGUE = text(
    "insert into public.file_backups "
    " (tenant_id, file_id, source_key, backup_key, destination, size_bytes, "
    "  source_digest, backup_digest, status, note, verified_at) "
    "values (cast(:tenant_id as uuid), cast(:file_id as uuid), :source_key, :backup_key, "
    " :destination, :size_bytes, :source_digest, :backup_digest, :status, :note, :verified_at) "
    "on conflict (file_id, destination) do update set "
    " source_key = excluded.source_key, backup_key = excluded.backup_key, "
    " size_bytes = excluded.size_bytes, source_digest = excluded.source_digest, "
    " backup_digest = excluded.backup_digest, status = excluded.status, "
    " note = excluded.note, copied_at = now(), verified_at = excluded.verified_at, "
    " expires_at = null"
)

_MARK = text(
    "update public.files set backup_status = :status, backed_up_at = :at "
    "where id = cast(:file_id as uuid)"
)

#: A catalogue row whose object is gone and which has not been dated yet. The
#: copy is kept for the retention period *after* the loss, which is the whole
#: point: a copy retired at the moment of the accident is not insurance.
_ORPHANED = text(
    "select b.id::text as id, b.tenant_id::text as tenant_id "
    "from public.file_backups b "
    "where b.expires_at is null "
    "  and not exists (select 1 from public.files f where f.id = b.file_id)"
)
_SET_EXPIRY = text(
    "update public.file_backups set expires_at = now() + make_interval(days => :days) "
    "where id = cast(:id as uuid)"
)

_EXPIRED = text(
    "select id::text as id, tenant_id::text as tenant_id, backup_key "
    "from public.file_backups "
    "where expires_at is not null and expires_at < now() "
    "order by expires_at limit :limit"
)
_FORGET = text("delete from public.file_backups where id = cast(:id as uuid)")

_AUDIT_INSERT = text(
    "insert into public.audit_events "
    " (tenant_id, actor_id, action, target_type, target_id, outcome, details, classification) "
    "values (cast(:tenant_id as uuid), 'system', :action, :target_type, :target_id, :outcome, "
    " cast(:details as jsonb), 'audit')"
)


@dataclass(frozen=True)
class Outcome:
    """What one object's copy concluded, before anything is written down."""

    status: str
    source_digest: str | None
    backup_digest: str | None
    note: str | None


@dataclass(frozen=True)
class RunSummary:
    """One night's pass over one product."""

    considered: int
    copied: int
    verified: int
    failed: int
    #: Objects the run declined to move: too large to stream to another
    #: provider, or gone from the source between the index read and the copy.
    skipped: int
    #: True when the run did not reach everything it could have -- it hit the
    #: limit, or it left an object behind. Every count above is then a floor.
    partial: bool


def destination_from(config: BackupSettings) -> Destination:
    """Where the copy goes, refusing to guess at anything load-bearing.

    An unset endpoint, region or key pair means "the same as the source", which
    is the same-project case. An unset *bucket* means nothing is configured, and
    that is a refusal rather than a default: a backup written into the bucket it
    was copied from is not a backup, and it is the one mistake that looks like
    success in every log line.
    """
    if not config.storage_backup_bucket:
        raise ValueError("STORAGE_BACKUP_BUCKET is not set; there is nowhere to copy to")
    if (
        config.storage_backup_bucket == config.storage_bucket
        and not config.storage_backup_endpoint
    ):
        raise ValueError(
            "STORAGE_BACKUP_BUCKET is the bucket the objects are already in; "
            "a copy beside the original survives a deleted object and nothing else"
        )
    return Destination(
        provider=_provider(config.storage_backup_provider),
        endpoint=config.storage_backup_endpoint or config.storage_endpoint,
        bucket=config.storage_backup_bucket,
        region=config.storage_backup_region or config.storage_region,
        access_key=config.storage_backup_access_key or config.storage_access_key,
        secret_key=config.storage_backup_secret_key or config.storage_secret_key,
    )


def _provider(name: str) -> Provider:
    """The destination's provider, refusing a name this product does not serve.

    Unset is the source's provider, which is the same-project case. A name that
    is not a provider is a refusal rather than a fallback: a typo resolving to
    the default is a backup written somewhere nobody chose.
    """
    if not name:
        return Provider.SUPABASE
    try:
        provider = Provider(name)
    except ValueError as problem:
        raise ValueError(
            f"STORAGE_BACKUP_PROVIDER is {name!r}, which is not a provider at all"
        ) from problem
    if provider not in S3_COMPATIBLE:
        # Azure Blob and a customer-owned account are named by the enum and
        # refused everywhere else in this product. A backup destination is not
        # the place they quietly become supported.
        raise ValueError(
            f"STORAGE_BACKUP_PROVIDER is {name!r}, which is not a provider this product serves"
        )
    return provider


def streams_through_here(config: BackupSettings) -> bool:
    """Whether the bytes have to pass through this process.

    They do exactly when the destination names an endpoint of its own that is
    not the source's: no single provider can copy server-side between two it
    does not both serve. Read from the settings rather than from the two
    stores, because it decides which store to build and what a run costs.
    """
    endpoint = config.storage_backup_endpoint
    return bool(endpoint) and endpoint != config.storage_endpoint


def verdict(source_digest: str | None, backup_digest: str | None) -> Outcome:
    """Compare two digests, and say plainly when there was nothing to compare.

    Three outcomes and not two. The third -- neither end holds a comparable
    digest -- is the ordinary case rather than the alarming one, because a
    provider computes a SHA-256 only when asked to and most objects were never
    asked. It is `copied`: a true statement about what is known.
    """
    if source_digest and backup_digest:
        if source_digest == backup_digest:
            return Outcome("verified", source_digest, backup_digest, None)
        return Outcome(
            "failed",
            source_digest,
            backup_digest,
            "the copy's digest does not match the source's",
        )
    missing = "the source" if not source_digest else "the copy"
    return Outcome(
        "copied",
        source_digest,
        backup_digest,
        f"no comparable digest for {missing}; copied but not verified",
    )


def digest_by_reading(store: ObjectStore, key: str, *, size_bytes: int | None) -> str | None:
    """Hash an object by reading it, for a provider that will not say.

    **Why this exists.** A backup is worth what can be said about it, and until
    this function every statement depended on the provider volunteering a
    SHA-256. Supabase's S3 accepts one on upload, stores nothing, and answers
    `None` to `HeadObject` and `GetObject` alike -- confirmed against the dev
    estate on 2026-09-17 by sending a digest and asking for it back. Nothing
    computes a digest at upload either, so `files.checksum_sha256` is null for
    every row. `verified` was therefore unreachable on the only provider
    configured in any environment, and the feature reported `copied` for ever
    while being described as backup with digest verification.

    Reading both ends and hashing them here is *stronger* than the provider's
    answer, not a substitute for it: it is a statement about the bytes this
    process actually read, rather than about a value a provider stored and may
    have computed over something else. The provider's own digest is still
    preferred where it exists, because it costs nothing.

    Bounded by `STREAM_CEILING`, which is the same bound the cross-provider copy
    has and for the same reason: an object of any size must not be pulled into a
    worker's memory. Past it this answers `None`, the comparison has nothing to
    compare, and the outcome is an honest `copied`.
    """
    if size_bytes is not None and size_bytes > STREAM_CEILING:
        return None
    content = store.get(key)
    return None if content is None else hashlib.sha256(content).hexdigest()


def _stream_one(
    store: ObjectStore,
    target_store: ObjectStore,
    *,
    source_key: str,
    backup_key: str,
    size_bytes: int | None,
) -> Outcome:
    """Read the object here and write it there, hashing what passes through.

    Used when no single provider reaches both ends, and now also when one that
    should reach both refuses -- see `copy_one`.
    """
    if size_bytes is not None and size_bytes > STREAM_CEILING:
        return Outcome("skipped", None, None, "larger than the cross-provider stream ceiling")
    content = store.get(source_key)
    if content is None:
        return Outcome("skipped", None, None, "the object was gone from the source")
    local = hashlib.sha256(content).hexdigest()
    try:
        # The digest goes *with* the write. The destination verifies what it
        # received before storing it and keeps the digest, so the `checksum()`
        # below has something to answer with.
        #
        # Sending it is what makes this path capable of `verified` at all.
        # Without it the destination stores no SHA-256, `checksum()` answers
        # None, and every copy through here reads `copied` for ever -- a backup
        # nobody could ever confirm, reported by a job whose entire purpose is
        # confirming backups.
        target_store.put(backup_key, content, "application/octet-stream", checksum_sha256=local)
    except IntegrityRefused:
        # The destination compared and disagreed. That is the control working,
        # and it is a failure rather than something to retry without the digest.
        return Outcome("failed", local, None, "the destination rejected the bytes as not matching")
    # The locally computed digest is the source side of the comparison: the
    # bytes read are the bytes hashed. The destination's own digest is preferred
    # because it costs nothing; where it answers none -- Supabase answers none
    # for everything -- the copy is read back and hashed here, which is what
    # makes `verified` reachable at all on such a provider.
    answered = target_store.checksum(backup_key) or digest_by_reading(
        target_store, backup_key, size_bytes=size_bytes
    )
    return verdict(local, answered)


def copy_one(
    store: ObjectStore,
    target_store: ObjectStore,
    target: Destination,
    *,
    source_key: str,
    backup_key: str,
    size_bytes: int | None,
    streaming: bool,
) -> Outcome:
    """Copy one object and decide what the copy is worth.

    Server-side where one provider reaches both ends. Where it does not -- or
    where the one that should refuses -- the bytes pass through here, bounded by
    `STREAM_CEILING`, and the digest of what was sent is computed here too,
    which is a stronger statement than either provider's: it is the digest of
    the bytes this process actually read from the source and actually wrote to
    the destination.

    **The refusal case is not theoretical.** Supabase's S3 gateway refuses
    `CopyObject` for any key containing a space, with an empty error code, while
    `HeadObject` on the same key succeeds. Four of the dev estate's six objects
    were therefore recorded `failed` night after night -- a backup job reporting
    `ok` while two thirds of the files it was for had no copy. Reading the
    bytes and writing them works on exactly those keys, so the fallback is not a
    lesser copy: it is the only one available, and it is the one that can reach
    `verified`.

    An integrity refusal is never answered this way. That is the destination
    saying the bytes do not match, and writing them by another route is how a
    corrupt object becomes a backup.
    """
    if streaming:
        return _stream_one(
            store,
            target_store,
            source_key=source_key,
            backup_key=backup_key,
            size_bytes=size_bytes,
        )

    try:
        store.copy(source_key, backup_key, dest=target)
    except CopyRefused:
        return _stream_one(
            store,
            target_store,
            source_key=source_key,
            backup_key=backup_key,
            size_bytes=size_bytes,
        )
    # Same rule on both ends: take the provider's digest when it gives one,
    # read and hash when it does not. On a provider that answers neither this
    # is two extra reads per object, once, when the backup is made -- `_DUE`
    # only picks up objects with no good copy, so a verified one is never read
    # again.
    source_digest = store.checksum(source_key) or digest_by_reading(
        store, source_key, size_bytes=size_bytes
    )
    backup_digest = target_store.checksum(backup_key) or digest_by_reading(
        target_store, backup_key, size_bytes=size_bytes
    )
    return verdict(source_digest, backup_digest)


def backup_key_for(source_key: str) -> str:
    """Where the copy lives at the destination.

    The source key unchanged. Objects here are immutable -- a key carries the
    file's id and nothing overwrites one -- so a mirror is a complete backup of
    current state, and a restore does not need a catalogue lookup to find the
    bytes. Dating the copies would guard against an overwrite this product
    cannot perform, at the cost of multiplying every object.
    """
    return source_key


def _store(config: BackupSettings) -> ObjectStore:
    return S3ObjectStore(
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


def _engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )


async def _record(
    session: AsyncSession,
    tenant_id: str,
    *,
    action: str,
    target_type: str,
    target_id: str,
    outcome: str,
    details: dict[str, Any],
) -> None:
    """One audit row, on that tenant's own context.

    The audit table admits an insert only for the tenant the row belongs to, so
    the sweep steps out of the provisioning context to write and the caller puts
    it back. No object keys: a key is half a signed URL and is never a detail.
    """
    await session.execute(_AS_TENANT, {"tenant_id": tenant_id})
    await session.execute(
        _AUDIT_INSERT,
        {
            "tenant_id": tenant_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "outcome": outcome,
            "details": json.dumps(details),
        },
    )


async def back_up_tenant_objects(
    session: AsyncSession,
    store: ObjectStore,
    target_store: ObjectStore,
    target: Destination,
    *,
    streaming: bool,
    limit: int,
) -> RunSummary:
    """Copy what has no good copy, across every tenant, and catalogue each one.

    Counted twice: once for the run's own summary, and once per tenant, because
    every run is recorded whatever its outcome and an audit row belongs to the
    tenant whose objects it describes. ADR 0006 decision 4.
    """
    due = (await session.execute(_DUE, {"limit": limit})).all()
    counts = {"copied": 0, "verified": 0, "failed": 0, "skipped": 0}
    per_tenant: dict[str, dict[str, int]] = {}

    for row in due:
        tally = per_tenant.setdefault(
            row.tenant_id, {"copied": 0, "verified": 0, "failed": 0, "skipped": 0}
        )
        key = backup_key_for(row.storage_key)
        try:
            outcome = copy_one(
                store,
                target_store,
                target,
                source_key=row.storage_key,
                backup_key=key,
                size_bytes=row.size_bytes,
                streaming=streaming,
            )
        except Exception:
            # One object the provider refused is not a reason to stop copying
            # the rest, and a run that stopped would leave the same object first
            # in the queue every night.
            logger.exception("an object could not be copied to the backup destination")
            outcome = Outcome("failed", None, None, "the destination refused the copy")

        counts[outcome.status] += 1
        tally[outcome.status] += 1
        if outcome.status == "skipped":
            continue

        now = datetime.now(UTC)
        await session.execute(
            _CATALOGUE,
            {
                "tenant_id": row.tenant_id,
                "file_id": row.id,
                "source_key": row.storage_key,
                "backup_key": key,
                "destination": target.bucket,
                "size_bytes": row.size_bytes,
                "source_digest": outcome.source_digest,
                "backup_digest": outcome.backup_digest,
                "status": outcome.status,
                "note": outcome.note,
                "verified_at": now if outcome.status == "verified" else None,
            },
        )
        await session.execute(
            _MARK,
            {
                "file_id": row.id,
                "status": outcome.status,
                "at": now if outcome.status != "failed" else None,
            },
        )
        await session.commit()
        await session.execute(_PROVISIONING)

    for tenant_id, tally in per_tenant.items():
        await _record(
            session,
            tenant_id,
            action="storage.backup.run",
            target_type="tenant",
            target_id=tenant_id,
            # `ok` only where nothing failed and nothing was left behind. A run
            # that copied a hundred objects and could not verify one of them is
            # not a successful run with a footnote.
            outcome="ok" if not (tally["failed"] or tally["skipped"]) else "failed",
            details=dict(tally),
        )
        await session.commit()
        await session.execute(_PROVISIONING)

    return RunSummary(
        considered=len(due),
        copied=counts["copied"],
        verified=counts["verified"],
        failed=counts["failed"],
        skipped=counts["skipped"],
        # Hitting the limit means there is more to do; a skipped object means
        # something was left behind. Either way the counts are a floor.
        partial=len(due) >= limit or counts["skipped"] > 0,
    )


async def date_orphaned_copies(session: AsyncSession, *, days: int) -> int:
    """Start the clock on copies whose object is gone.

    Not at purge time, because the purge happens in a different sweep that
    should not have to know a catalogue exists. Here, where the catalogue does.
    """
    dated = 0
    for row in (await session.execute(_ORPHANED)).all():
        await session.execute(_SET_EXPIRY, {"id": row.id, "days": days})
        dated += 1
    if dated:
        await session.commit()
        await session.execute(_PROVISIONING)
    return dated


async def retire_expired_copies(
    session: AsyncSession, target_store: ObjectStore, *, limit: int
) -> tuple[int, int]:
    """Remove copies past their date. The object first, then the catalogue row."""
    retired = 0
    stuck = 0
    for row in (await session.execute(_EXPIRED, {"limit": limit})).all():
        try:
            target_store.delete(row.backup_key)
        except Exception:
            logger.warning("an expired backup copy could not be removed from the destination")
            stuck += 1
            continue
        await session.execute(_FORGET, {"id": row.id})
        await _record(
            session,
            row.tenant_id,
            action="storage.backup.retired",
            target_type="file",
            target_id=row.id,
            outcome="ok",
            details={"reason": "expired"},
        )
        await session.commit()
        await session.execute(_PROVISIONING)
        retired += 1
    return retired, stuck


async def back_up_storage(ctx: dict[str, Any]) -> dict[str, Any]:
    """The nightly pass: copy, verify, date what is orphaned, retire what is due.

    Skips loudly rather than quietly. A misconfigured destination is a failure
    and not a no-op, because a backup reported as nothing-to-do is a backup
    nobody fixes -- the same rule registration follows.
    """
    del ctx
    if not backup.storage_backup_enabled:
        return {"status": "skipped", "reason": "not enabled"}
    if not settings.database_url:
        logger.warning("storage backup skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}
    if not backup.storage_bucket or not backup.storage_access_key:
        logger.warning("storage backup skipped: the worker has no storage credentials")
        return {"status": "skipped", "reason": "no storage"}

    try:
        target = destination_from(backup)
    except ValueError as problem:
        # Enabled and misconfigured. Loud, and not a skip.
        logger.error("storage backup is enabled and cannot run: %s", problem)
        return {"status": "failed", "reason": str(problem)}

    store = _store(backup)
    target_store = S3ObjectStore(target)
    streaming = streams_through_here(backup)

    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(_PROVISIONING)
            summary = await back_up_tenant_objects(
                session,
                store,
                target_store,
                target,
                streaming=streaming,
                limit=backup.storage_backup_limit,
            )
            dated = await date_orphaned_copies(
                session, days=backup.storage_backup_retention_days
            )
            retired, stuck = await retire_expired_copies(
                session, target_store, limit=backup.storage_backup_limit
            )
    finally:
        await engine.dispose()

    logger.info(
        "storage backup: %d considered, %d verified, %d copied only, %d failed, %d skipped, "
        "%d copies dated, %d retired%s",
        summary.considered,
        summary.verified,
        summary.copied,
        summary.failed,
        summary.skipped,
        dated,
        retired,
        " (partial)" if summary.partial else "",
    )
    return {
        # A partial run says so in its own status rather than leaving the caller
        # to notice a count. ADR 0006 decision 5.
        "status": "partial" if summary.partial else "ok",
        "considered": summary.considered,
        "verified": summary.verified,
        "copied": summary.copied,
        "failed": summary.failed,
        "skipped": summary.skipped,
        "dated": dated,
        "retired": retired,
        "stuck": stuck,
        "streaming": streaming,
    }
