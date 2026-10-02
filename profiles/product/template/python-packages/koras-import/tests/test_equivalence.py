"""The same answers, asked less often.

GR-352C changed how four things are computed and not what any of them
answers: how a cell is cleaned, how a mapping is looked up for each cell, how
a prediction is counted once the rows have gone by, and how a match key is
held. Each is kept here beside the implementation it replaced -- verbatim,
from `1fefbc3` -- and both are handed the same input, a few written to be
awkward and many from a seeded generator.

A reference that shared code with the thing under test would drift with it,
so the old bodies are copied rather than imported. Where the old code is still
the public function (`predict`, `request_for`, `validate_row`, `normalise_row`,
`match_key`) the public function is the reference.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping

import pytest
from koras_import import (
    Candidate,
    FieldKind,
    FieldSpec,
    ImportTarget,
    Operation,
    ResolvedMapping,
    Row,
    RowError,
    Validation,
    clean_cell,
    mapping,
    match_key,
    normalise_row,
    normaliser,
    predict,
    predict_from,
    request_for,
    request_from,
    resolve,
    rows_from,
    validate,
    validate_row,
)

EMOJI = "\U0001f600"

# ── cleaning a cell ──────────────────────────────────────────────────────────

_CONTROLS_BEFORE = {chr(code) for code in range(32) if chr(code) not in "\t\n\r"}


def clean_cell_as_before(text: str) -> str:
    if any(char in _CONTROLS_BEFORE for char in text):
        text = "".join(char for char in text if char not in _CONTROLS_BEFORE)
    return text.strip()


#: Every character the two could disagree about: all of C0 and C1, the
#: delete, every space the standard library strips, the separators
#: `isprintable` is false for, a combining mark, and one of each width.
AWKWARD = [
    *(chr(code) for code in range(0x00, 0x21)),
    *(chr(code) for code in range(0x7F, 0xA1)),
    " ", " ", " ", " ", " ", " ", " ", "　",
    "​", "﻿", "́", "퟿", "", "a", "ż", "中", EMOJI,
]  # fmt: skip


def test_every_awkward_character_is_cleaned_as_it_was() -> None:
    for char in AWKWARD:
        for text in (char, f"a{char}b", f"{char}ab", f"ab{char}", f" {char} a {char} ", char * 3):
            assert clean_cell(text) == clean_cell_as_before(text), repr(text)


@pytest.mark.parametrize("seed", range(20))
def test_generated_text_is_cleaned_as_it_was(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - reproducible text, not a secret
    for _ in range(400):
        text = "".join(rng.choice(AWKWARD) for _ in range(rng.randrange(0, 24)))
        assert clean_cell(text) == clean_cell_as_before(text), repr(text)


def test_the_removed_set_is_exactly_what_it_was() -> None:
    from koras_import import reading

    assert reading._CONTROLS == _CONTROLS_BEFORE
    for code in range(0x3000):
        char = chr(code)
        assert bool(reading._CONTROL.search(char)) is (char in _CONTROLS_BEFORE), hex(code)


@pytest.mark.parametrize(
    "text", ["b" * 5000, "ż" * 5000, EMOJI * 5000, "a b\tc" * 1000, ""], ids=repr
)
def test_a_cell_that_needs_nothing_is_not_copied(text: str) -> None:
    # What IMPORT-DEF-016 turns on: a clean string named by a million cells
    # must come back as itself, not as a million of it.
    assert clean_cell(text) is text


# ── a mapping, looked up once ────────────────────────────────────────────────


def _truthy(mapped: Mapping[str, str]) -> dict[str, str]:
    """A product's own rule: a pro account names its seats."""
    if mapped.get("tier", "").lower() == "pro" and not mapped.get("seats"):
        return {"seats": "shop.error.seats_required"}
    return {}


ACCOUNTS = ImportTarget(
    key="shop.accounts",
    label_key="import.target.shop.accounts",
    permission="imports.manage",
    fields=(
        FieldSpec("email", "import.field.email", kind=FieldKind.EMAIL, required=True),
        FieldSpec("name", "import.field.name", required=True, max_length=12),
        FieldSpec("seats", "import.field.seats", kind=FieldKind.INTEGER),
        FieldSpec("joined", "import.field.joined", kind=FieldKind.DATE),
        FieldSpec("active", "import.field.active", kind=FieldKind.BOOLEAN),
        FieldSpec("tier", "import.field.tier", options=("Basic", "Pro")),
        FieldSpec("balance", "import.field.balance", kind=FieldKind.DECIMAL),
        FieldSpec("region", "import.field.region"),
    ),
    match_keys=("email", "region"),
    operations=tuple(Operation),
    validator=_truthy,
)

#: Seven of the eight fields are mapped; `region` -- a match key -- is not in
#: the second mapping, which is what `create` allows.
COLUMNS = ("E-Mail", "Name", "Seats", "Joined", "Active", "Tier", "Balance", "Region", "Notes")
EVERY_FIELD = resolve(
    ACCOUNTS,
    COLUMNS,
    {
        "E-Mail": "email",
        "Name": "name",
        "Seats": "seats",
        "Joined": "joined",
        "Active": "active",
        "Tier": "tier",
        "Balance": "balance",
        "Region": "region",
    },
)
SOME_FIELDS = resolve(ACCOUNTS, COLUMNS, {"E-Mail": "email", "Name": "name", "Tier": "tier"})

_VALUES: dict[str, list[str]] = {
    "E-Mail": ["ada@example.com", "ADA@example.com", "bo@x.io", "not-an-address", "", " cy@x.io "],
    "Name": ["Ada", "", "A name that is too long", " Bo "],
    "Seats": ["", "3", "3.5", "x", " 7 "],
    "Joined": ["", "2025-12-31", "31.12.2025", "31/12/2025", "12/31/2025", "soon"],
    "Active": ["", "yes", "NEIN", "wahr", "maybe", "1"],
    "Tier": ["", "pro", "PRO", "Basic", "gold"],
    "Balance": ["", "1,234", "1.234,50", "1,234.50", "12.5", "nan", "abc"],
    "Region": ["", "EU", "eu", "US"],
    "Notes": ["", "anything"],
}


def _rows(seed: int, count: int) -> list[Row]:
    rng = random.Random(seed)  # noqa: S311 - reproducible rows, not a secret
    return [
        Row(
            number=number,
            cells={column: rng.choice(_VALUES[column]) for column in COLUMNS},
            short=False,
            long=rng.random() < 0.1,
        )
        for number in range(2, count + 2)
    ]


def validate_as_before(
    target: ImportTarget, resolved: ResolvedMapping, rows: Iterable[Row]
) -> Validation:
    """`validate` as it stood at `1fefbc3`, over the public per-row functions."""
    errors: list[RowError] = []
    seen: dict[tuple[str, ...], int] = {}
    total = 0
    bad_rows: set[int] = set()
    truncated = False
    duplicates = 0
    for row in rows:
        total += 1
        problems = validate_row(target, resolved, row)
        key = match_key(target, resolved, row)
        if key is not None:
            first = seen.get(key)
            if first is not None:
                problems.append(
                    RowError(
                        row=row.number,
                        column=resolved.fields.get(target.match_keys[0], ""),
                        field=target.match_keys[0],
                        code="import.error.duplicate_in_file",
                        value=str(first),
                    )
                )
                duplicates += 1
            else:
                seen[key] = row.number
        if problems:
            bad_rows.add(row.number)
            for problem in problems:
                if len(errors) >= mapping.MAX_REPORTED_ERRORS:
                    truncated = True
                    break
                errors.append(problem)
    return Validation(
        rows=total,
        valid=total - len(bad_rows),
        errors=tuple(errors),
        truncated=truncated,
        duplicates=duplicates,
        bad_rows=frozenset(bad_rows),
    )


def validate_row_as_before(
    target: ImportTarget, resolved: ResolvedMapping, row: Row
) -> list[RowError]:
    """`validate_row` as it stood at `1fefbc3`: a lookup for every cell."""
    problems: list[RowError] = []
    if row.long:
        problems.append(
            RowError(row=row.number, column="", field="", code="import.error.extra_cells")
        )
    for field, column in resolved.fields.items():
        spec = target.spec(field)
        value = row.cells.get(column, "").strip()
        code = mapping._check(spec, value)
        if code is not None:
            problems.append(
                RowError(row=row.number, column=column, field=field, code=code, value=value[:120])
            )
    if problems or target.validator is None:
        return problems
    mapped = {
        field: row.cells.get(column, "").strip() for field, column in resolved.fields.items()
    }
    for field, code in target.validator(mapped).items():
        problems.append(
            RowError(
                row=row.number,
                column=resolved.fields.get(field, ""),
                field=field,
                code=code,
                value=mapped.get(field, "")[:120],
            )
        )
    return problems


def match_key_as_before(
    target: ImportTarget, resolved: ResolvedMapping, row: Row
) -> tuple[str, ...] | None:
    if not target.match_keys:
        return None
    parts = tuple(
        mapping.canonical(
            target.spec(name), row.cells.get(resolved.fields.get(name, ""), "").strip()
        ).lower()
        for name in target.match_keys
    )
    return parts if any(parts) else None


def normalise_row_as_before(
    target: ImportTarget, resolved: ResolvedMapping, row: Row
) -> dict[str, str]:
    return {
        field: mapping.canonical(target.spec(field), row.cells.get(column, "").strip())
        for field, column in resolved.fields.items()
    }


@pytest.mark.parametrize("resolved", [EVERY_FIELD, SOME_FIELDS], ids=["full", "partial"])
@pytest.mark.parametrize("seed", range(15))
def test_a_row_is_judged_keyed_and_normalised_as_it_was(
    resolved: ResolvedMapping, seed: int
) -> None:
    normalise = normaliser(ACCOUNTS, resolved)
    for row in _rows(seed, 120):
        assert validate_row(ACCOUNTS, resolved, row) == validate_row_as_before(
            ACCOUNTS, resolved, row
        )
        assert match_key(ACCOUNTS, resolved, row) == match_key_as_before(ACCOUNTS, resolved, row)
        expected = normalise_row_as_before(ACCOUNTS, resolved, row)
        assert normalise_row(ACCOUNTS, resolved, row) == expected
        made = normalise(row)
        # The same keys in the same order: a writer may rely on field order.
        assert made == expected and list(made) == list(expected)


@pytest.mark.parametrize("resolved", [EVERY_FIELD, SOME_FIELDS], ids=["full", "partial"])
@pytest.mark.parametrize("seed", range(15))
def test_a_file_is_validated_as_it_was(resolved: ResolvedMapping, seed: int) -> None:
    rows = _rows(100 + seed, 300)
    assert validate(ACCOUNTS, resolved, iter(rows)) == validate_as_before(ACCOUNTS, resolved, rows)


def test_a_report_is_still_cut_where_it_was() -> None:
    # Every row wrong in several ways: well past the ceiling of the report.
    rows = [
        Row(number=n, cells={column: "x" for column in COLUMNS}, short=False, long=True)
        for n in range(2, 700)
    ]
    now = validate(ACCOUNTS, EVERY_FIELD, iter(rows))
    assert now == validate_as_before(ACCOUNTS, EVERY_FIELD, rows)
    assert now.truncated and len(now.errors) == mapping.MAX_REPORTED_ERRORS


def test_validation_reads_its_rows_once_and_keeps_none() -> None:
    rows = _rows(7, 50)
    told: list[tuple[int, tuple[str, ...] | None, bool]] = []

    def stream() -> Iterable[Row]:
        yield from rows  # a generator: a second pass over it would be empty

    verdict = validate(
        ACCOUNTS,
        EVERY_FIELD,
        stream(),
        each=lambda row, key, bad: told.append((row.number, key, bad)),
    )
    assert [number for number, _, _ in told] == [row.number for row in rows]
    assert {number for number, _, bad in told if bad} == verdict.bad_rows
    for (_, key, _), row in zip(told, rows, strict=True):
        assert key == match_key(ACCOUNTS, EVERY_FIELD, row)


# ── a prediction, once the rows have gone by ─────────────────────────────────


@pytest.mark.parametrize("resolved", [EVERY_FIELD, SOME_FIELDS], ids=["full", "partial"])
@pytest.mark.parametrize("operation", list(Operation))
@pytest.mark.parametrize("seed", range(8))
def test_a_prediction_from_what_was_kept_is_the_prediction_from_the_rows(
    resolved: ResolvedMapping, operation: Operation, seed: int
) -> None:
    rows = _rows(200 + seed, 250)
    gathered = Candidate(ACCOUNTS, resolved)
    verdict = validate(ACCOUNTS, resolved, iter(rows), each=gathered.collect)
    kept = gathered.candidates()

    expected_request = request_for(ACCOUNTS, resolved, rows, tenant_id="t-1", verdict=verdict)
    assert request_from(ACCOUNTS, kept, tenant_id="t-1") == expected_request

    rng = random.Random(seed)  # noqa: S311 - which records "exist", reproducibly
    keys = expected_request.keys
    for existing in (
        set(),
        set(keys),
        {key for key in keys if rng.random() < 0.5},
        {("nobody@example.com", "")},
    ):
        expected = predict(
            ACCOUNTS, operation, resolved, rows, verdict=verdict, existing=existing
        )
        assert predict_from(ACCOUNTS, operation, resolved, kept, existing=existing) == expected


def test_what_is_kept_of_a_row_is_a_key_a_number_and_one_cell() -> None:
    rows = [
        Row(number=number, cells={"E-Mail": email, "Name": name}, short=False, long=False)
        for number, email, name in (
            (2, " Ada@Example.com ", "Ada"),
            (3, "", "Nobody"),
            (4, "ada@example.com", "Twice"),
            (5, "x" * 300 + "@example.com", "Long"),
        )
    ]
    target = ImportTarget(
        key="shop.people",
        label_key="k",
        permission="imports.manage",
        fields=(FieldSpec("email", "k"), FieldSpec("name", "k", required=True)),
        match_keys=("email",),
        operations=tuple(Operation),
    )
    resolved = resolve(target, ("E-Mail", "Name"), {"E-Mail": "email", "Name": "name"})
    gathered = Candidate(target, resolved)
    validate(target, resolved, iter(rows), each=gathered.collect)
    kept = gathered.candidates()
    assert kept.keys == (("ada@example.com",), ("x" * 300 + "@example.com",))
    assert kept.rows == (2, 5)
    # The cell as the file had it, cut as a problem's value is cut.
    assert kept.values == (" Ada@Example.com ", "x" * 120)
    assert kept.unkeyed == 1


# ── a key part, held once ────────────────────────────────────────────────────


def test_a_long_key_part_every_row_carries_is_one_string() -> None:
    """IMPORT-DEF-016, in the duplicate index.

    `str.lower` answers a new string each time. A two-part key whose first
    part is one long string and whose second is the row's own was a copy of
    the long part for every row.
    """
    region = "R" * 20_000
    rows = [
        Row(
            number=n,
            cells={"E-Mail": f"p{n}@example.com", "Name": "N", "Region": region},
            short=False,
            long=False,
        )
        for n in range(2, 302)
    ]
    resolved = resolve(
        ACCOUNTS,
        ("E-Mail", "Name", "Region"),
        {"E-Mail": "email", "Name": "name", "Region": "region"},
    )
    gathered = Candidate(ACCOUNTS, resolved)
    verdict = validate(ACCOUNTS, resolved, iter(rows), each=gathered.collect)
    assert verdict.ok and verdict.rows == 300
    keys = gathered.candidates().keys
    assert len(keys) == 300 and keys[0][1] == region.lower()
    assert all(key[1] is keys[0][1] for key in keys)
    # And the answer is the public function's, which interns nothing.
    assert list(keys) == [match_key(ACCOUNTS, resolved, row) for row in rows]


# ── the rows a writer is handed ──────────────────────────────────────────────


def test_rows_the_caller_built_for_the_writer_are_not_copied() -> None:
    mapped = ({"email": "a@x.io"}, {"email": "b@x.io"})
    handed = rows_from(mapped, ceiling=2, owned=True)
    assert handed is mapped
    # Without the word, every row is still a copy, as it always was.
    copied = rows_from(mapped, ceiling=2)
    assert copied == mapped and all(a is not b for a, b in zip(copied, mapped, strict=True))
    # And the ceiling is refused the same either way.
    from koras_import import WriteRefused

    with pytest.raises(WriteRefused, match="takes 1"):
        rows_from(mapped, ceiling=1, owned=True)
