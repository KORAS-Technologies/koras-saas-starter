"""The gate that applies the release rule to a request (ADR 0013, `secure_files`).

The rule itself is `core/file_release.py`, which is dependency-free so the
worker's image can carry it. This is the API-only half: it loads the tenant's
row, asks the rule, and on a refusal records one security event and raises the
product-safe answer. Nothing is signed or fetched before it returns.

**Only generated with the capability.** Every consumer that reads bytes in a product
with `secure_files` goes through `require_releasable` (a person's request, which signs a
URL) or `read_releasable` (a process that reads the object itself, such as the assistant's
indexer). Both load the row by tenant and id, ask `file_release.releasable` with the row's
own identity, and only then touch the bucket.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from . import release_audit
from .audit import record
from .errors import ApiErrorCode, api_error
from .file_release import Consumer, refusal_reason, releasable

_ONE = text(
    "select id, tenant_id::text as tenant_id, storage_key, name, size_bytes, content_type, "
    " uploaded_by, scan_status, scan_object_etag, status, legal_hold, created_at "
    "from public.files where id = cast(:id as uuid) and tenant_id = cast(:tenant_id as uuid)"
)


def row_releasable(row: Row[Any], tenant_id: str, consumer: Consumer) -> bool:
    """The rule, asked of one loaded row for the tenant that is acting.

    The one place a row's columns are turned into the rule's arguments, so no consumer
    can forget one of the identity fields.
    """
    return releasable(
        status=row.status,
        scan_status=row.scan_status,
        consumer=consumer,
        tenant_id=tenant_id,
        row_tenant_id=row.tenant_id,
        storage_key=row.storage_key,
        scan_object_etag=row.scan_object_etag,
    )


async def _refuse(
    session: AsyncSession,
    row: Row[Any],
    *,
    tenant_id: str,
    file_id: str,
    actor_id: str,
    consumer: Consumer,
) -> str:
    """Record one denied event for a refusal and return its closed reason."""
    reason = refusal_reason(status=row.status, scan_status=row.scan_status)
    await record(
        session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=(
            "storage.object.quarantined"
            if reason == "infected"
            else release_audit.OBJECT_RELEASE_REFUSED
        ),
        target_type="file",
        target_id=file_id,
        outcome="denied",
        details={"reason": reason, "consumer": consumer},
    )
    return reason


async def require_releasable(
    session: AsyncSession,
    tenant_id: str,
    file_id: str,
    *,
    actor_id: str,
    consumer: Consumer,
) -> Row[Any]:
    """The tenant's file row, if and only if its content may be released.

    Loaded by tenant and id, so another tenant's file is `file_not_found`
    exactly as an unknown one is. A refusal records one security event --
    tenant, actor, file id, reason and consumer, never a name or a scan note --
    and then raises:

    - `infected` or quarantined: 403 `file_quarantined`;
    - `pending`, `skipped`, not recognised, or an identity that does not hold:
      409 `file_scan_pending`.

    Nothing is signed or fetched before this returns.
    """
    try:
        uuid.UUID(file_id)
    except ValueError:
        raise api_error(404, ApiErrorCode.FILE_NOT_FOUND, "no such file") from None
    row = (await session.execute(_ONE, {"id": file_id, "tenant_id": tenant_id})).first()
    if row is None or row.status not in ("ready", "quarantined"):
        raise api_error(404, ApiErrorCode.FILE_NOT_FOUND, "no such file")
    if row_releasable(row, tenant_id, consumer):
        return row
    reason = await _refuse(
        session, row, tenant_id=tenant_id, file_id=file_id, actor_id=actor_id, consumer=consumer
    )
    if reason == "infected":
        raise api_error(403, ApiErrorCode.FILE_QUARANTINED, "this file is not available")
    raise api_error(
        409,
        ApiErrorCode.FILE_SCAN_PENDING,
        "this file is still being checked and is not available yet"
        if reason == "pending"
        else "this file is not available",
    )


class ObjectLike(Protocol):
    def get(self, key: str) -> bytes | None: ...


async def read_releasable(
    session: AsyncSession,
    store: ObjectLike,
    tenant_id: str,
    file_id: str,
    *,
    actor_id: str,
    consumer: Consumer,
) -> tuple[Row[Any], bytes | None] | None:
    """The file's row and its bytes, if and only if its content may be released.

    For a consumer that reads the object itself rather than handing a URL to a
    person: the assistant's indexer. The rule is asked on the row just loaded and
    the object is read only on a yes, so a file that is not `clean` costs no
    bucket read and no byte reaches a model. Another tenant's file, an unknown id
    and a malformed id are all `None`, as is every state `releasable()` refuses.

    The bytes are `None` when the object is not in the bucket, which is a failure to
    read and not a refusal. A refusal records one event, with the closed reason and the
    consumer and nothing else -- the same shape as the download gate's -- and answers
    `None` rather than raising: this runs after a response, where nobody can act on an
    exception. It is rare by construction (the caller offers only releasable files), so
    it is a race with a verdict, which is worth one row.
    """
    try:
        uuid.UUID(file_id)
    except ValueError:
        return None
    row = (await session.execute(_ONE, {"id": file_id, "tenant_id": tenant_id})).first()
    if row is None:
        return None
    if not row_releasable(row, tenant_id, consumer):
        await _refuse(
            session, row, tenant_id=tenant_id, file_id=file_id, actor_id=actor_id, consumer=consumer
        )
        return None
    # `store.get` is synchronous and `S3ObjectStore.get` blocks on the network.
    raw = await asyncio.to_thread(store.get, row.storage_key)
    return row, raw


__all__ = ["read_releasable", "require_releasable", "row_releasable"]
