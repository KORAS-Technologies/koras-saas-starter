"""The local identity provider is configured the way the deployed ones are.

Local exists to reproduce deployed behaviour. When the two disagree, the
disagreement is invisible: everything works on a laptop and fails in an
environment, or the reverse, and the difference is in infrastructure nobody
reads side by side.

That is not hypothetical here. The deployed OIDC applications were missing
`id_token_role_assertion`, so a user with a platform role signed in carrying
none and the middleware refused them -- a day to find. The local provisioner
had the same gap, and would have reproduced the bug rather than exposing it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TERRAFORM = ROOT / "infrastructure" / "terraform" / "modules" / "zitadel" / "main.tf"
PROVISION = ROOT / "local" / "zitadel" / "provision.py"


def test_the_same_five_platform_roles_exist_in_both() -> None:
    terraform = set(re.findall(r'"(platform_[a-z_]+)"', TERRAFORM.read_text(encoding="utf-8")))
    local = set(re.findall(r'"(platform_[a-z_]+)"', PROVISION.read_text(encoding="utf-8")))
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


def test_the_local_provisioner_grants_someone_a_role() -> None:
    """Otherwise sign-in completes and every page answers 403.

    Correct for a token carrying no role, and indistinguishable from a broken
    login -- which is how two hours went into checking a grant that was fine.
    """
    local = PROVISION.read_text(encoding="utf-8")
    assert "platform_super_admin" in local
    assert "/grants" in local
