"""Helpers for doppler-bootstrap.sh.

Synced from koras-saas-starter:
  profiles/<profile>/template/local/scripts/doppler_bootstrap_support.py
Change it there. A fix made only here is a fix the next generated project
does not get, and R-65 was exactly that shape of miss. (This file is
copied verbatim rather than rendered, which is why the profile is not
filled in above.)

A separate file rather than heredocs inside the shell script. Three reasons,
and the third is the one that decided it: an inline heredoc cannot be tested,
quoting a Python block inside a bash function is where subtle bugs hide, and a
value read on stdin must never be reachable from a command line -- which is far
easier to guarantee when the reading happens in one small place.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

# Resolved once, absolutely. A bare "git" takes whatever the PATH offers, which
# a helper that reads credentials out of history should not do.
GIT = shutil.which("git") or "git"

# Attribute names in Terraform state that hold something worth refusing to
# reuse. Deliberately broader than the two we know leaked: state carries
# whatever a provider decided to return, and the next provider added will not
# announce that it stores a password.
CREDENTIAL_PATTERNS = (
    r'"database_password"\s*:\s*"([^"]{4,})"',
    r'"client_secret"\s*:\s*"([^"]{4,})"',
    r'"password"\s*:\s*"([^"]{8,})"',
    r'"secret"\s*:\s*"([^"]{8,})"',
)

# Plan and state artifacts, matched by name. A plan file has no extension by
# convention, which is exactly why a content scanner never looks inside one.
ARTIFACT_NAMES = {"tfplan", "terraform.tfplan", "plan.out"}
ARTIFACT_SUFFIXES = (".tfplan", ".tfstate", ".tfstate.backup")


def _is_artifact(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name in ARTIFACT_NAMES or name.endswith(ARTIFACT_SUFFIXES)


def _harvest(blob: bytes, digests: set[str]) -> None:
    """Collect digests of every credential-shaped value in one artifact.

    Digests, never the values. This runs over published credentials, and a
    helper that could print them would become the next way they escape.
    """
    text: str | None = None
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            # A plan is a zip carrying a state snapshot. This is the case a
            # secret scanner misses entirely.
            for member in archive.namelist():
                if member in {"tfstate", "tfstate-prev"}:
                    text = archive.read(member).decode("utf-8", "replace")
                    break
    except (zipfile.BadZipFile, KeyError):
        text = None

    if text is None:
        text = blob.decode("utf-8", "replace")

    for pattern in CREDENTIAL_PATTERNS:
        for value in re.findall(pattern, text):
            digests.add(hashlib.sha256(value.encode()).hexdigest())


def burned(root: str) -> int:
    """Print the digest of every credential reachable in git history.

    History, not the working tree. Deleting the file was never the fix: a plan
    file removed in a later commit is still fetchable from the remote, which is
    how one project's credentials stayed retrievable long after someone tidied
    them away.
    """
    try:
        revisions = subprocess.run(  # noqa: S603 -- fixed argv, absolute binary
            [GIT, "-C", root, "rev-list", "--all", "--max-count=200"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return 0

    digests: set[str] = set()
    seen_blobs: set[str] = set()

    for revision in revisions:
        listing = subprocess.run(  # noqa: S603 -- fixed argv, absolute binary
            [GIT, "-C", root, "ls-tree", "-r", revision],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.splitlines()

        for line in listing:
            # "<mode> <type> <sha>\t<path>"
            try:
                meta, path = line.split("\t", 1)
                blob_sha = meta.split()[2]
            except (ValueError, IndexError):
                continue
            if not _is_artifact(path) or blob_sha in seen_blobs:
                continue
            seen_blobs.add(blob_sha)

            blob = subprocess.run(  # noqa: S603 -- fixed argv, absolute binary
                [GIT, "-C", root, "cat-file", "blob", blob_sha],
                capture_output=True,
                check=False,
            ).stdout
            _harvest(blob, digests)

    for digest in sorted(digests):
        print(digest)
    return 0


def digest() -> int:
    """Hash one value read from stdin.

    stdin so the value never appears in a process listing. The caller pipes it
    in and compares the result against the burned set.
    """
    print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())
    return 0


def derived(source: str, environment: str) -> int:
    """Print the value a manifest SOURCE resolves to, if it resolves at all.

    The source is `out:<terraform output>` or `const:<literal>`. It is not the
    setting name: the first version assumed those were the same, so every
    lookup missed and the whole derivation feature silently did nothing while
    appearing to work.

    Outputs arrive through the environment rather than as an argument. Several
    are marked sensitive, and an argument is visible to every process on the
    machine.

    Exits non-zero when the value is absent, which the caller treats as "ask a
    person" rather than as an error -- a missing output should slow someone
    down, not stop them.
    """
    if source == "self:environment":
        # The environment's own name. Redundant with the Doppler config it lives
        # in, and required anyway: a deployed service reads its settings from
        # the environment, not from Doppler's notion of which config they came
        # from. Leaving it out is how three services shipped with every setting
        # except the one that has no default, and crash-looped on startup.
        print(environment, end="")
        return 0

    if source.startswith("const:"):
        print(source[len("const:") :], end="")
        return 0

    if not source.startswith("out:"):
        return 1
    output_name = source[len("out:") :]

    try:
        outputs = json.loads(os.environ.get("OUTPUTS_JSON", "{}"))
    except json.JSONDecodeError:
        return 1
    if not isinstance(outputs, dict):
        return 1

    value = outputs.get(output_name, {})
    if isinstance(value, dict) and "value" in value:
        value = value["value"]
    # Most outputs are a map keyed by environment; some are scalars that apply
    # everywhere.
    if isinstance(value, dict):
        value = value.get(environment)
    if value in (None, "", {}):
        return 1

    print(value, end="")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: doppler_bootstrap_support.py {burned|digest|derived}", file=sys.stderr)
        return 2

    command = sys.argv[1]
    if command == "burned":
        return burned(sys.argv[2])
    if command == "digest":
        return digest()
    if command == "derived":
        return derived(sys.argv[2], sys.argv[3])

    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
