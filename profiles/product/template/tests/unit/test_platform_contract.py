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
import os
import re
from pathlib import Path

import pytest

# Every assertion here but one reads the router's source text, which needs no
# settings. The exception is the governance response check below: comparing
# Pydantic field names to the contract means importing the module, and the
# module reads settings at import. The same four defaults every other unit
# test in this suite sets, for the same reason.
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTER = REPO_ROOT / "services" / "api" / "koras_api" / "routers" / "platform.py"


def _capability_router(capability: str) -> Path:
    """A capability's half of the contract lives beside the platform router,
    generated only with the capability: `platform_ai.py` for `ai`."""
    return ROUTER.with_name(f"platform_{capability}.py")


# Read, not restated. This list existed here, in the router, and again in the
# Control Plane's reference implementation -- three copies of one contract, and
# three chances for two of them to agree while the third ships.
CONTRACT = json.loads(
    (REPO_ROOT / "contracts" / "product-platform.v1.json").read_text(encoding="utf-8")
)
REQUIRED_ROUTES = tuple((r["method"], r["path"], r.get("capability")) for r in CONTRACT["routes"])
CAPABILITIES = sorted({r["capability"] for r in CONTRACT["routes"] if r.get("capability")})


def _foundation_routers() -> list[Path]:
    """Every platform router a product carries regardless of its capabilities.

    `platform.py` was the only one until 2026-09-16, when the governance
    aggregates arrived and were too large to add to it. A route with no
    `capability` in the contract may live in any of these; a route *with* one
    lives in that capability's own file and nowhere else, which is what keeps
    a product without the capability answering 404 rather than serving it.
    """
    capability_files = {_capability_router(name).name for name in CAPABILITIES}
    return sorted(
        path
        for path in ROUTER.parent.glob("platform*.py")
        if path.name not in capability_files
    )


def _router_source() -> str:
    assert ROUTER.is_file(), "the private platform router is missing"
    sources = [path.read_text(encoding="utf-8") for path in _foundation_routers()]
    for capability in CAPABILITIES:
        extra = _capability_router(capability)
        if extra.is_file():
            sources.append(extra.read_text(encoding="utf-8"))
    return "\n".join(sources)


@pytest.mark.parametrize(("method", "path", "capability"), REQUIRED_ROUTES)
def test_the_contract_routes_exist(method: str, path: str, capability: str | None) -> None:
    if capability is not None and not _capability_router(capability).is_file():
        pytest.skip(f"the {capability} capability is not generated here")
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
    handlers = re.findall(
        r"@router\.(?:get|post|put)\([^)]*\)\s*\nasync def [^(]+\(([^)]*)\)", source
    )
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


def test_the_create_call_records_the_identity_the_resolver_needs() -> None:
    """The tenant resolver matches `zitadel_org_id` and `status = 'active'`.

    Until 2026-09-09 the create call carried no such identifier and nothing
    called activate, so every tenant sat at `provisioning` with no organization
    and refused its own customer (R-105 in koras-control-plane). This asserts
    the request schema accepts it, the store writes it, and a repeat call fills
    in a row that lacks it -- which is the repair for tenants made before.
    """
    source = _router_source()
    assert "zitadel_org_id: str | None = None" in source, "the organization schema has no identity"
    assert "zitadel_org_id=body.organization.zitadel_org_id" in source
    store = (REPO_ROOT / "services" / "api" / "koras_api" / "core" / "tenant_store.py").read_text(
        encoding="utf-8"
    )
    assert ":zitadel_org_id) " in store, "the insert does not write the identity"
    assert "where tenant_key = :tenant_key and zitadel_org_id is null" in store, (
        "a repeat call does not fill in a missing identity"
    )


def test_storage_defaults_are_the_settings_and_never_a_credential() -> None:
    """The Control Plane records where files go from this answer; it must be the
    bucket and region the product actually signs against, and nothing that
    authenticates."""
    source = _router_source()
    handler = source[source.index("async def storage_defaults") :]
    handler = handler[: handler.index("@router.")]
    assert "settings.storage_bucket" in handler
    assert "settings.storage_region" in handler
    for secret in ("access_key", "secret_key", "storage_endpoint"):
        assert secret not in handler, f"{secret} must not be reported"


# -- the response shape, and not only the route -------------------------------
#
# The routes above are checked by name. That is not enough for `/governance`,
# because the Control Plane does not call it through a generated client -- its
# collector reads the keys out of the parsed JSON by name. A field renamed here
# and not there is read as a missing key, which the collector counts as zero,
# which the console reports as an estate storing nothing. Nothing goes red.
#
# So the contract declares the field names and both repositories assert their
# own side against it.


def _declared(section: str) -> set[str]:
    route = next(r for r in CONTRACT["routes"] if r["path"] == "/governance")
    return set(route["response"][section])


@pytest.mark.parametrize(
    ("section", "model"),
    [
        ("storage", "StorageSummary"),
        ("audit", "AuditSummary"),
        ("holds", "HoldSummary"),
        ("exports", "ExportSummary"),
    ],
)
def test_the_governance_response_matches_the_contract(section: str, model: str) -> None:
    """Every field the contract declares exists on the model, and vice versa.

    Both directions on purpose. A field the model dropped would be read as
    zero by the collector; a field the model added that the contract does not
    declare is one the Control Plane will never read, which is a different
    kind of waste and worth knowing about at the same moment.
    """
    from koras_api.routers import platform_governance

    fields = set(getattr(platform_governance, model).model_fields)
    assert fields == _declared(section), (
        f"{model} and the contract disagree about the {section} fields; "
        f"only on the model: {sorted(fields - _declared(section))}; "
        f"only in the contract: {sorted(_declared(section) - fields)}"
    )


def test_the_governance_response_names_nothing_that_identifies_anybody() -> None:
    """The contract is where this is cheapest to enforce: a field added to the
    declaration is reviewed here before either side implements it."""
    every = set().union(*(_declared(s) for s in ("storage", "audit", "holds", "exports")))
    for forbidden in ("storage_key", "name", "actor_id", "uploaded_by", "reason", "details"):
        assert forbidden not in every, f"the platform contract would carry {forbidden}"
