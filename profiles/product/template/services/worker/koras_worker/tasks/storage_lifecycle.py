"""Object retention: resolve a date, then act on it once it passes.

Migration 00018 put `retain_until`, `retention_policy` and `legal_hold` on the
file index and nothing wrote or read them. This is both halves.

**Resolution.** A file gets a retention date from the platform floor for its
classification. The date is written once, when a policy is first resolved for
the object, rather than recomputed at sweep time -- but the *floor* is read
fresh each night, so a lengthened floor extends objects that have not yet
expired. Shortening the floor does not bring an existing date forward: that
direction is the one that deletes data, and a configuration change should not.

**Purge.** An object past its date, not held, is removed: object first, then
the row, which is the order the Files routes already use and the order that
leaves a findable orphan rather than a row with no bytes behind it.

Two states in the documented lifecycle are deliberately absent. WARM and COLD
are metadata with no physical effect -- no provider this estate uses offers
tiering -- and ARCHIVE needs a bucket nothing provisions. Writing a `tier`
column that nothing acts on would be the same defect this module exists to
close: a column that looks like a capability and is not.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from koras_storage import ObjectStore, S3ObjectStore, StorageSettings, resolve_destination
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..settings import settings


class LifecycleSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    #: Off unless asked for. This sweep deletes, which is a good reason to make
    #: a product opt in rather than discover it.
    storage_lifecycle_enabled: bool = False

    #: The platform floor, in days, by classification. A tenant may lengthen
    #: retention and may never shorten it below these.
    #:
    #: **`standard` is one day, and that is the whole point of the number.**
    #: It was 2555 -- seven years over everything a customer uploaded, which a
    #: tenant could not shorten. A customer who uploads a document and wants it
    #: gone in ninety days is entitled to ask, and a product that answers
    #: "seven years" to that is not applying a compliance control; it is
    #: refusing a deletion, which is the finding rather than the defence. One
    #: day rather than zero because retention of nothing is a wipe, and
    #: `floors_from` refuses anything below one for that reason.
    #:
    #: `sensitive` and `restricted` keep ten years, because those are the
    #: classifications a product sets deliberately for content it has decided
    #: carries an obligation. The floor belongs where the obligation is.
    #: Decided 2026-09-16; ADR 0003 decision 15.
    storage_retention_days_standard: int = 1
    storage_retention_days_sensitive: int = 3650
    storage_retention_days_restricted: int = 3650

    #: How many objects one night removes at most. A ceiling rather than a
    #: target: a sweep that deletes ten thousand files because a floor was
    #: mistyped is a sweep nobody can stop halfway.
    storage_purge_limit: int = 500

    storage_endpoint: str = ""
    storage_bucket: str = ""
    storage_region: str = ""
    storage_access_key: str = ""
    storage_secret_key: str = ""


lifecycle = LifecycleSettings()

logger = logging.getLogger(__name__)

_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")
_AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)

#: Objects with no resolved policy. Null is not expired -- it means nobody has
#: decided -- so these are given a date rather than swept.
_UNRESOLVED = text(
    "select id::text as id, tenant_id::text as tenant_id, classification, created_at "
    "from public.files "
    "where retain_until is null and status in ('ready', 'quarantined') "
    "order by created_at limit :limit"
)

# The floor resolved against this tenant's own override, whichever is longer.
_SET_RETENTION = text(
    "update public.files f "
    "   set retain_until = f.created_at + make_interval("
    "         days => public.retention_days_for(f.tenant_id, :kind, :days)), "
    "       retention_policy = :policy "
    " where f.id = cast(:id as uuid) and f.retain_until is null"
)

#: Only lengthening, and set-based because it touches every row of a class.
#: The `retain_until < ...` is what makes it one-directional: a floor that was
#: *shortened* matches nothing, so a configuration change can extend retention
#: and can never bring a deletion forward.
_EXTEND = text(
    "update public.files f "
    "   set retain_until = f.created_at + make_interval("
    "         days => public.retention_days_for(f.tenant_id, :kind, :days)), "
    "       retention_policy = :policy "
    " where coalesce(f.classification, 'standard') = :classification "
    "   and f.retain_until is not null "
    "   and f.status <> 'purged' "
    "   and f.retain_until < f.created_at + make_interval("
    "         days => public.retention_days_for(f.tenant_id, :kind, :days)) "
    "returning f.id"
)

#: Due, and not held. The hold is checked in the query rather than after it,
#: so a row under hold is never even selected for removal.
_DUE = text(
    "select f.id::text as id, f.tenant_id::text as tenant_id, f.storage_key, f.size_bytes "
    "from public.files f "
    "where f.retain_until is not null and f.retain_until < now() "
    "  and f.legal_hold = false and f.status <> 'purged' "
    "  and not public.under_legal_hold(f.tenant_id, 'files') "
    "order by f.retain_until limit :limit"
)

#: What a hold kept, counted before anything is removed.
_HELD = text(
    "select count(*) as held from public.files f "
    "where f.retain_until is not null and f.retain_until < now() and f.status <> 'purged' "
    "  and (f.legal_hold = true or public.under_legal_hold(f.tenant_id, 'files'))"
)

#: Rows marked `purged` whose object the bucket would not delete on an earlier
#: run. Retried before anything new is purged, because the alternative is what
#: shipped first: `_DUE` excludes `status = 'purged'`, so a row that stranded
#: once stranded forever, and reconciliation could not find it either -- it
#: reads every `files` row into its claimed set, so the object was never an
#: orphan to report. Nothing in the product looked at these.
_STRANDED = text(
    "select id::text as id, tenant_id::text as tenant_id, storage_key, size_bytes "
    "from public.files where status = 'purged' and storage_key is not null "
    "order by retain_until limit :limit"
)

_MARK_PURGED = text("update public.files set status = 'purged' where id = cast(:id as uuid)")
_DELETE_ROW = text("delete from public.files where id = cast(:id as uuid)")

_AUDIT_INSERT = text(
    "insert into public.audit_events "
    " (tenant_id, actor_id, action, target_type, target_id, outcome, details, classification) "
    "values (cast(:tenant_id as uuid), 'system', :action, 'file', :file_id, :outcome, "
    " cast(:details as jsonb), :class)"
)


@dataclass(frozen=True)
class Floors:
    """The platform floor per classification, in days."""

    standard: int
    sensitive: int
    restricted: int

    def days_for(self, classification: str | None) -> int:
        if classification == "sensitive":
            return self.sensitive
        if classification == "restricted":
            return self.restricted
        return self.standard


def floors_from(config: LifecycleSettings) -> Floors:
    """Read the floors, refusing a retention of nothing.

    The same guard the audit sweep has, for the same reason and with the same
    ordering: every floor is checked before anything is resolved or removed, so
    one mistyped number cannot act on the two that were right.
    """
    floors = Floors(
        standard=config.storage_retention_days_standard,
        sensitive=config.storage_retention_days_sensitive,
        restricted=config.storage_retention_days_restricted,
    )
    for name, days in (
        ("standard", floors.standard),
        ("sensitive", floors.sensitive),
        ("restricted", floors.restricted),
    ):
        if days < 1:
            raise ValueError(
                f"storage retention for {name!r} must be at least 1 day; "
                "retention of nothing is a wipe"
            )
    return floors


async def resolve_retention(session: AsyncSession, *, floors: Floors, limit: int) -> int:
    """Give a date to objects that have none. Returns how many were resolved.

    The date is derived from the object's own creation time, not from now, so
    resolving late does not grant an old file a fresh full term.
    """
    rows = (await session.execute(_UNRESOLVED, {"limit": limit})).all()
    for row in rows:
        classification = row.classification or "standard"
        await session.execute(
            _SET_RETENTION,
            {
                "id": row.id,
                "kind": f"storage_{classification}",
                "days": floors.days_for(row.classification),
                "policy": f"platform:{classification}",
            },
        )
    await session.commit()
    return len(rows)


async def extend_to_floor(session: AsyncSession, *, floors: Floors) -> int:
    """Lengthen any date that now falls short of its floor. Never shorten one.

    A floor raised today should protect objects stored yesterday, so this runs
    every night rather than only at resolution. The reverse -- a floor lowered
    today pulling an existing date forward -- would mean a configuration change
    deleting data on the next sweep, and the statement is written so that it
    cannot: it matches only rows whose date is *below* the floor.
    """
    extended = 0
    for classification in ("standard", "sensitive", "restricted"):
        rows = await session.execute(
            _EXTEND,
            {
                "classification": classification,
                "kind": f"storage_{classification}",
                "days": floors.days_for(classification),
                "policy": f"platform:{classification}",
            },
        )
        extended += len(rows.all())
    await session.commit()
    return extended


async def retry_stranded(
    session: AsyncSession, store: ObjectStore, *, limit: int
) -> tuple[int, int]:
    """Try again to remove objects whose row already says `purged`.

    Before anything new is purged, so a bucket that has started refusing
    deletes cannot have a growing backlog hidden behind a fresh one. Returns
    how many were cleared and how many are still stranded.
    """
    cleared = 0
    still = 0
    for row in (await session.execute(_STRANDED, {"limit": limit})).all():
        try:
            store.delete(row.storage_key)
        except Exception:
            logger.warning("a stranded object still could not be removed from the bucket")
            still += 1
            continue
        await session.execute(_DELETE_ROW, {"id": row.id})
        await session.commit()
        await session.execute(_PROVISIONING)
        cleared += 1
    return cleared, still


async def purge_expired(
    session: AsyncSession, store: ObjectStore, *, limit: int
) -> tuple[int, int, int]:
    """Remove objects past their retention that nothing is holding.

    Returns how many were purged, how many a hold kept, and how many could not
    be removed from the bucket. The third is retried at the start of the next
    run: an object the provider would not delete leaves its row marked
    `purged`, and that row is this sweep's own backlog. It is not
    reconciliation's -- that sweep reads every `files` row into its claimed set,
    so a stranded object never looked like an orphan to it. An earlier version
    of this docstring said otherwise, and the object would have stayed in the
    bucket for as long as the product ran.
    """
    purged, stranded = await retry_stranded(session, store, limit=limit)
    held = int((await session.execute(_HELD)).one().held)
    due = (await session.execute(_DUE, {"limit": limit})).all()

    for row in due:
        # Marked first. A crash between the mark and the delete leaves a row
        # that says what was supposed to happen, which is recoverable; the
        # reverse leaves a `ready` row with no bytes behind it, which is not.
        await session.execute(_MARK_PURGED, {"id": row.id})
        await session.commit()
        await session.execute(_PROVISIONING)

        try:
            store.delete(row.storage_key)
        except Exception:
            logger.exception("a file past its retention could not be removed from the bucket")
            stranded += 1
            continue

        await _record(
            session,
            row.tenant_id,
            row.id,
            "storage.object.purged",
            "ok",
            {"size_bytes": int(row.size_bytes)},
        )
        await session.execute(_PROVISIONING)
        await session.execute(_DELETE_ROW, {"id": row.id})
        await session.commit()
        await session.execute(_PROVISIONING)
        purged += 1

    return purged, held, stranded


async def _record(
    session: AsyncSession,
    tenant_id: str,
    file_id: str,
    action: str,
    outcome: str,
    details: dict[str, Any],
) -> None:
    """Record on the tenant's own context, then leave it to the caller to return.

    The audit table admits an insert only for the tenant the row belongs to,
    which is why a sweep holding cross-tenant reach has to become the tenant to
    write. `190_sweep_audit_write_isolation.sql` bounds this path.
    """
    await session.execute(_AS_TENANT, {"tenant_id": tenant_id})
    await session.execute(
        _AUDIT_INSERT,
        {
            "tenant_id": tenant_id,
            "action": action,
            "file_id": file_id,
            "outcome": outcome,
            "details": json.dumps(details),
            "class": "security" if action == "storage.purge.held" else "audit",
        },
    )
    await session.commit()


def _store() -> ObjectStore:
    destination = resolve_destination(
        None,
        StorageSettings(
            endpoint=lifecycle.storage_endpoint,
            bucket=lifecycle.storage_bucket,
            region=lifecycle.storage_region,
            access_key=lifecycle.storage_access_key,
            secret_key=lifecycle.storage_secret_key,
        ),
    )
    return S3ObjectStore(destination)


def _engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )


async def sweep_storage_lifecycle(ctx: dict[str, Any]) -> dict[str, Any]:
    """The nightly pass: resolve what has no date, remove what has passed one."""
    del ctx
    if not lifecycle.storage_lifecycle_enabled:
        return {"status": "skipped", "reason": "not enabled"}
    if not settings.database_url:
        logger.warning("storage lifecycle skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}
    if not lifecycle.storage_bucket or not lifecycle.storage_access_key:
        logger.warning("storage lifecycle skipped: the worker has no storage credentials")
        return {"status": "skipped", "reason": "no storage"}

    floors = floors_from(lifecycle)
    store = _store()
    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(_PROVISIONING)
            resolved = await resolve_retention(
                session, floors=floors, limit=lifecycle.storage_purge_limit
            )
            await session.execute(_PROVISIONING)
            extended = await extend_to_floor(session, floors=floors)
            await session.execute(_PROVISIONING)
            purged, held, stranded = await purge_expired(
                session, store, limit=lifecycle.storage_purge_limit
            )
    finally:
        await engine.dispose()

    logger.info(
        "storage lifecycle: %d resolved, %d extended, %d purged, "
        "%d kept by a legal hold, %d stranded",
        resolved,
        extended,
        purged,
        held,
        stranded,
    )
    return {
        "status": "ok",
        "resolved": resolved,
        "extended": extended,
        "purged": purged,
        "held": held,
        "stranded": stranded,
    }
