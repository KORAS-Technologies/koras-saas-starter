"""The private platform API this product must expose.

The Control Plane calls these endpoints during provisioning. They are the
product half of a contract whose other half lives in koras-control-plane, and a
product that drops or renames one breaks customer onboarding rather than
anything visible in its own test suite.

These assert the contract, not the implementation. Persistence lives in
`core/tenant_store.py` and is free to change; the four routes, their status
codes and the identity they require are not.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTER = REPO_ROOT / "services" / "api" / "koras_api" / "routers" / "platform.py"

# Read, not restated. This list existed here, in the router, and again in the
# Control Plane's reference implementation -- three copies of one contract, and
# three chances for two of them to agree while the third ships.
CONTRACT = json.loads(
    (REPO_ROOT / "contracts" / "product-platform.v1.json").read_text(encoding="utf-8")
)
REQUIRED_ROUTES = tuple((r["method"], r["path"]) for r in CONTRACT["routes"])


def _router_source() -> str:
    assert ROUTER.is_file(), "the private platform router is missing"
    return ROUTER.read_text(encoding="utf-8")


@pytest.mark.parametrize(("method", "path"), REQUIRED_ROUTES)
def test_the_contract_routes_exist(method: str, path: str) -> None:
    source = _router_source()
    assert f'@router.{method}("{path}"' in source, f"{method.upper()} {path} is not exposed"


def test_the_router_is_mounted_at_the_contract_prefix() -> None:
    main = (REPO_ROOT / "services" / "api" / "koras_api" / "main.py").read_text(encoding="utf-8")
    assert f'prefix="{CONTRACT["prefix"]}"' in main


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


def test_the_contract_is_not_empty() -> None:
    """Guards the guard.

    Every assertion above is parametrised or formatted from the contract file.
    An empty routes list would make the parametrised test vacuous and the
    prefix assertion compare against nothing, and the suite would pass while
    checking that the product exposes no API at all.
    """
    assert len(REQUIRED_ROUTES) >= 4
    assert CONTRACT["prefix"].startswith("/internal/platform/")
