"""What the API actually serves, asked of the API rather than of its source.

OWASP API5 (broken function level authorization) and API3 (broken object
property level authorization). Both were reviewed by hand and recorded as
holding, and both were recorded as having no test -- so a route added without
an authorization dependency, or a response model that grew a sensitive field,
would have been caught by nobody.

These read `app.openapi()`, which is the app's own description of what it
serves. A test that greps the router source can only see the routes it thought
to look for, and stops seeing anything the moment a route is declared some other
way -- a different decorator, a sub-router, a loop. The schema is generated from
the assembled application, so a route is in it however it got there.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

# Set before importing the app. `Settings()` runs at import and several fields
# are required with no default -- deliberately, so a missing ENVIRONMENT fails
# loudly rather than defaulting to something that looks fine. None of these
# values is used: nothing here opens a connection.
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_api.main import app  # noqa: E402  - must follow the environment above

MUTATING = {"post", "put", "patch", "delete"}

# Routes that are allowed to answer without an authenticated caller.
#
# Health only, and it is not an oversight: a liveness probe that needs a token
# takes the service out of rotation the moment the identity provider is slow,
# which converts a dependency's bad minute into an outage of your own.
PUBLIC = {("get", "/api/v1/health")}

SPEC: dict[str, Any] = app.openapi()


def operations() -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (method.lower(), path, operation)
        for path, methods in SPEC.get("paths", {}).items()
        for method, operation in methods.items()
        if method.lower() in {"get", "post", "put", "patch", "delete", "head", "options"}
    ]


def test_the_app_serves_something() -> None:
    # Without this the parametrised tests below would pass by having no cases,
    # which is the way this kind of suite usually stops asserting anything.
    assert operations(), "the OpenAPI schema describes no operations"


@pytest.mark.parametrize(("method", "path", "operation"), operations())
def test_every_mutating_route_requires_a_caller(
    method: str, path: str, operation: dict[str, Any]
) -> None:
    """A route that changes state must know who is asking.

    `security` appears on an operation when a security dependency resolves for
    it -- the bearer scheme, in this codebase, which is what `require_auth` and
    `require_platform_staff` are built on. An empty or absent `security` on a
    mutating route means nothing authenticates it.
    """
    if method not in MUTATING or (method, path) in PUBLIC:
        return

    assert operation.get("security"), (
        f"{method.upper()} {path} changes state and requires no authenticated caller. "
        "Add an auth dependency, or add it to PUBLIC here with the reason."
    )


@pytest.mark.parametrize(("method", "path", "operation"), operations())
def test_public_routes_are_only_the_ones_named(
    method: str, path: str, operation: dict[str, Any]
) -> None:
    """The allowlist is exhaustive, so widening it is a visible decision.

    Without this the previous test could be satisfied by adding entries to
    PUBLIC, and the allowlist would grow quietly. Here, an unauthenticated read
    that nobody declared fails too.
    """
    if operation.get("security"):
        return

    assert (method, path) in PUBLIC, (
        f"{method.upper()} {path} answers without an authenticated caller and is not "
        "in the PUBLIC allowlist. If that is intended, say so there."
    )


# ── API3: what the responses carry ───────────────────────────────────────────

# Field names that would mean an internal or secret value is being serialised.
# Matched on the name because the value is not knowable from a schema, and a
# field called `password_hash` is a finding whatever it happens to hold.
FORBIDDEN_FIELD = (
    "password",
    "secret",
    "token",
    "api_key",
    "private_key",
    "credential",
    "session_key",
    "hashed",
    "salt",
)


def response_schemas() -> list[tuple[str, dict[str, Any]]]:
    """Every schema a response can be shaped by, keyed by its name."""
    return sorted(SPEC.get("components", {}).get("schemas", {}).items())


def test_the_app_publishes_response_schemas() -> None:
    assert response_schemas(), "no component schemas: the check below asserts nothing"


@pytest.mark.parametrize(("name", "schema"), response_schemas())
def test_no_schema_serialises_a_secret(name: str, schema: dict[str, Any]) -> None:
    """A response model must not carry a credential or an internal column.

    The registration payload has the same rule enforced two ways -- the Control
    Plane's schema forbids extra fields, and the generator builds the payload
    only from Terraform outputs it did not mark sensitive. This is the same rule
    for everything else the API returns.
    """
    offenders = [
        field
        for field in schema.get("properties", {})
        if any(word in field.lower() for word in FORBIDDEN_FIELD)
    ]

    assert not offenders, (
        f"{name} would serialise {offenders}. A response model is a published "
        "contract; keep internal and secret columns out of it."
    )
