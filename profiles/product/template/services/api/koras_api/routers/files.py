"""The Files surface: what a tenant has stored, and the signed URLs to move it.

Four routes and no bytes. An upload is a row and a signed PUT; the browser
puts the object into the bucket itself and then confirms, at which point the
API checks the object is there and is the size that was promised. A download
is a signed GET with an attachment disposition. Credentials stay here; the
browser holds a URL that names one key and expires in minutes.

Who may do what is the caller's role, read from the token the same way the
sidebar reads it: every member lists, downloads and uploads; owners and
administrators delete. `files.manage` is the permission the registry names for
that, and `packages/permissions` is where the mapping lives -- this mirrors it
rather than importing it, because the two run in different languages, and the
generator's structural test is what keeps them agreeing.

Whether the tenant may store anything at all, and how much, is the platform's
answer, resolved in `core/storage.py`. An upload past the ceiling is refused
with 402 -- the one status that says "this is a commercial limit, not a
permission" -- and the page says which plan lifts it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from koras_platform import OrganizationRole
from koras_storage import object_key, safe_filename
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Row

from ..core.auth import AuthDep
from ..core.database import DbSession
from ..core.storage import STORAGE_ENTITLEMENT, StorageDep
from ..core.tenant import TenantDep

router = APIRouter(tags=["files"])

#: Signed URLs live this long. Long enough for a slow connection to finish
#: a large upload, short enough that a leaked URL is worth little.
UPLOAD_URL_SECONDS = 15 * 60
DOWNLOAD_URL_SECONDS = 5 * 60

#: One object, one request. Multipart uploads are a later phase; a file
#: larger than this is refused with a message rather than failing midway.
MAX_OBJECT_BYTES = 5 * 1024**3

_MANAGERS = (OrganizationRole.OWNER, OrganizationRole.ADMIN)


class FileRow(BaseModel):
    id: str
    name: str
    size_bytes: int
    content_type: str
    uploaded_by: str
    uploaded_at: datetime


class FileList(BaseModel):
    files: list[FileRow]
    used_bytes: int
    #: Null when the plan sets no ceiling, or the platform did not answer.
    limit_bytes: int | None
    provider: str
    #: Whether the platform answered. False means the product fell back to
    #: its defaults and the page should say so rather than show a quota.
    resolved: bool


class UploadRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=0, le=MAX_OBJECT_BYTES)
    content_type: str = Field(default="application/octet-stream", max_length=255)


class UploadTicket(BaseModel):
    file_id: str
    upload_url: str
    method: str = "PUT"
    #: The browser must send exactly these; they are part of the signature.
    headers: dict[str, str]
    expires_in: int


class DownloadTicket(BaseModel):
    url: str
    expires_in: int


def _require_grant(storage: StorageDep) -> None:
    if not storage.grant.enabled:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"this organization's plan does not include {STORAGE_ENTITLEMENT}",
        )


async def _used_bytes(session: DbSession, tenant_id: str) -> int:
    result = await session.execute(
        text(
            "select coalesce(sum(size_bytes), 0) from public.files "
            "where tenant_id = :tenant_id and status = 'ready'"
        ),
        {"tenant_id": tenant_id},
    )
    return int(result.scalar_one())


@router.get("/files", response_model=FileList)
async def list_files(tenant: TenantDep, storage: StorageDep, session: DbSession) -> FileList:
    """Every ready file this tenant holds, newest first, with the usage beside it.

    Listed even when the plan lacks the capability: a customer whose trial
    ended should see what they have and be told why they cannot add to it,
    not a blank page. Only new uploads are refused.
    """
    rows = await session.execute(
        text(
            "select id, name, size_bytes, content_type, uploaded_by, ready_at "
            "from public.files where tenant_id = :tenant_id and status = 'ready' "
            "order by ready_at desc"
        ),
        {"tenant_id": tenant.id},
    )
    return FileList(
        files=[
            FileRow(
                id=str(row.id),
                name=row.name,
                size_bytes=row.size_bytes,
                content_type=row.content_type,
                uploaded_by=row.uploaded_by,
                uploaded_at=row.ready_at,
            )
            for row in rows.fetchall()
        ],
        used_bytes=await _used_bytes(session, tenant.id),
        limit_bytes=storage.grant.limit_bytes,
        provider=storage.provider.value,
        resolved=storage.grant.resolved,
    )


@router.post("/files/uploads", response_model=UploadTicket, status_code=status.HTTP_201_CREATED)
async def request_upload(
    body: UploadRequest,
    claims: AuthDep,
    tenant: TenantDep,
    storage: StorageDep,
    session: DbSession,
) -> UploadTicket:
    """A place to put one file, and a row that says it is expected.

    The row is `pending` until `complete` confirms the object. The quota is
    checked here, against ready bytes plus this file, so a customer at the
    ceiling is told before uploading rather than after.
    """
    _require_grant(storage)
    limit = storage.grant.limit_bytes
    if limit is not None:
        used = await _used_bytes(session, tenant.id)
        if used + body.size_bytes > limit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="this upload would exceed the storage included in the plan",
            )

    file_id = str(uuid.uuid4())
    key = object_key(tenant.id, file_id, body.name)
    content_type = body.content_type or "application/octet-stream"
    await session.execute(
        text(
            "insert into public.files "
            "(id, tenant_id, storage_key, name, size_bytes, content_type, status, uploaded_by) "
            "values (:id, :tenant_id, :key, :name, :size, :content_type, 'pending', :who)"
        ),
        {
            "id": file_id,
            "tenant_id": tenant.id,
            "key": key,
            "name": safe_filename(body.name),
            "size": body.size_bytes,
            "content_type": content_type,
            "who": claims.sub,
        },
    )
    await session.commit()

    url = storage.store.presign_upload(key, content_type, body.size_bytes, UPLOAD_URL_SECONDS)
    return UploadTicket(
        file_id=file_id,
        upload_url=url,
        headers={"Content-Type": content_type},
        expires_in=UPLOAD_URL_SECONDS,
    )


@router.post("/files/{file_id}/complete", response_model=FileRow)
async def complete_upload(
    file_id: str, tenant: TenantDep, storage: StorageDep, session: DbSession
) -> FileRow:
    """The browser says it finished; the API checks the bucket agrees.

    The object's size must match the size the ticket was issued for. A
    mismatch means something other than the promised file was put there, and
    the row is removed rather than marked ready -- the object stays for the
    sweep, because deleting on a client's word is how a race loses a file.
    """
    row = await _pending(session, tenant.id, file_id)
    actual = storage.store.head(row.storage_key)
    if actual is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the object has not arrived in the bucket yet",
        )
    if actual != row.size_bytes:
        await session.execute(text("delete from public.files where id = :id"), {"id": file_id})
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the object in the bucket is not the size that was announced",
        )

    now = datetime.now(UTC)
    await session.execute(
        text("update public.files set status = 'ready', ready_at = :now where id = :id"),
        {"now": now, "id": file_id},
    )
    await session.commit()
    return FileRow(
        id=file_id,
        name=row.name,
        size_bytes=row.size_bytes,
        content_type=row.content_type,
        uploaded_by=row.uploaded_by,
        uploaded_at=now,
    )


@router.get("/files/{file_id}/download", response_model=DownloadTicket)
async def download(
    file_id: str, tenant: TenantDep, storage: StorageDep, session: DbSession
) -> DownloadTicket:
    row = await _ready(session, tenant.id, file_id)
    return DownloadTicket(
        url=storage.store.presign_download(row.storage_key, row.name, DOWNLOAD_URL_SECONDS),
        expires_in=DOWNLOAD_URL_SECONDS,
    )


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: str,
    claims: AuthDep,
    tenant: TenantDep,
    storage: StorageDep,
    session: DbSession,
) -> None:
    """Object first, then row: a row without an object is a pending upload the
    list already hides, and an object without a row is what the sweep finds."""
    if not claims.has_role(*_MANAGERS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="deleting files needs an owner or administrator",
        )
    row = await _ready(session, tenant.id, file_id)
    storage.store.delete(row.storage_key)
    await session.execute(text("delete from public.files where id = :id"), {"id": file_id})
    await session.commit()


async def _ready(session: DbSession, tenant_id: str, file_id: str) -> Row[Any]:
    return await _one(session, tenant_id, file_id, "ready")


async def _pending(session: DbSession, tenant_id: str, file_id: str) -> Row[Any]:
    return await _one(session, tenant_id, file_id, "pending")


async def _one(session: DbSession, tenant_id: str, file_id: str, state: str) -> Row[Any]:
    try:
        uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such file") from None
    result = await session.execute(
        text(
            "select id, storage_key, name, size_bytes, content_type, uploaded_by "
            "from public.files where id = :id and tenant_id = :tenant_id and status = :state"
        ),
        {"id": file_id, "tenant_id": tenant_id, "state": state},
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such file")
    return row
