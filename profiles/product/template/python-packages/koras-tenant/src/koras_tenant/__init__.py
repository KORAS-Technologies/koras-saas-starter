from __future__ import annotations

from dataclasses import dataclass

from koras_auth import JWTClaims


@dataclass
class TenantContext:
    id: str
    slug: str
    name: str


async def resolve_tenant(claims: JWTClaims) -> TenantContext | None:
    if not claims.organization_id:
        return None
    # In production, look up tenant by ZITADEL org ID from database
    return TenantContext(
        id=claims.organization_id,
        slug=claims.organization_id,
        name=claims.organization_id,
    )
