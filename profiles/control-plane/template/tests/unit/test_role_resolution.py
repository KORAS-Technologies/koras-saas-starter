"""One resolution rule, written twice, asserted to be the same rule.

The session is minted in TypeScript and verified in Python, so "which staff role
does a caller holding several actually get" is answered in two runtimes that
cannot import each other. For a while they answered differently: the console
sorted the role strings alphabetically and the API sorted by position in the
privilege enum. Both resolved *downward*, so neither granted authority nobody
held -- they simply disagreed about which role was lower, and a caller was
``platform_admin`` in the console header and ``platform_readonly`` at the API.
Observed on dev 2026-08-28 as a header naming a role the Plans page refused,
with nothing on either side naming the second role that caused it.

Both sides now resolve by position in one ordered list. That makes them
identical only for as long as the two lists stay identical, which is what the
first test here checks -- by reading the TypeScript source, because the
alternative is trusting that somebody updated both.

The remaining tests fix the rule itself over **every** combination of platform
roles. The two implementations agreed on most combinations, which is why the
disagreement survived: a test of a handful of cases would have passed.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import pytest
from koras_auth import _parse_roles
from koras_platform.platform_roles import PlatformRole

#: The claim ZITADEL emits roles under, shaped role -> {org id: primary domain}.
ROLES_CLAIM = "urn:zitadel:iam:org:project:roles"

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_TYPESCRIPT_ROLES = _REPOSITORY_ROOT / "packages" / "permissions" / "src" / "index.ts"


def _typescript_platform_roles() -> list[str]:
    """The PLATFORM_ROLES array from the permissions package, in order.

    Read rather than duplicated. A copy of the list here would be a third place
    for it to drift, and this test exists because there were already two.
    """
    source = _TYPESCRIPT_ROLES.read_text(encoding="utf-8")
    block = re.search(r"export const PLATFORM_ROLES = \[(.*?)\] as const", source, re.DOTALL)
    assert block is not None, f"PLATFORM_ROLES not found in {_TYPESCRIPT_ROLES}"
    return re.findall(r"'([^']+)'", block.group(1))


def test_both_runtimes_declare_the_same_roles_in_the_same_order() -> None:
    """The linchpin.

    Both sides resolve to the entry furthest down their own list, so identical
    ordered lists is exactly the condition under which they cannot disagree.
    Order is asserted, not membership: the same five roles in a different order
    is the divergence this whole file exists to catch, and set equality would
    call it a match.
    """
    assert _typescript_platform_roles() == [role.value for role in PlatformRole]


def test_the_list_is_most_privileged_first() -> None:
    """Stated once, so neither list can be reordered on the belief it is cosmetic."""
    assert [role.value for role in PlatformRole] == [
        "platform_super_admin",
        "platform_admin",
        "platform_support",
        "platform_billing",
        "platform_readonly",
    ]


def _combinations() -> list[tuple[PlatformRole, ...]]:
    roles = list(PlatformRole)
    return [
        held
        for size in range(1, len(roles) + 1)
        for held in itertools.combinations(roles, size)
    ]


@pytest.mark.parametrize("held", _combinations(), ids=lambda held: "+".join(r.name for r in held))
def test_every_combination_resolves_to_the_least_privileged_role_held(
    held: tuple[PlatformRole, ...],
) -> None:
    """All 31 non-empty subsets, in the order the enum declares them."""
    claims = {ROLES_CLAIM: {role.value: {"org": "koras"} for role in held}}
    resolved, _ = _parse_roles(claims)
    assert resolved == held[-1]


def test_the_answer_does_not_depend_on_claim_order() -> None:
    """ZITADEL emits an object, and key order is not something to lean on.

    An implementation taking the first recognised name passes the parametrised
    test above whenever the claim happens to arrive most-privileged-first, which
    is how it usually arrives.
    """
    for held in _combinations():
        forwards = {role.value: {"org": "koras"} for role in held}
        backwards = {role.value: {"org": "koras"} for role in reversed(held)}
        assert _parse_roles({ROLES_CLAIM: forwards})[0] == _parse_roles({ROLES_CLAIM: backwards})[0]


def test_the_pair_that_started_this() -> None:
    """`platform_admin` sorts before `platform_readonly` alphabetically.

    So the alphabetical rule returned the *more* privileged of the two. Named
    here so a revert to it cannot pass quietly.
    """
    claims = {
        ROLES_CLAIM: {
            "platform_admin": {"org": "koras"},
            "platform_readonly": {"org": "koras"},
        }
    }
    assert _parse_roles(claims)[0] is PlatformRole.READONLY


def test_a_list_shaped_claim_resolves_the_same_way() -> None:
    """Older tokens emit a plain list. Same rule, or the shape becomes a bypass."""
    claims = {ROLES_CLAIM: ["platform_admin", "platform_readonly"]}
    assert _parse_roles(claims)[0] is PlatformRole.READONLY


def test_unknown_names_grant_nothing_and_disturb_nothing() -> None:
    assert _parse_roles({ROLES_CLAIM: {}})[0] is None
    assert _parse_roles({ROLES_CLAIM: ["platform_administrator", "admin", ""]})[0] is None
    # A customer role is not staff authority, and must not change which staff
    # role is resolved.
    claims = {ROLES_CLAIM: ["organization_owner", "platform_admin", "member"]}
    assert _parse_roles(claims)[0] is PlatformRole.ADMIN
