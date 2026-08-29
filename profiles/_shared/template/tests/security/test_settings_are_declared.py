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

It happened a fourth time, in Python, because this file scanned only
`process.env` in `.ts`. A signup form reading an undeclared name was caught here
the same day a worker gained three settings -- two of them duplicating names the
manifest already declared -- and nothing said a word. So it reads pydantic
`Settings` fields now as well.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "local" / "config" / "secrets.manifest"

# Read from the environment and deliberately never declared.
#
# An entry here claims nobody should be able to set this in Doppler, which is a
# stronger statement than "we have not got round to it". Both are asserted below:
# one that becomes declared fails, and one nothing reads fails -- an exemption
# that quietly stops being true is a rule describing something the code no
# longer does.
NEVER_SETTABLE = {
    "REQUIRE_RLS_ENFORCEMENT": (
        "The startup check that the database connection cannot bypass row-level "
        "security. A deployment where it is false has correct policies, `force` "
        "set on every table, a green policy suite and no tenant isolation at "
        "all -- which is R-032. The field exists so a test can run without a "
        "database; putting a switch for it in Doppler would put a switch for "
        "turning tenant isolation off beside the one for the pool size."
    ),
}

# Read by the build or the platform, not by this repository's settings.
PROVIDED_BY_THE_PLATFORM = {
    # The credential a process uses to reach Doppler, so it cannot live in
    # Doppler. Injected at deploy time. Here rather than in NEVER_SETTABLE
    # because only one profile's API reads it, and that list asserts every entry
    # is read -- which would make it a fact about the product profile stated in a
    # file both profiles share.
    "DOPPLER_TOKEN",
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


def read_by_the_services() -> dict[str, list[str]]:
    """Every field on a pydantic Settings class, as the environment name it reads.

    `BaseSettings` maps a field to the upper-cased field name, so the field list
    *is* the list of environment variables a service reads.

    Parsed rather than imported: importing a settings module requires the
    settings to be present, which is the thing being checked.

    Fields on nested models are not found. There are none today; if one appears,
    this returns fewer names than are read and the gap reopens quietly -- worth
    knowing before it happens rather than after.
    """
    found: dict[str, list[str]] = {}
    field = re.compile(r"^    ([a-z][a-z0-9_]*)\s*:", re.MULTILINE)

    for path in (ROOT / "services").rglob("settings.py"):
        if {"node_modules", ".venv", "__pycache__"} & set(path.parts):
            continue
        source = path.read_text(encoding="utf-8")
        if "BaseSettings" not in source:
            continue
        body = source.split("class Settings", 1)[-1]
        for name in field.findall(body):
            if name.startswith("model_"):
                continue
            found.setdefault(name.upper(), []).append(str(path.relative_to(ROOT)))
    return found


def test_the_scanners_find_something() -> None:
    """Guards the guards.

    Both read source with a regular expression, and one that stops matching
    reports an empty set -- which passes the assertion below while checking
    nothing at all.
    """
    assert len(read_by_the_applications()) > 1
    assert len(read_by_the_services()) > 3


def test_nothing_is_both_declared_and_never_settable() -> None:
    """An exemption that stopped being true is worse than no exemption."""
    both = set(NEVER_SETTABLE) & declared()
    assert not both, f"declared despite being listed as never settable: {sorted(both)}"


def test_every_never_settable_entry_is_actually_read() -> None:
    """And one nothing reads is a rule about nothing."""
    read = set(read_by_the_applications()) | set(read_by_the_services())
    stale = set(NEVER_SETTABLE) - read
    assert not stale, f"listed as never settable but nothing reads them: {sorted(stale)}"


def test_no_application_reads_an_undeclared_setting() -> None:
    known = declared() | PROVIDED_BY_THE_PLATFORM | set(NEVER_SETTABLE)
    undeclared = {
        name: sorted(set(files))
        for name, files in {**read_by_the_applications(), **read_by_the_services()}.items()
        if name not in known
    }
    assert not undeclared, (
        "These are read from the environment but declared nowhere, so they are "
        "empty in every deployed environment:\n"
        + "\n".join(f"  {n}: {', '.join(f)}" for n, f in sorted(undeclared.items()))
    )
