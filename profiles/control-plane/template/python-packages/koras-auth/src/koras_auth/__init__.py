"""ZITADEL token verification.

Turns a bearer token into the claims a service can authorise against. Only
verification lives here; the authorisation decision belongs to the caller.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from jose import JWTError, jwt
from koras_platform import OrganizationRole, is_organization_role

__all__ = [
    "ORGANIZATION_CLAIM",
    "ROLES_CLAIM",
    "JWKSCache",
    "JWTClaims",
    "TokenVerificationError",
    "verify_token",
]

# ZITADEL emits project roles as an OBJECT keyed by role name, whose values map
# organization id to domain. Reading it as a list yields nothing, and every role
# check then fails closed while looking like a configuration problem.
ROLES_CLAIM = "urn:zitadel:iam:org:project:roles"
ORGANIZATION_CLAIM = "urn:zitadel:iam:org:id"
AMR_CLAIM = "amr"

_MFA_METHODS = frozenset({"mfa", "otp", "u2f", "hwk", "sc", "totp", "webauthn"})


class TokenVerificationError(Exception):
    """The token could not be verified, or carries no usable identity.

    Distinct from an authorisation failure on purpose: the caller maps this to
    401, and a verified caller lacking a role to 403. Collapsing the two tells
    an attacker which tokens are real.
    """


@dataclass(frozen=True)
class JWTClaims:
    sub: str
    email: str | None = None
    name: str | None = None
    roles: frozenset[OrganizationRole] = field(default_factory=frozenset)
    unknown_roles: frozenset[str] = field(default_factory=frozenset)
    organization_id: str | None = None
    used_mfa: bool = False

    def has_role(self, *roles: OrganizationRole) -> bool:
        return bool(self.roles & frozenset(roles))


class JWKSCache:
    """Caches the signing keys for one ZITADEL instance.

    Fetching them per request means two outbound round trips on every API call
    and a hard dependency on the identity provider for requests that have no
    other reason to need it: a brief outage takes down all authenticated
    traffic.

    One cache per instance. A token minted by another environment cannot
    validate here, because the keys that would verify it are never fetched.
    """

    def __init__(self, domain: str, *, ttl_seconds: int = 3600) -> None:
        self._domain = domain.rstrip("/")
        self._ttl = ttl_seconds
        self._keys: dict[str, Any] | None = None
        self._fetched_at = 0.0

    async def get(self, *, force_refresh: bool = False) -> dict[str, Any]:
        if force_refresh or self._keys is None or (time.monotonic() - self._fetched_at) > self._ttl:
            self._keys = await self._fetch()
            self._fetched_at = time.monotonic()
        keys = self._keys
        if keys is None:  # pragma: no cover - set directly above
            raise TokenVerificationError("Signing keys unavailable")
        return keys

    async def _fetch(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            discovery = await client.get(f"{self._domain}/.well-known/openid-configuration")
            discovery.raise_for_status()
            config: dict[str, Any] = discovery.json()
            jwks_uri = config.get("jwks_uri")
            if not jwks_uri:
                raise TokenVerificationError(
                    f"{self._domain} published no jwks_uri; cannot verify tokens"
                )
            keys = await client.get(jwks_uri)
            keys.raise_for_status()
            payload: dict[str, Any] = keys.json()
            return payload


def _parse_roles(payload: dict[str, Any]) -> tuple[frozenset[OrganizationRole], frozenset[str]]:
    """Read the roles claim, accepting either shape ZITADEL may emit.

    Names that are not known roles are kept separately rather than discarded, so
    a service can log them, but they are never returned as authority.
    """
    raw = payload.get(ROLES_CLAIM)
    if isinstance(raw, dict):
        names = [str(name) for name in raw]
    elif isinstance(raw, list):
        names = [str(name) for name in raw]
    else:
        names = []

    known = {OrganizationRole(name) for name in names if is_organization_role(name)}
    unknown = {name for name in names if not is_organization_role(name)}
    return frozenset(known), frozenset(unknown)


def _used_mfa(payload: dict[str, Any]) -> bool:
    amr = payload.get(AMR_CLAIM)
    if not isinstance(amr, list):
        return False
    return bool({str(method).lower() for method in amr} & _MFA_METHODS)


async def verify_token(
    token: str,
    *,
    jwks: JWKSCache,
    project_id: str,
    issuer: str | None = None,
) -> JWTClaims:
    """Verify a bearer token and return its claims.

    Raises:
        TokenVerificationError: signature, audience, issuer, expiry, or subject
            not satisfied. Safe to log; do not return the message to the caller.
    """
    options = {"verify_aud": True}
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            await jwks.get(),
            algorithms=["RS256"],
            audience=project_id,
            issuer=issuer,
            options=options,
        )
    except JWTError:
        # A signing key may simply have rotated. Refresh once before rejecting;
        # otherwise every token fails until the TTL expires.
        try:
            claims = jwt.decode(
                token,
                await jwks.get(force_refresh=True),
                algorithms=["RS256"],
                audience=project_id,
                issuer=issuer,
                options=options,
            )
        except JWTError as exc:
            raise TokenVerificationError(f"Token rejected: {exc}") from exc

    subject = claims.get("sub")
    if not subject:
        raise TokenVerificationError("Token carries no subject")

    roles, unknown = _parse_roles(claims)
    return JWTClaims(
        sub=subject,
        email=claims.get("email"),
        name=claims.get("name"),
        roles=roles,
        unknown_roles=unknown,
        organization_id=claims.get(ORGANIZATION_CLAIM),
        used_mfa=_used_mfa(claims),
    )
