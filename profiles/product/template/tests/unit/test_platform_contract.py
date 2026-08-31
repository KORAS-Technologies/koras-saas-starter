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


def test_a_foreign_environment_is_refused() -> None:
    """422, and deliberately not a retryable code.

    This service serves one environment. A request naming another is a
    misconfigured caller -- a dev Control Plane holding a prod address, or the
    reverse -- and writing the row anyway would put a customer's prod tenant in
    a dev database, which is the boundary the whole estate is arranged around.
    """
    source = _router_source()
    rule = CONTRACT["rules"]["environment_must_match"]
    assert rule["status"] == 422
    # The comparison itself, not merely the names in it. Asserting that the
    # source mentions `settings.environment` passes even when the branch has
    # been disabled, because the value is also interpolated into the message --
    # which is exactly what a mutation of this check proved on 2026-08-30.
    assert "body.environment != settings.environment.value" in source, (
        "the create route does not compare the requested environment to its own"
    )
    assert "HTTP_422_UNPROCESSABLE_ENTITY" in source


def test_a_slug_held_by_another_organization_is_refused() -> None:
    """409, and the caller must not adopt what is in the way.

    Distinct from the repeat case, and the distinction is the whole point. A
    repeat of the same tenant_key is the same customer retrying and is answered
    200. This is two different customers asking for one name, so the tenant in
    the way belongs to somebody else; adopting it would hand one customer
    another customer's tenant.
    """
    source = _router_source()
    rule = CONTRACT["rules"]["slug_conflict_is_not_adoptable"]
    assert rule["status"] == 409
    assert "SlugTaken" in source, "the create route never distinguishes a taken slug"
    assert "HTTP_409_CONFLICT" in source


def test_every_rule_the_contract_states_names_the_status_it_is_checked_by() -> None:
    """Guards the two tests above.

    Both read their status out of the contract and compare it to the router. A
    rule that lost its `status` would make them assert nothing in particular,
    which is how the 422 and the 409 came to be implemented here and written
    down in neither half of the contract.
    """
    refusals = ("environment_must_match", "slug_conflict_is_not_adoptable")
    for name in refusals:
        assert isinstance(CONTRACT["rules"][name].get("status"), int), (
            f"the {name} rule states no status code"
        )


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


# --- who the machine identity must be ------------------------------------

PLATFORM_AUTH = REPO_ROOT / "services" / "api" / "koras_api" / "core" / "platform_auth.py"


def _platform_auth_source() -> str:
    assert PLATFORM_AUTH.is_file(), "the platform authentication dependency is missing"
    return PLATFORM_AUTH.read_text(encoding="utf-8")


def test_the_gate_names_the_caller_it_admits() -> None:
    """A machine identity is not enough; it must be *the* machine identity.

    "Valid signature, no email" describes every service account in the ZITADEL
    instance, including one belonging to another product and one created by
    anybody who can make a service account. That was the entire gate until
    2026-08-31 while its docstring claimed to admit only the Control Plane, and
    it was verified against the live instance: a token from an account with no
    grant on this project was admitted. The project grant cannot close it -- a
    grant reaches neither the audience nor the roles claim -- so `sub` is the
    only field in the token that identifies the caller. R-87.
    """
    source = _platform_auth_source()
    assert "claims.sub != expected" in source, (
        "the platform gate does not compare the token's subject to the configured caller"
    )
    assert "zitadel_platform_caller_sub" in source


def test_an_unconfigured_gate_refuses_rather_than_admits() -> None:
    """Unset must mean refuse.

    The tempting alternative is to skip the check when nothing is configured, so
    that an existing product keeps working. That produces a security check which
    is present in the source, absent at runtime, and indistinguishable from a
    working one from the outside -- which is the shape of this exact defect, and
    of three others found the same week.

    503 rather than 403 because the caller is not at fault: the product is
    unconfigured, and an operator reading 403 would go looking at the wrong end.
    """
    source = _platform_auth_source()
    assert "if not expected:" in source, "the gate does not handle an unset caller at all"
    assert "HTTP_503_SERVICE_UNAVAILABLE" in source, (
        "an unconfigured gate does not refuse; if it falls through it admits every machine"
    )


def test_the_setting_is_declared_so_a_deployment_asks_for_it() -> None:
    """Optional in code, mandatory in the manifest.

    The service still starts without it -- health and every customer-facing
    route are unaffected -- but a deploy is refused, so the 503 above is a state
    a product passes through during bootstrap rather than one it ships in.
    """
    manifest = (REPO_ROOT / "local" / "config" / "secrets.manifest").read_text(encoding="utf-8")
    assert "ZITADEL_PLATFORM_CALLER_SUB supplied" in manifest, (
        "the platform caller is not declared as supplied, so nothing prompts for it "
        "and nothing refuses a deployment that omits it"
    )
