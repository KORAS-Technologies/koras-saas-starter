"""The local identity provider is configured the way the deployed ones are.

Local exists to reproduce deployed behaviour. When the two disagree, the
disagreement is invisible: everything works on a laptop and fails in an
environment, or the reverse, and the difference is in infrastructure nobody
reads side by side.

That is not hypothetical here. The deployed OIDC applications were missing
`id_token_role_assertion`, so a user with a role signed in carrying none and the
middleware refused them -- a day to find. The local provisioner had the same
gap, and would have reproduced the bug rather than exposing it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TERRAFORM = ROOT / "infrastructure" / "terraform" / "modules" / "zitadel" / "main.tf"
PROVISION = ROOT / "local" / "zitadel" / "provision.py"


# Organization roles, because that is what this profile's ZITADEL module
# creates. A product never issues platform roles; the second test below asserts
# the local instance cannot start doing so.
ROLE = r'"(organization_owner|organization_admin|billing_admin|security_admin|member)"'


def test_the_same_roles_exist_in_both() -> None:
    terraform = set(re.findall(ROLE, TERRAFORM.read_text(encoding="utf-8")))
    local = set(re.findall(ROLE, PROVISION.read_text(encoding="utf-8")))
    assert terraform, "no roles found in the Terraform module"
    assert terraform == local, (
        "the local instance and the deployed ones would grant different roles:\n"
        f"  only in Terraform: {sorted(terraform - local)}\n"
        f"  only in local:     {sorted(local - terraform)}"
    )


def test_both_assert_roles_into_the_id_token() -> None:
    """The setting whose absence cost a day.

    project_role_assertion governs the access token. The applications read the
    ID token, so without id_token_role_assertion a signed-in user carries no
    role at all and the refusal reads as a misconfigured account.
    """
    terraform = TERRAFORM.read_text(encoding="utf-8")
    local = PROVISION.read_text(encoding="utf-8")

    for name, text, pattern in (
        ("terraform", terraform, r"id_token_role_assertion\s*=\s*true"),
        ("terraform", terraform, r"id_token_userinfo_assertion\s*=\s*true"),
        ("local", local, r'"idTokenRoleAssertion":\s*True'),
        ("local", local, r'"idTokenUserinfoAssertion":\s*True'),
    ):
        assert re.search(pattern, text), f"{name} does not set {pattern}"


def test_the_local_instance_issues_no_platform_role() -> None:
    """A product must not be able to mint staff authority, even locally.

    Building against a role the deployed estate will never grant is worse than
    not having it: it works on a laptop and fails in every environment, and the
    failure looks like a broken grant rather than a role that was never real.
    """
    local = PROVISION.read_text(encoding="utf-8")
    minted = re.findall(r'"(platform_[a-z_]+)"', local)
    assert not minted, f"the local provisioner would create staff roles: {sorted(set(minted))}"


def test_the_local_provisioner_grants_someone_a_role() -> None:
    """Otherwise sign-in completes and every page answers 403.

    Correct for a token carrying no role, and indistinguishable from a broken
    login -- which is how two hours went into checking a grant that was fine.
    """
    local = PROVISION.read_text(encoding="utf-8")
    assert "organization_owner" in local
    assert "/grants" in local
