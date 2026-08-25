"""ZITADEL token verification for the Control Plane.

Turns a bearer token into a Principal: who is calling, on whose behalf, and with
what authority. Authorisation decisions are made by the caller from that value;
this module only establishes what is true about the token.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import httpx
from jose import JWTError, jwt
from koras_platform import OrganizationRole, is_organization_role
from koras_platform.platform_roles import PlatformRole, is_platform_role

__all__ = [
    "ORGANIZATION_CLAIM",
    "ROLES_CLAIM",
    "ActorType",
    "JWKSCache",
    "Principal",
    "TokenVerificationError",
    "verify_token",
]


class ActorType(StrEnum):
    PLATFORM = "platform"
    ORGANIZATION = "organization"
    MACHINE = "machine"


class TokenVerificationError(Exception):
    """The token could not be verified, or carries no usable identity.

    Deliberately distinct from an authorisation failure. The caller maps this to
    401; a Principal that lacks the required role is a 403.
    """


# ZITADEL puts project roles under this claim, as an object keyed by role name
# whose values map organization id to domain.
ROLES_CLAIM = "urn:zitadel:iam:org:project:roles"
ORGANIZATION_CLAIM = "urn:zitadel:iam:org:id"
# Authentication Methods References, per RFC 8176. ZITADEL includes "mfa" and
# the specific second factor used.
AMR_CLAIM = "amr"

_MFA_METHODS = frozenset({"mfa", "otp", "u2f", "hwk", "sc", "totp", "webauthn"})


@dataclass(frozen=True)
class Principal:
    """An authenticated caller."""

    subject: str
    actor_type: ActorType
    email: str | None = None
    name: str | None = None
    platform_role: PlatformRole | None = None
    organization_roles: frozenset[OrganizationRole] = field(default_factory=frozenset)
    zitadel_organization_id: str | None = None
    used_mfa: bool = False

    @property
    def is_platform_staff(self) -> bool:
        return self.actor_type is ActorType.PLATFORM and self.platform_role is not None

    def has_organization_role(self, *roles: OrganizationRole) -> bool:
        return bool(self.organization_roles & frozenset(roles))


class JWKSCache:
    """Caches the signing keys for one ZITADEL instance.

    The previous implementation fetched the OIDC discovery document and then the
    JWKS on every single request: two outbound round trips per API call, and an
    outage of the identity provider taking down request handling that had no
    other reason to need it.

    Keys are cached for a TTL and, on a verification failure that looks like key
    rotation, refreshed once before the token is rejected.
    """

    def __init__(self, domain: str, *, ttl_seconds: int = 3600) -> None:
        self._domain = domain.rstrip("/")
        self._ttl = ttl_seconds
        self._keys: dict[str, Any] | None = None
        self._fetched_at = 0.0

    def _expired(self) -> bool:
        return self._keys is None or (time.monotonic() - self._fetched_at) > self._ttl

    async def get(self, *, force_refresh: bool = False) -> dict[str, Any]:
        if force_refresh or self._expired():
            self._keys = await self._fetch()
            self._fetched_at = time.monotonic()
        assert self._keys is not None  # noqa: S101 - narrowing, set directly above
        return self._keys

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


def _parse_roles(
    payload: dict[str, Any],
) -> tuple[PlatformRole | None, frozenset[OrganizationRole]]:
    """Extract roles from the ZITADEL project-roles claim.

    ZITADEL emits an object keyed by role name. Older tokens and some
    configurations emit a plain list, so both shapes are accepted. Anything that
    is not a known role is discarded rather than carried forward: an unrecognised
    role must never be treated as authority.
    """
    raw = payload.get(ROLES_CLAIM)
    if isinstance(raw, dict):
        names = list(raw.keys())
    elif isinstance(raw, list):
        names = [str(item) for item in raw]
    else:
        names = []

    platform = [PlatformRole(name) for name in names if is_platform_role(name)]
    organization = {OrganizationRole(name) for name in names if is_organization_role(name)}

    if len(platform) > 1:
        # Ambiguous authority. Take the least privileged rather than guessing
        # upward: a token carrying two staff roles is a provisioning mistake.
        order = list(PlatformRole)
        platform.sort(key=order.index, reverse=True)

    return (platform[0] if platform else None), frozenset(organization)


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
    require_mfa_for_platform: bool = True,
) -> Principal:
    """Verify a bearer token and describe who presented it.

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
        require_mfa_for_platform: staff tokens without a second factor are
            rejected. MFA is mandatory for every platform role, and checking it
            here means no endpoint can forget to.

    Raises:
        TokenVerificationError: signature, audience, issuer, expiry, identity, or
            MFA requirement not satisfied. The message is safe to log but should
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
    # compare against at_hash claim'. Every page in the admin application
    # answered 401 on that sentence, which nothing was printing.
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

    platform_role, organization_roles = _parse_roles(claims)
    used_mfa = _used_mfa(claims)

    if platform_role is not None:
        if require_mfa_for_platform and not used_mfa:
            raise TokenVerificationError(
                f"Platform role {platform_role.value} requires multi-factor authentication"
            )
        return Principal(
            subject=subject,
            actor_type=ActorType.PLATFORM,
            email=claims.get("email"),
            name=claims.get("name"),
            platform_role=platform_role,
            zitadel_organization_id=_organization_id(claims),
            used_mfa=used_mfa,
        )

    # A ZITADEL service user presents a token with no email and no interactive
    # authentication. Machine identities are how products and internal jobs call
    # the platform API, and they are never granted platform roles.
    if not claims.get("email"):
        return Principal(
            subject=subject,
            actor_type=ActorType.MACHINE,
            name=claims.get("name"),
            organization_roles=organization_roles,
            zitadel_organization_id=_organization_id(claims),
            used_mfa=used_mfa,
        )

    return Principal(
        subject=subject,
        actor_type=ActorType.ORGANIZATION,
        email=claims.get("email"),
        name=claims.get("name"),
        organization_roles=organization_roles,
        zitadel_organization_id=_organization_id(claims),
        used_mfa=used_mfa,
    )
