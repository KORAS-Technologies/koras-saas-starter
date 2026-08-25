"""No Terraform plan or state artifact is tracked in the repository.

Checked by path rather than by content, because content scanning provably
cannot see these. A Terraform plan file embeds a full state snapshot, and state
holds every credential Terraform touched -- generated OIDC client secrets,
database passwords, provider tokens. It is a zip, and gitleaks decides whether
to look inside an archive from the *file extension*. Terraform names plan files
without one by convention.

Measured, not assumed: `tfplan` scans as zero bytes and reports no leaks; the
byte-identical file named `tfplan.zip` yields 28 findings. So the secret scan is
structurally blind to exactly the artifact most likely to carry a whole estate's
credentials, and no tuning of the scanner fixes that.

This has happened. A generated project carried `infrastructure/terraform/tfplan`
holding four Supabase database passwords and four ZITADEL client secrets in
plaintext, in a repository pushed to GitHub. The generator now writes the plan
outside the project and refuses to commit one, so this check should never fire
-- which is the point of keeping it.

A path rule is the right control here. It cannot be defeated by an entropy
threshold, it fails in under a second, and the artifacts it forbids have no
legitimate reason to be committed: a plan is a disposable intermediate, and
state belongs in the remote backend.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Resolved once, absolutely. Invoking a bare "git" would take whatever the PATH
# happens to offer, which is the kind of thing a security check should not do
# even when it is only reading a file list.
GIT = shutil.which("git") or "git"

# Name patterns, not extensions -- the extension is the part that is missing.
FORBIDDEN_NAMES = {
    "tfplan",
    "terraform.tfplan",
    "plan.out",
    "terraform.tfstate",
    "terraform.tfstate.backup",
}

FORBIDDEN_SUFFIXES = (".tfplan", ".tfstate", ".tfstate.backup")


def _tracked_files() -> list[str]:
    result = subprocess.run(  # noqa: S603 -- fixed argv, absolute binary
        [GIT, "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def test_no_terraform_plan_or_state_is_tracked() -> None:
    offenders = [
        path
        for path in _tracked_files()
        if Path(path).name in FORBIDDEN_NAMES or path.endswith(FORBIDDEN_SUFFIXES)
    ]

    assert not offenders, (
        "These are Terraform plan or state artifacts and each one embeds a full "
        "state snapshot, credentials included:\n  "
        + "\n  ".join(offenders)
        + "\n\nRemove with `git rm --cached`, confirm .gitignore covers it, and "
        "rotate every secret the state held -- deleting the file does not "
        "unpublish what was already pushed."
    )


def test_the_ignore_rules_would_stop_it_coming_back() -> None:
    """Removing the file is not the fix; the fix is that it cannot return.

    `git check-ignore` is asked directly rather than the .gitignore text being
    read, because what matters is the decision git actually makes -- a pattern
    can be present and overridden by a later negation.
    """
    candidates = (
        "infrastructure/terraform/tfplan",
        "infrastructure/terraform/terraform.tfstate",
    )
    for candidate in candidates:
        result = subprocess.run(  # noqa: S603 -- fixed argv, absolute binary
            [GIT, "check-ignore", "-q", candidate],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"{candidate} is not ignored and could be committed again. "
            "Note that git reports a *tracked* file as not-ignored, so if the "
            "test above also failed, untrack it first and re-run."
        )


@pytest.mark.parametrize(
    "path",
    [
        "infrastructure/terraform/tfplan",
        "infrastructure/terraform/terraform.tfstate",
        "somewhere/else/plan.out",
        "modules/thing.tfplan",
    ],
)
def test_the_check_recognises_the_shapes_it_is_meant_to(path: str) -> None:
    """The rule is only worth having if it matches what it claims to.

    Asserted against the matcher rather than against the repository, so this
    keeps failing if someone narrows the patterns while the tree happens to be
    clean.
    """
    assert Path(path).name in FORBIDDEN_NAMES or path.endswith(FORBIDDEN_SUFFIXES)


def test_the_check_does_not_forbid_ordinary_terraform() -> None:
    """A rule that also blocks .tf files would be removed within the week."""
    for path in (
        "infrastructure/terraform/main.tf",
        "infrastructure/terraform/terraform.tfvars",
        "infrastructure/terraform/.terraform.lock.hcl",
    ):
        assert not (Path(path).name in FORBIDDEN_NAMES or path.endswith(FORBIDDEN_SUFFIXES)), (
            f"{path} is a normal Terraform file and must stay committable"
        )
