"""Every setting the applications read is one the contract declares.

Three names broke a working deployment, and all three failed the same way:
the code read a variable nothing sets, took a default, and reported the
consequence rather than the cause.

  PLATFORM_API_URL          never declared. Defaulted to http://localhost:8010,
                            which on a deployed function reaches nothing, so
                            every page said "the platform API could not be
                            reached" while the API was healthy.

  NEXT_PUBLIC_API_BASE_URL  never declared. Left connect-src as 'self', so the
                            browser blocked calls to the API without anything
                            in the application saying so.

Doppler held NEXT_PUBLIC_API_URL the whole time. Nothing compared the names.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "local" / "config" / "secrets.manifest"

# Read by the build or the platform, not by this repository's settings.
PROVIDED_BY_THE_PLATFORM = {
    "NODE_ENV",
    "VERCEL_ENV",
    "VERCEL_URL",
    "npm_package_version",
}


def declared() -> set[str]:
    names = set()
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.add(line.split()[0])
    return names


def read_by_the_applications() -> dict[str, list[str]]:
    """Every process.env.NAME in application and package source."""
    found: dict[str, list[str]] = {}
    for base in ("apps", "packages"):
        for path in (ROOT / base).rglob("*.ts*"):
            parts = set(path.parts)
            if {".next", "dist", "node_modules"} & parts:
                continue
            if path.name.endswith((".test.ts", ".test.tsx")):
                continue
            for name in re.findall(r"process\.env\.([A-Z0-9_]+)", path.read_text(encoding="utf-8")):
                found.setdefault(name, []).append(str(path.relative_to(ROOT)))
    return found


def test_no_application_reads_an_undeclared_setting() -> None:
    known = declared() | PROVIDED_BY_THE_PLATFORM
    undeclared = {
        name: sorted(set(files))
        for name, files in read_by_the_applications().items()
        if name not in known
    }
    assert not undeclared, (
        "These are read from the environment but declared nowhere, so they are "
        "empty in every deployed environment:\n"
        + "\n".join(f"  {n}: {', '.join(f)}" for n, f in sorted(undeclared.items()))
    )
