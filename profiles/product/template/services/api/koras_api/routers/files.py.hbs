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

import base64
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from koras_audit import Outcome
from koras_platform import OrganizationRole
from koras_storage import Category, object_key, safe_filename
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Row

from ..core.audit import record
from ..core.auth import AuthDep
from ..core.database import DbSession
from ..core.errors import ApiErrorCode, api_error
from ..core.file_hooks import hooks, run_after_upload
from ..core.file_scan import withheld
from ..core.storage import (
    MAX_OBJECT_BYTES,
    STORAGE_ENTITLEMENT,
    StorageDep,
    upload_limits,
)
from ..core.tenant import TenantDep

router = APIRouter(tags=["files"])

_bearer = HTTPBearer(auto_error=False)
CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]

#: Retrieval indexes uploads only where the product has an AI gateway; a
#: product generated without the capability has neither the setting nor the
#: tables, and this reads as False there.

#: Signed URLs live this long. Long enough for a slow connection to finish
#: a large upload, short enough that a leaked URL is worth little.
UPLOAD_URL_SECONDS = 15 * 60
DOWNLOAD_URL_SECONDS = 5 * 60


_MANAGERS = (OrganizationRole.OWNER, OrganizationRole.ADMIN)


class FileRow(BaseModel):
    id: str
    name: str
    size_bytes: int
    content_type: str
    uploaded_by: str
    uploaded_at: datetime
    #: The digest, and whether anyone but the client vouched for it. Two
    #: fields rather than one, so a reader is never left guessing whether a
    #: hash was measured or merely claimed.
    checksum_sha256: str | None = None
    checksum_verified: bool = False
    #: pending, clean, infected or skipped. `pending` where no scanner is
    #: installed, which is the starter's own state.
    scan_status: str = "pending"
    #: When the assistant's index took the file's text, or why it did not.
    indexed_at: datetime | None = None
    index_note: str | None = None


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
    #: The digest of the bytes about to be sent, where the browser could take
    #: one. Signed into the upload URL, so the provider stores it and can be
    #: asked for it afterwards -- which is the only way corroboration is
    #: possible at all. It also makes the provider refuse bytes that do not
    #: match, so a corrupted transfer fails at the bucket rather than arriving
    #: as a file whose claim nobody can check.
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    #: Which shelf the object goes on. Two of the eight are offered to a
    #: caller: a document, which is what a person uploads on the Files page,
    #: and an import source. The rest -- exports, generated, archives, temp --
    #: are written by the product about itself, and a caller that could choose
    #: one could hide a file among the artefacts a sweep may remove.
    category: Literal["documents", "imports"] = "documents"


class CompleteRequest(BaseModel):
    """What the browser says about the upload it has just finished.

    The digest is optional and is the client's claim about the bytes it sent.
    It is recorded as a claim -- see `checksum_verified_at`, which this route
    does not set -- because a client asserting a hash of its own upload proves
    only that the client is consistent with itself. It is still worth having:
    it detects a file that changed on disk between two uploads, and it gives a
    later verification something to compare against.
    """

    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


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


async def _record(
    session: DbSession,
    *,
    tenant_id: str,
    actor_id: str,
    action: str,
    target_id: str,
    outcome: Outcome,
    details: dict[str, str | int | bool] | None = None,
) -> None:
    """Record one storage event. Everything here targets a file.

    Never `storage_key`: `koras_audit` refuses a detail whose name contains
    `key`, and the object key is half a signed URL anyway. The file id is
    what a later question is asked about.
    """
    await record(
        session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        target_type="file",
        target_id=target_id,
        outcome=outcome,
        details=details,
    )


def _b64(hex_digest: str) -> str:
    """A hex SHA-256 as the base64 the S3 protocol carries in its header."""
    return base64.b64encode(bytes.fromhex(hex_digest)).decode("ascii")


def _require_grant(storage: StorageDep) -> None:
    if not storage.grant.enabled:
        raise api_error(
            status.HTTP_402_PAYMENT_REQUIRED,
            ApiErrorCode.ENTITLEMENT_MISSING,
            f"this organization's plan does not include {STORAGE_ENTITLEMENT}",
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
            "select id, name, size_bytes, content_type, uploaded_by, ready_at, "
            " indexed_at, index_note "
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
                indexed_at=row.indexed_at,
                index_note=row.index_note,
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
    if not storage.grant.enabled:
        await _record(
            session,
            tenant_id=tenant.id,
            actor_id=claims.sub,
            action="storage.upload.refused",
            target_id="-",
            outcome="denied",
            details={"reason": "entitlement", "size_bytes": body.size_bytes},
        )
    _require_grant(storage)

    # The organisation's own ceiling, resolved from the settings catalogue.
    # Three settings were drawn on the settings page and read by nothing at all
    # until 2026-09-19: a customer could set "Largest file" to 10 MB and watch
    # a 2 GB upload succeed. Checked before the quota because it is the cheaper
    # refusal and the more specific sentence.
    limits = await upload_limits(session, tenant.id)
    refusal = limits.refuses(body.name, body.size_bytes)
    if refusal is not None:
        await _record(
            session,
            tenant_id=tenant.id,
            actor_id=claims.sub,
            action="storage.upload.refused",
            target_id="-",
            outcome="denied",
            details={"reason": refusal, "size_bytes": body.size_bytes},
        )
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ApiErrorCode.UPLOAD_REFUSED_BY_POLICY,
            (
                "this file is larger than the organisation allows"
                if refusal == "size"
                else "this organisation does not allow that kind of file"
            ),
        )

    limit = storage.grant.limit_bytes
    if limit is not None:
        used = await _used_bytes(session, tenant.id)
        if used + body.size_bytes > limit:
            await _record(
                session,
                tenant_id=tenant.id,
                actor_id=claims.sub,
                action="storage.upload.refused",
                target_id="-",
                outcome="denied",
                details={"reason": "quota", "size_bytes": body.size_bytes},
            )
            raise api_error(
                status.HTTP_402_PAYMENT_REQUIRED,
                ApiErrorCode.STORAGE_LIMIT_EXCEEDED,
                "this upload would exceed the storage included in the plan",
            )

    file_id = str(uuid.uuid4())
    key = object_key(tenant.id, file_id, body.name, category=Category(body.category))
    content_type = body.content_type or "application/octet-stream"
    await session.execute(
        text(
            "insert into public.files "
            "(id, tenant_id, storage_key, name, size_bytes, content_type, category, "
            "status, uploaded_by) "
            "values (:id, :tenant_id, :key, :name, :size, :content_type, :category, "
            "'pending', :who)"
        ),
        {
            "id": file_id,
            "tenant_id": tenant.id,
            "key": key,
            "name": safe_filename(body.name),
            "size": body.size_bytes,
            "content_type": content_type,
            "category": body.category,
            "who": claims.sub,
        },
    )
    await session.commit()

    url = storage.store.presign_upload(
        key, content_type, body.size_bytes, UPLOAD_URL_SECONDS, body.checksum_sha256
    )
    headers = {"Content-Type": content_type}
    if body.checksum_sha256:
        # Part of the signature, so the browser must send exactly this.
        headers["x-amz-checksum-sha256"] = _b64(body.checksum_sha256)
    return UploadTicket(
        file_id=file_id,
        upload_url=url,
        headers=headers,
        expires_in=UPLOAD_URL_SECONDS,
    )


@router.post("/files/{file_id}/complete", response_model=FileRow)
async def complete_upload(
    file_id: str,
    body: CompleteRequest,
    tenant: TenantDep,
    claims: AuthDep,
    storage: StorageDep,
    session: DbSession,
    background: BackgroundTasks,
    credentials: CredentialsDep,
) -> FileRow:
    """The browser says it finished; the API checks the bucket agrees.

    The object's size must match the size the ticket was issued for. A
    mismatch means something other than the promised file was put there, and
    the row is removed rather than marked ready -- the object stays for the
    sweep, because deleting on a client's word is how a race loses a file.

    The quota is checked again here, and not only when the ticket was issued.
    Two tickets taken out together were each within the limit and together
    over it, and nothing between the two checks stopped the second: the
    ceiling was advisory until 2026-09-15. A confirmation that would cross it
    is refused the way the ticket would have been, and its row goes the way a
    size mismatch's does.
    """
    row = await _pending(session, tenant.id, file_id)
    actual = storage.store.head(row.storage_key)
    if actual is None:
        await _record(
            session,
            tenant_id=tenant.id,
            actor_id=claims.sub,
            action="storage.upload.failed",
            target_id=file_id,
            outcome="failed",
            details={"reason": "not_arrived"},
        )
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiErrorCode.UPLOAD_NOT_ARRIVED,
            "the object has not arrived in the bucket yet",
        )
    if actual != row.size_bytes:
        await session.execute(text("delete from public.files where id = :id"), {"id": file_id})
        await session.commit()
        await _record(
            session,
            tenant_id=tenant.id,
            actor_id=claims.sub,
            action="storage.upload.failed",
            target_id=file_id,
            outcome="failed",
            details={"reason": "size_mismatch", "announced": row.size_bytes, "found": actual},
        )
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiErrorCode.UPLOAD_SIZE_MISMATCH,
            "the object in the bucket is not the size that was announced",
        )

    limit = storage.grant.limit_bytes
    if limit is not None:
        used = await _used_bytes(session, tenant.id)
        if used + row.size_bytes > limit:
            await session.execute(text("delete from public.files where id = :id"), {"id": file_id})
            await session.commit()
            await _record(
                session,
                tenant_id=tenant.id,
                actor_id=claims.sub,
                action="storage.upload.refused",
                target_id=file_id,
                outcome="denied",
                details={"reason": "quota_at_confirm", "size_bytes": row.size_bytes},
            )
            raise api_error(
                status.HTTP_402_PAYMENT_REQUIRED,
                ApiErrorCode.STORAGE_LIMIT_EXCEEDED,
                "this upload would exceed the storage included in the plan",
            )

    # The provider's own digest, where it will give one. A multipart object's
    # entity tag is a digest of digests and `checksum()` answers None for it,
    # so corroboration is attempted and never assumed.
    now = datetime.now(UTC)
    provider_digest = storage.store.checksum(row.storage_key)
    claimed = body.checksum_sha256
    corroborated = (
        claimed is not None and provider_digest is not None and claimed == provider_digest
    )
    verified_at = now if corroborated else None

    await session.execute(
        text(
            "update public.files set status = 'ready', ready_at = :now, "
            " checksum_sha256 = :checksum, checksum_verified_at = :verified "
            "where id = :id"
        ),
        {"now": now, "id": file_id, "checksum": claimed, "verified": verified_at},
    )
    await session.commit()
    await _record(
        session,
        tenant_id=tenant.id,
        actor_id=claims.sub,
        action="storage.object.uploaded",
        target_id=file_id,
        outcome="ok",
        details={
            "size_bytes": row.size_bytes,
            "content_type": row.content_type,
            # Whether the digest was claimed, corroborated, or absent. Never
            # the digest itself: it is not a secret, but an audit row is not
            # where a file's contents get fingerprinted for later matching.
            "integrity": (
                "verified" if verified_at else "claimed" if claimed else "none"
            ),
        },
    )
    interested = hooks.for_upload(row.content_type) if credentials is not None else ()
    if interested and credentials is not None:
        # A type something registered an interest in -- text a model can read,
        # or bytes a scanner wants -- so worth handing on after the response.
        # One signed URL for all of them, and none at all when nothing wants
        # the file: a signed URL is a bearer credential, so minting one that
        # nobody reads is a credential in flight for no reason.
        url = storage.store.presign_download(row.storage_key, row.name, DOWNLOAD_URL_SECONDS)
        for hook in interested:
            background.add_task(
                run_after_upload,
                hook,
                tenant_id=tenant.id,
                organization_id=tenant.organization_id,
                token=credentials.credentials,
                file_id=file_id,
                name=row.name,
                content_type=row.content_type,
                url=url,
                user_id=claims.sub,
            )
    return FileRow(
        id=file_id,
        name=row.name,
        size_bytes=row.size_bytes,
        content_type=row.content_type,
        uploaded_by=row.uploaded_by,
        uploaded_at=now,
        checksum_sha256=claimed,
        checksum_verified=verified_at is not None,
    )


@router.get("/files/{file_id}/download", response_model=DownloadTicket)
async def download(
    file_id: str,
    claims: AuthDep,
    tenant: TenantDep,
    storage: StorageDep,
    session: DbSession,
) -> DownloadTicket:
    """A signed URL for one object, and a record that it was asked for.

    The record is of the ticket, not of the bytes: the browser fetches the
    object from the bucket, so the product never sees the transfer. A ticket
    issued is the last thing this side can honestly claim to know.
    """
    row = await _ready(session, tenant.id, file_id)
    if withheld(row.scan_status):
        # Server-side, before the URL is signed. A scan result the page
        # consults and the API does not is a suggestion, not a control.
        await _record(
            session,
            tenant_id=tenant.id,
            actor_id=claims.sub,
            action="storage.object.quarantined",
            target_id=file_id,
            outcome="denied",
            details={"reason": "scan"},
        )
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.FILE_QUARANTINED,
            "this file is withheld: a scan did not find it clean",
        )
    await _record(
        session,
        tenant_id=tenant.id,
        actor_id=claims.sub,
        action="storage.object.downloaded",
        target_id=file_id,
        outcome="ok",
        details={"size_bytes": row.size_bytes},
    )
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
        await _record(
            session,
            tenant_id=tenant.id,
            actor_id=claims.sub,
            action="storage.object.delete_refused",
            target_id=file_id,
            outcome="denied",
            details={"reason": "role"},
        )
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.ROLE_REQUIRED,
            "deleting files needs an owner or administrator",
        )
    row = await _ready(session, tenant.id, file_id)

    # A hold outranks the person as well as the schedule. The sweeps have
    # excluded held rows since 00020 and this route did not, which protected
    # the file from the machine and not from the administrator -- the wrong way
    # round, because the actor a hold exists to constrain is the one who can
    # decide to delete. Found by review on 2026-09-16.
    held = bool(row.legal_hold) or bool(
        (
            await session.execute(
                text("select public.under_legal_hold(cast(:tenant_id as uuid), 'files') as held"),
                {"tenant_id": tenant.id},
            )
        ).one().held
    )
    if held:
        await _record(
            session,
            tenant_id=tenant.id,
            actor_id=claims.sub,
            action="storage.purge.held",
            target_id=file_id,
            outcome="denied",
            details={"reason": "legal_hold", "by": "person"},
        )
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiErrorCode.FILE_UNDER_HOLD,
            "this file is under a legal hold and cannot be deleted",
        )

    storage.store.delete(row.storage_key)
    for hook in hooks.for_delete():
        undo = hook.before_delete
        if undo is not None:
            await undo(session, tenant.id, file_id)
    await session.execute(text("delete from public.files where id = :id"), {"id": file_id})
    await session.commit()
    await _record(
        session,
        tenant_id=tenant.id,
        actor_id=claims.sub,
        action="storage.object.deleted",
        target_id=file_id,
        outcome="ok",
        details={"size_bytes": row.size_bytes, "content_type": row.content_type},
    )


async def _ready(session: DbSession, tenant_id: str, file_id: str) -> Row[Any]:
    return await _one(session, tenant_id, file_id, "ready")


async def _pending(session: DbSession, tenant_id: str, file_id: str) -> Row[Any]:
    return await _one(session, tenant_id, file_id, "pending")


async def _one(session: DbSession, tenant_id: str, file_id: str, state: str) -> Row[Any]:
    try:
        uuid.UUID(file_id)
    except ValueError:
        raise api_error(
            status.HTTP_404_NOT_FOUND, ApiErrorCode.FILE_NOT_FOUND, "no such file"
        ) from None
    result = await session.execute(
        text(
            "select id, storage_key, name, size_bytes, content_type, uploaded_by, scan_status, "
            " legal_hold "
            "from public.files where id = :id and tenant_id = :tenant_id and status = :state"
        ),
        {"id": file_id, "tenant_id": tenant_id, "state": state},
    )
    row = result.first()
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, ApiErrorCode.FILE_NOT_FOUND, "no such file")
    return row
