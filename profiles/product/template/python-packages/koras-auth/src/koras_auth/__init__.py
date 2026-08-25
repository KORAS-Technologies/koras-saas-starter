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


def _organization_id(payload: dict[str, Any]) -> str | None:
    """Which ZITADEL organization this caller belongs to.

    `urn:zitadel:iam:org:id` is the obvious place and ZITADEL does not send it
    unless the authorization request named an organization -- which a login
    form cannot, because the point of logging in is to find out who you are.
    Reading only that claim meant every customer token resolved to no
    organization and the portal answered 403 on every request.

    The organization is in the roles claim, which ZITADEL shapes as
    role -> {organization id: primary domain}. Roles are granted per
    organization, so that mapping is the authoritative statement of which one.

    More than one is refused rather than guessed. A customer belongs to a
    single organization here; a token naming two is a provisioning mistake,
    and picking one would silently scope a session to whichever came first.
    """
    explicit = payload.get(ORGANIZATION_CLAIM)
    if isinstance(explicit, str) and explicit:
        return explicit

    raw = payload.get(ROLES_CLAIM)
    if not isinstance(raw, dict):
        return None

    organizations = {
        organization
        for value in raw.values()
        if isinstance(value, dict)
        for organization in value
    }
    return organizations.pop() if len(organizations) == 1 else None


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
    client_id: str | None = None,
    issuer: str | None = None,
) -> JWTClaims:
    """Verify a bearer token and describe who presented it.

    Returns organization authority only. Staff roles belong to the Control
    Plane; see the note on the return value below.

    Args:
        token: the raw bearer token.
        jwks: signing keys for the ZITADEL instance this environment uses. One
            cache per instance, so a token minted by another environment cannot
            validate here even if it is otherwise well formed.
        project_id: an accepted audience. ZITADEL puts it in access tokens.
        client_id: also an accepted audience, and the one an OIDC ID token
            actually carries. Verifying against the project id alone rejected
            every ID token the applications hold, so every page answered 401
            while the API was healthy and the caller properly signed in.
        issuer: expected issuer, when it should be pinned as well as the audience.

    Raises:
        TokenVerificationError: signature, audience, issuer, expiry or identity
            not satisfied. The message is safe to log but should
            not be returned to the caller verbatim.
    """
    # Audience is checked here rather than by the decoder, which takes one
    # value. Two are legitimate: the project id, which ZITADEL puts in access
    # tokens, and the client id, which is what an ID token carries. Rejecting
    # the second is what made every page answer 401.
    allowed = {value for value in (project_id, client_id) if value}
    if not allowed:
        raise TokenVerificationError('No audience configured to verify against')
    # at_hash is not this service's business, and demanding it rejected every
    # real token. It binds an ID token to the access token issued beside it,
    # so the *client* can confirm it received a matching pair. A resource
    # server holds neither the pair nor the reason to check it, and python-jose
    # refuses outright rather than skipping: 'No access_token provided to
    # compare against at_hash claim'. Every page of an application answered 401
    # on that sentence, which nothing was printing.
    options = {"verify_aud": False, "verify_at_hash": False}
    claims: dict[str, Any]
    try:
        claims = jwt.decode(
            token,
            await jwks.get(),
            algorithms=["RS256"],
            issuer=issuer,
            options=options,
        )
    except JWTError:
        # A signing key may simply have rotated. Refresh once and retry before
        # concluding the token is bad; failing here would reject every token
        # until the TTL expired.
        try:
            claims = jwt.decode(
                token,
                await jwks.get(force_refresh=True),
                algorithms=["RS256"],
                issuer=issuer,
                options=options,
            )
        except JWTError as exc:
            raise TokenVerificationError(f"Token rejected: {exc}") from exc

    # Never widened to 'any audience'. A token minted for another application
    # on the same instance must not be accepted here.
    presented = claims.get("aud")
    presented = {presented} if isinstance(presented, str) else set(presented or ())
    if not (presented & allowed):
        raise TokenVerificationError('Token is addressed to another application')

    subject = claims.get("sub")
    if not subject:
        raise TokenVerificationError("Token carries no subject")

    roles, unknown_roles = _parse_roles(claims)

    # No platform branch, and no platform_role on JWTClaims.
    #
    # KORAS staff authority is Control Plane authority, and a product that can
    # represent it is a product that can accidentally honour it. The roles
    # parser here returns organization roles and the names it did not
    # recognise -- a platform role arriving in a product's token lands in
    # `unknown_roles`, where it can be logged and cannot be acted on.
    #
    # This function was a verbatim copy of the Control Plane's, which branches
    # on a PlatformRole and returns a Principal. Neither type exists here, so
    # the module did not typecheck as generated, and the copy also reached for
    # authority a product must not hold.
    return JWTClaims(
        sub=subject,
        email=claims.get("email"),
        name=claims.get("name"),
        roles=roles,
        unknown_roles=unknown_roles,
        organization_id=_organization_id(claims),
        used_mfa=_used_mfa(claims),
    )
