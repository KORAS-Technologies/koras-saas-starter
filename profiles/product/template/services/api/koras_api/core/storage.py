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

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
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

from . import platform
from .settings import PRODUCT_CODE, settings
from .tenant import TenantDep

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
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(reason)
        ) from reason

    return TenantStorage(
        store=S3ObjectStore(destination),
        provider=destination.provider,
        bucket=destination.bucket,
        grant=_grant_from(entitlements),
    )


StorageDep = Annotated[TenantStorage, Depends(tenant_storage)]
