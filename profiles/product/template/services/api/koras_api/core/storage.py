"""The bucket this request's tenant writes to, and how much it may hold.

Assembled once per request from three things the request already carries: the
resolved tenant, the caller's verified token, and the product's own settings.
The Control Plane's storage policy decides the provider and may name a bucket;
its entitlement resolution decides whether this customer has file storage at
all and how many gigabytes of it. Both are read through `core/platform.py`
with the caller's token, cached for a minute, and both fall back to something
honest when the platform is silent: the product's default bucket, and no gate.

No gate when the platform is unreachable is a decision, and it is the same one
the web tier makes for the Reports page. A customer who has paid for storage
and cannot reach it because the platform hiccupped is the worse outcome; the
platform's own reconciliation is what withdraws access from a customer who
stopped paying, and it does so by the entitlement disappearing on the next
successful read.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from koras_storage import (
    ObjectStore,
    Provider,
    S3ObjectStore,
    StoragePolicy,
    StorageSettings,
    Unsupported,
    resolve_destination,
)
from sqlalchemy.ext.asyncio import AsyncSession

from . import platform
from .errors import ApiErrorCode, api_error
from .settings import PRODUCT_CODE, settings
from .tenant import TenantDep

logger = logging.getLogger(__name__)

#: One object, one request. Multipart uploads are a later phase; a file larger
#: than this is refused with a message rather than failing midway.
#:
#: Here rather than in the route since 2026-09-19, because the settings that
#: narrow it are resolved here and two constants for one number is how they
#: come to disagree. The route imports it.
MAX_OBJECT_BYTES = 5 * 1024**3

#: The platform capability that gates the Files module. Named once here and
#: once in `packages/branding`'s navigation registry; the generator's
#: structural test asserts the two agree.
STORAGE_ENTITLEMENT = "storage.files"

_bearer = HTTPBearer(auto_error=True)


@dataclass(frozen=True)
class StorageGrant:
    """Whether this tenant may store files, and the ceiling in bytes."""

    enabled: bool
    limit_bytes: int | None
    #: False when the platform did not answer and the product fell back to
    #: "no gate". Surfaced so the page can say so rather than guess.
    resolved: bool


@dataclass(frozen=True)
class TenantStorage:
    store: ObjectStore
    provider: Provider
    bucket: str
    grant: StorageGrant


def _settings() -> StorageSettings:
    return StorageSettings(
        endpoint=settings.storage_endpoint,
        bucket=settings.storage_bucket,
        region=settings.storage_region,
        access_key=settings.storage_access_key,
        secret_key=settings.storage_secret_key,
        r2_access_key=settings.storage_r2_access_key,
        r2_secret_key=settings.storage_r2_secret_key,
        s3_access_key=settings.storage_s3_access_key,
        s3_secret_key=settings.storage_s3_secret_key,
    )


def _policy_from(body: dict[str, Any] | None) -> StoragePolicy | None:
    if body is None:
        return None
    try:
        provider = Provider(str(body.get("provider", "")))
    except ValueError:
        # A provider this build does not know. Refusing is `Unsupported`'s
        # job; here it is simply not a policy this product can read.
        return None
    config = body.get("config")
    return StoragePolicy(
        provider=provider,
        bucket=body.get("bucket") or None,
        region=body.get("region") or None,
        config=config if isinstance(config, dict) else {},
    )


def _grant_from(answer: platform.PortalAnswer | None) -> StorageGrant:
    if answer is None:
        return StorageGrant(enabled=True, limit_bytes=None, resolved=False)
    body = answer.body
    if body is None:
        # The platform answered and this organization holds no subscription to
        # this product: nothing is granted, and that is a real answer.
        return StorageGrant(enabled=False, limit_bytes=None, resolved=True)
    for row in body.get("entitlements", []) or []:
        if not isinstance(row, dict) or row.get("code") != STORAGE_ENTITLEMENT:
            continue
        limit = row.get("limit_value")
        return StorageGrant(
            enabled=bool(row.get("enabled")),
            limit_bytes=int(limit) * 1024**3 if isinstance(limit, int) and limit >= 0 else None,
            resolved=True,
        )
    return StorageGrant(enabled=False, limit_bytes=None, resolved=True)


async def tenant_storage(
    tenant: TenantDep,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> TenantStorage:
    """Resolve where this tenant's files go and whether they may go there.

    Two platform reads, both cached, both optional. The token is the caller's
    own, verified already by `AuthDep` on the way to `TenantDep`; it is
    forwarded, not re-minted, because the portal routes are addressed to the
    customer and a product is not entitled to a stronger identity (F2b).
    """
    token = credentials.credentials
    policy = await platform.read_portal(
        f"/api/portal/v1/products/{PRODUCT_CODE}/storage-policy",
        organization_id=tenant.organization_id,
        token=token,
    )
    entitlements = await platform.read_portal(
        f"/api/portal/v1/products/{PRODUCT_CODE}/entitlements",
        organization_id=tenant.organization_id,
        token=token,
    )

    try:
        destination = resolve_destination(
            _policy_from(policy.body if policy is not None else None), _settings()
        )
    except Unsupported as reason:
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE, ApiErrorCode.STORAGE_UNAVAILABLE, str(reason)
        ) from reason

    return TenantStorage(
        store=S3ObjectStore(destination),
        provider=destination.provider,
        bucket=destination.bucket,
        grant=_grant_from(entitlements),
    )


StorageDep = Annotated[TenantStorage, Depends(tenant_storage)]


# ── what a customer may upload ───────────────────────────────────────────────


@dataclass(frozen=True)
class UploadLimits:
    """The organisation's own ceiling on an upload, from the settings catalogue.

    Three settings were declared, translated into three languages and drawn on
    the settings page from the day the framework shipped, and **read by nothing
    at all** until 2026-09-19: the upload route applied a hardcoded 5 GiB and
    consulted none of them. A customer could tighten "Largest file" to 10 MB
    and watch a 2 GB upload succeed.

    Two of them are honoured here. `files.maxFilesPerUpload` is not, because
    there is no route to honour it on -- the ticket route mints one ticket for
    one file, and the browser uploads one at a time -- so it is unsurfaced
    rather than left offering something nothing can apply.
    """

    #: Bytes. Never above the hard ceiling: a setting widens nothing.
    max_bytes: int
    #: Lower-case, without the dot. Empty means every extension.
    extensions: tuple[str, ...]

    def refuses(self, name: str, size_bytes: int) -> str | None:
        """The reason this upload is refused, or nothing."""
        if size_bytes > self.max_bytes:
            return "size"
        if self.extensions:
            _, _, suffix = name.rpartition(".")
            if not suffix or suffix.lower() not in self.extensions:
                return "extension"
        return None


async def upload_limits(session: AsyncSession, tenant_id: str) -> UploadLimits:
    """Resolve the two enforceable file limits for this organisation.

    Resolved rather than read: the ladder is the organisation's value over the
    platform's over the definition's default, and doing it here with the
    framework's own resolver is what keeps the number the settings page shows
    and the number the route applies the same number.

    Never raises. A settings table that cannot be read gives the hard ceiling
    and no extension list, which is the behaviour the route had before any of
    this existed -- an upload page that fails because a preference lookup was
    unavailable would be a worse trade than one that is briefly permissive.
    """
    from koras_settings import resolve

    from ..settings_catalogue import catalogue
    from .settings_store import global_values, tenant_values

    megabytes = 5_000
    extensions: tuple[str, ...] = ()
    try:
        globals_ = await global_values(session)
        tenants_ = await tenant_values(session, tenant_id)
        # `resolve` answers the value *and* anything it skipped reaching it.
        # The skipped half is dropped here on purpose: a stored value that no
        # longer satisfies its own definition is already reported on the
        # settings page, and an upload is not the place to learn about it.
        size, _ = resolve(
            catalogue.require("files.maxUploadSizeMb"),
            global_values=globals_,
            organization_values=tenants_,
            member_values={},
        )
        allowed, _ = resolve(
            catalogue.require("files.allowedExtensions"),
            global_values=globals_,
            organization_values=tenants_,
            member_values={},
        )
        if isinstance(size.value, int) and not isinstance(size.value, bool):
            megabytes = size.value
        if isinstance(allowed.value, (list, tuple)):
            extensions = tuple(
                str(item).strip().lstrip(".").lower()
                for item in allowed.value
                if str(item).strip()
            )
    except Exception:  # noqa: BLE001 - a preference lookup must not fail an upload
        logger.exception("the upload limits could not be resolved; using the ceiling")

    # A setting narrows and never widens: the 5 GiB ceiling is about what the
    # provider and this service can carry, and no customer preference changes
    # that.
    return UploadLimits(
        max_bytes=min(megabytes * 1024 * 1024, MAX_OBJECT_BYTES), extensions=extensions
    )
