"""Two defect classes a browser found on a deployed product, as tests.

Both shipped green. Both were invisible to every suite this repository runs, for
the same underlying reason: the suites read source text, or run SQL through
`psql`, and neither is what the product does at runtime.

Found on 2026-09-16 by opening the pages on dev.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "services" / "api"
WEB = ROOT / "apps" / "web" / "src"
MESSAGES = ROOT / "packages" / "i18n" / "src" / "messages" / "en.ts"


# -- an optional filter asyncpg cannot type ------------------------------------


def test_no_optional_filter_is_left_without_a_cast() -> None:
    """`where (:param is null or col = :param)` raises before the query runs.

    asyncpg sees the parameter only inside an `is null` test, cannot infer a
    type, and answers `AmbiguousParameterError: could not determine data type of
    parameter $N`. Not for some inputs -- for every call, whether or not the
    filter was supplied.

    Audit search carried four of these and was unusable on a deployed product
    from the day it shipped. Nothing caught it: the unit tests assert on the
    statement as text, and the row-level security suite runs raw SQL through
    psql, which infers types differently. No test executed the statement through
    the driver the API uses.

    This does not execute anything either -- it cannot, without a database. It
    asserts the shape that is safe, which is checkable everywhere at once and
    would have caught all four.
    """
    offenders: list[str] = []
    bare = re.compile(r":(\w+)\s+is\s+null", re.IGNORECASE)

    for path in sorted(API.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # A comment is not a query. The comment above this very statement
            # in `routers/audit.py` writes the broken form out to explain it,
            # and a scanner that read it would report the explanation as the
            # defect. Every statement here lives in a string literal, so the
            # line a comment starts on can be skipped whole.
            if line.lstrip().startswith("#"):
                continue
            for match in bare.finditer(line):
                # `cast(:x as text) is null` is the safe form, and reads as
                # `as text) is null` rather than `:x is null`.
                if f"cast(:{match.group(1)} as" not in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")

    assert not offenders, (
        "an optional SQL filter is not cast, so asyncpg cannot type it and the "
        f"query raises before it runs: {offenders}"
    )


# -- a translated sentence whose placeholder nobody filled ---------------------


def _catalogue() -> dict[str, list[str]]:
    """Every key in the English catalogue that carries a placeholder."""
    source = MESSAGES.read_text(encoding="utf-8")
    found: dict[str, list[str]] = {}
    pattern = re.compile(r"'([a-zA-Z0-9_.]+)':\s*'((?:[^'\\]|\\.)*)'")
    for key, value in pattern.findall(source):
        names = sorted(set(re.findall(r"\{(\w+)\}", value)))
        if names:
            found[key] = names
    return found


def test_the_scanner_finds_something() -> None:
    """Guards the guard. A pattern that stopped matching would report no keys
    and pass the assertion below while checking nothing at all."""
    assert len(_catalogue()) > 3, "no placeholder-bearing keys were found at all"


def test_every_placeholder_sentence_is_called_with_values() -> None:
    """A `t(key)` with no second argument renders the braces to the customer.

    `files.intro` says "What your organisation has stored in {product}" and was
    called bare, so a deployed product showed the literal braces on its Files
    page. Nothing failed: the key exists, every translation exists, and the
    three-language test only checks that every key is present in every
    catalogue -- never that a sentence needing a value was given one.

    Only a **direct render** counts. `{t('key')}` in JSX puts that string on the
    screen exactly as the catalogue holds it, so a placeholder in it reaches the
    customer. `confirmRemove: t('files.confirmRemove')` does not: a label bag is
    carried into a client component and filled there with `fill(label, values)`,
    because the value is not known on the server. Seven of those exist and every
    one of them is correct, so a rule that flagged any bare `t()` would be eight
    false positives around one defect and would be turned off within a week.
    """
    catalogue = _catalogue()
    offenders: list[str] = []
    rendered = re.compile(r"\{\s*t\(\s*'([a-zA-Z0-9_.]+)'\s*\)\s*\}")

    for path in sorted(WEB.rglob("*.tsx")) + sorted(WEB.rglob("*.ts")):
        if "node_modules" in path.parts:
            continue
        for match in rendered.finditer(path.read_text(encoding="utf-8")):
            key = match.group(1)
            if key in catalogue:
                offenders.append(f"{path.relative_to(ROOT)}: t('{key}') needs {catalogue[key]}")

    assert not offenders, (
        "a sentence with a placeholder is translated without values, so the "
        f"braces reach the customer: {offenders}"
    )
