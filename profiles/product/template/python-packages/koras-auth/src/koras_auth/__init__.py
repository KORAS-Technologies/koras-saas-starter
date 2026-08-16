from __future__ import annotations

import httpx
from jose import jwt, JWTError
from dataclasses import dataclass


@dataclass
class JWTClaims:
    sub: str
    email: str
    name: str | None
    roles: list[str]
    tenant_id: str | None


async def verify_jwt(
    token: str,
    zitadel_domain: str,
    project_id: str,
) -> JWTClaims | None:
    try:
        jwks = await _fetch_jwks(zitadel_domain)
        payload = jwt.decode(token, jwks, algorithms=["RS256"], audience=project_id)
        return JWTClaims(
            sub=payload["sub"],
            email=payload.get("email", ""),
            name=payload.get("name"),
            roles=payload.get("urn:zitadel:iam:org:project:roles", []),
            tenant_id=payload.get("urn:zitadel:iam:org:id"),
        )
    except JWTError:
        return None


async def _fetch_jwks(zitadel_domain: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{zitadel_domain}/.well-known/openid-configuration")
        config = response.json()
        jwks_response = await client.get(config["jwks_uri"])
        return jwks_response.json()
