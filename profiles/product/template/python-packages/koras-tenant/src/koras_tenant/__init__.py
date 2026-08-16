from __future__ import annotations
from dataclasses import dataclass
from koras_auth import JWTClaims


@dataclass
class TenantContext:
    id: str
    slug: str
    name: str


async def resolve_tenant(claims: JWTClaims) -> TenantContext | None:
    if not claims.tenant_id:
        return None
    # In production, look up tenant by ZITADEL org ID from database
    return TenantContext(
        id=claims.tenant_id,
        slug=claims.tenant_id,
        name=claims.tenant_id,
    )
