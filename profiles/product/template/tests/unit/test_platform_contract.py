"""The private platform API this product must expose.

The Control Plane calls these endpoints during provisioning. They are the
product half of a contract whose other half lives in koras-control-plane, and a
product that drops or renames one breaks customer onboarding rather than
anything visible in its own test suite.

These assert the contract, not the implementation. Replace the placeholder store
in the router with real tenant persistence; do not replace these.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTER = REPO_ROOT / "services" / "api" / "src" / "routers" / "platform.py"

REQUIRED_ROUTES = (
    ("post", "/tenants"),
    ("get", "/tenants/{tenant_id}"),
    ("post", "/tenants/{tenant_id}/activate"),
    ("post", "/tenants/{tenant_id}/suspend"),
)


def _router_source() -> str:
    assert ROUTER.is_file(), "the private platform router is missing"
    return ROUTER.read_text(encoding="utf-8")


@pytest.mark.parametrize(("method", "path"), REQUIRED_ROUTES)
def test_the_contract_routes_exist(method: str, path: str) -> None:
    source = _router_source()
    assert f'@router.{method}("{path}"' in source, f"{method.upper()} {path} is not exposed"


def test_the_router_is_mounted_at_the_contract_prefix() -> None:
    main = (REPO_ROOT / "services" / "api" / "src" / "main.py").read_text(encoding="utf-8")
    assert 'prefix="/internal/platform/v1"' in main


def test_every_contract_route_requires_a_machine_identity() -> None:
    """A browser token must not reach an internal provisioning endpoint.

    These are not part of any interactive flow, so a human token arriving here
    is a mistake or an attack -- even one belonging to an administrator.
    """
    source = _router_source()
    handlers = re.findall(r"@router\.(?:get|post)\([^)]*\)\s*\nasync def [^(]+\(([^)]*)\)", source)
    assert handlers, "no route handlers were found to check"
    for signature in handlers:
        assert "PlatformMachineDep" in signature, (
            f"a contract route does not require a machine identity: {signature.strip()[:80]}"
        )


def test_a_repeat_is_not_answered_with_a_conflict() -> None:
    """The Control Plane derives the tenant key, so a retry names the same tenant.

    Answering 409 would make a retryable operation fail. The contract requires
    200 with the existing tenant, and 201 only when this call created it.
    """
    source = _router_source()
    assert "HTTP_200_OK" in source, "the create route never returns 200 for an existing tenant"
    assert "HTTP_201_CREATED" in source, "the create route never signals a newly created tenant"


def test_the_contract_offers_no_delete() -> None:
    """Rollback suspends. The customer may already have data behind the tenant."""
    assert "@router.delete" not in _router_source()
