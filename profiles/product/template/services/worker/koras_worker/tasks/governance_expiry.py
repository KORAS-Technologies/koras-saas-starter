"""Dates the product set itself, honoured without waiting for anybody to look.

Two sweeps, together because they share the defect they exist to close: in both
cases the product displayed an expiry and then depended on a person opening a
screen for anything to happen at it.

An export is a copy of a tenant's audit history sitting in a bucket. It is
given an expiry when it is created, and until this sweep existed that expiry
was honoured in exactly two places: the download route refused a stale one, and
the exports list retired anything expired *while somebody was looking at it*.

The second is the defect. A tenant that produced exports and then stopped
opening the page kept every artifact it had ever made, indefinitely, while the
product showed an expiry date on each. A retention promise that depends on a
customer visiting a screen is not a retention promise.

**The row goes only after the object does.** A bucket that refuses the delete
leaves the row, so the next run tries again -- the opposite order would leave
bytes nobody has a record of.

**It never touches an export that is not `ready`.** A `pending` row is a
request still being written by an API process; deleting it underneath that
process is a race with a customer's download on the other end.

The second sweep closes a bounded legal hold. Enforcement was never wrong --
`under_legal_hold` has read `ends_at` since migration 00020, so a hold past its
end date stopped holding on the day it said it would. The label was wrong: the
row went on reading `active` for ever, so the holds list showed holds that held
nothing and the platform's governance counts overstated how much of the estate
was under hold. The database policy behind it can only move such a row into
`expired`; releasing and activating stay decisions with a person behind them.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from koras_storage import ObjectStore, S3ObjectStore, StorageSettings, resolve_destination
from pydantic_settings import SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..settings import SweepSettings, settings


class ExportExpirySettings(SweepSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    #: On by default, unlike the other two sweeps. Those delete a customer's
    #: own content; this deletes an artifact the product generated, with a
    #: date the product itself set and displayed. Leaving it off would mean
    #: shipping an expiry that does not expire.
    audit_export_expiry_enabled: bool = True

    #: A ceiling per run. A misconfigured expiry should not be able to empty
    #: the prefix in one night without anybody getting a chance to look.
    audit_export_expiry_limit: int = 500

    storage_endpoint: str = ""
    storage_bucket: str = ""
    storage_region: str = ""
    storage_access_key: str = ""
    storage_secret_key: str = ""


expiry = ExportExpirySettings()

logger = logging.getLogger(__name__)

_PROVISIONING = text("select set_config('app.provisioning', 'on', true)")
_AS_TENANT = text(
    "select set_config('app.provisioning', '', true), set_config('app.tenant_id', :tenant_id, true)"
)
_DUE = text(
    "select id::text as id, tenant_id::text as tenant_id, storage_key, format "
    "from public.audit_exports "
    "where status = 'ready' and storage_key is not null "
    "  and expires_at is not null and expires_at < now() "
    "order by expires_at limit :limit"
)
_DELETE = text("delete from public.audit_exports where id = cast(:id as uuid)")
_AUDIT_INSERT = text(
    "insert into public.audit_events "
    " (tenant_id, actor_id, action, target_type, target_id, outcome, details, classification) "
    "values (cast(:tenant_id as uuid), 'system', 'audit.export_expired', "
    " 'audit_export', :target_id, 'ok', cast(:details as jsonb), 'audit')"
)


def _store() -> ObjectStore:
    destination = resolve_destination(
        None,
        StorageSettings(
            endpoint=expiry.storage_endpoint,
            bucket=expiry.storage_bucket,
            region=expiry.storage_region,
            access_key=expiry.storage_access_key,
            secret_key=expiry.storage_secret_key,
        ),
    )
    return S3ObjectStore(destination)


def _engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )


async def _record(session: AsyncSession, tenant_id: str, export_id: str, fmt: str) -> None:
    """One audit row per retirement, written on that tenant's own context.

    The audit table admits an insert only for the tenant the row belongs to, so
    the sweep steps out of the provisioning context to write and the caller
    puts it back. The format, never the key: an object key is half a signed URL.
    """
    await session.execute(_AS_TENANT, {"tenant_id": tenant_id})
    await session.execute(
        _AUDIT_INSERT,
        {
            "tenant_id": tenant_id,
            "target_id": export_id,
            "details": json.dumps({"format": fmt}),
        },
    )


async def expire_audit_exports(ctx: dict[str, Any]) -> dict[str, Any]:
    """Remove every artifact whose expiry has passed. Object first, then row."""
    del ctx
    if not expiry.audit_export_expiry_enabled:
        return {"status": "skipped", "reason": "not enabled"}
    if not settings.database_url:
        logger.warning("audit export expiry skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}
    if not expiry.storage_bucket or not expiry.storage_access_key:
        logger.warning("audit export expiry skipped: the worker has no storage credentials")
        return {"status": "skipped", "reason": "no storage"}

    store = _store()
    engine = _engine()
    retired = 0
    stuck = 0
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(_PROVISIONING)
            due = (await session.execute(_DUE, {"limit": expiry.audit_export_expiry_limit})).all()
            for row in due:
                try:
                    store.delete(row.storage_key)
                except Exception:
                    # A bucket that will not delete is a leak to report, not a
                    # reason to drop the row that records the object exists.
                    logger.warning("an expired audit export could not be removed from the bucket")
                    stuck += 1
                    continue
                await session.execute(_DELETE, {"id": row.id})
                await _record(session, row.tenant_id, row.id, row.format)
                await session.commit()
                await session.execute(_PROVISIONING)
                retired += 1
    finally:
        await engine.dispose()

    logger.info(
        "audit export expiry: %d artifact(s) retired, %d the bucket would not remove",
        retired,
        stuck,
    )
    return {"status": "ok", "retired": retired, "stuck": stuck}


_EXPIRABLE_HOLDS = text(
    "select id::text as id, tenant_id::text as tenant_id, scope from public.legal_holds "
    "where status = 'active' and ends_at is not null and ends_at < now() "
    "order by ends_at limit :limit"
)
_EXPIRE_HOLD = text(
    "update public.legal_holds set status = 'expired' where id = cast(:id as uuid)"
)
_HOLD_AUDIT = text(
    "insert into public.audit_events "
    " (tenant_id, actor_id, action, target_type, target_id, outcome, details, classification) "
    "values (cast(:tenant_id as uuid), 'system', 'hold.expired', "
    " 'hold', :target_id, 'ok', cast(:details as jsonb), 'administrative')"
)


async def expire_legal_holds(ctx: dict[str, Any]) -> dict[str, Any]:
    """Close out bounded holds whose end date has passed.

    Always on, and it takes no storage credentials: this changes a label, not
    a byte. It is also the one sweep here that cannot lose anything -- the row
    it touches already stopped holding on the day `ends_at` named.
    """
    del ctx
    if not settings.database_url:
        logger.warning("legal hold expiry skipped: the worker has no DATABASE_URL")
        return {"status": "skipped", "reason": "no database"}

    engine = _engine()
    expired = 0
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(_PROVISIONING)
            due = (
                await session.execute(
                    _EXPIRABLE_HOLDS, {"limit": expiry.audit_export_expiry_limit}
                )
            ).all()
            for row in due:
                await session.execute(_EXPIRE_HOLD, {"id": row.id})
                # On the tenant's own context, like every other audit insert a
                # sweep makes: the table admits a row only for the tenant it
                # belongs to, and the scope is a category, never a matter.
                await session.execute(_AS_TENANT, {"tenant_id": row.tenant_id})
                await session.execute(
                    _HOLD_AUDIT,
                    {
                        "tenant_id": row.tenant_id,
                        "target_id": row.id,
                        "details": json.dumps({"scope": row.scope, "reason": "ends_at"}),
                    },
                )
                await session.commit()
                await session.execute(_PROVISIONING)
                expired += 1
    finally:
        await engine.dispose()

    logger.info("legal hold expiry: %d bounded hold(s) closed out", expired)
    return {"status": "ok", "expired": expired}
