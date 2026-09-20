"""What the import engine refuses, and what it repairs.

The assertions worth having are about files nobody meant to send: a European
Excel export with semicolons and `cp1252`, a header with two columns called the
same thing, a row with one comma too many, a trailing newline. None of those is
malformed to the person who sent it, and an engine that refuses them is an
engine whose first real customer gives up.

The other half is the allowlist. A mapping arrives from a browser, and the two
cases that matter are a field the target never declared and a required field
nobody mapped — refused, both, and named in the refusal.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from koras_import import (
    ENCODINGS,
    FALLBACK_ENCODING,
    FieldKind,
    FieldSpec,
    Format,
    ImportTarget,
    MappingRefused,
    Operation,
    ReadRefused,
    Row,
    RunState,
    TargetRegistry,
    TransitionRefused,
    Validation,
    build_registry,
    count_rows,
    decode,
    is_terminal,
    may_move,
    read_header,
    read_rows,
    require_move,
    resolve,
    sniff_delimiter,
    suggest,
    validate,
    validate_row,
    wrote_nothing,
)

CUSTOMERS = ImportTarget(
    key="shop.customers",
    label_key="import.target.shop.customers",
    permission="imports.manage",
    fields=(
        FieldSpec("email", "import.field.email", kind=FieldKind.EMAIL, required=True),
        FieldSpec("name", "import.field.name", required=True, max_length=80),
        FieldSpec("seats", "import.field.seats", kind=FieldKind.INTEGER),
        FieldSpec("joined", "import.field.joined", kind=FieldKind.DATE),
        FieldSpec("active", "import.field.active", kind=FieldKind.BOOLEAN),
        FieldSpec("tier", "import.field.tier", options=("basic", "pro")),
    ),
    match_keys=("email",),
    operations=(Operation.SKIP_DUPLICATE, Operation.UPSERT),
)


def lines(text: str) -> list[str]:
    """A file as the reader takes it: an iterable of lines."""
    return text.splitlines(keepends=True)


# ── the declaration ──────────────────────────────────────────────────────────


def test_a_target_that_recognises_a_row_must_say_how() -> None:
    """Upsert without match keys would create a second row every time, and the
    person who wrote the target would find out from a customer."""
    with pytest.raises(ValueError, match="recognise a row it has seen before"):
        ImportTarget(
            key="shop.thing",
            label_key="k",
            permission="imports.manage",
            fields=(FieldSpec("name", "k"),),
            operations=(Operation.UPSERT,),
        )


def test_a_target_cannot_match_on_a_field_it_does_not_declare() -> None:
    with pytest.raises(ValueError, match="does not declare as a field"):
        ImportTarget(
            key="shop.thing",
            label_key="k",
            permission="imports.manage",
            fields=(FieldSpec("name", "k"),),
            match_keys=("email",),
        )


def test_a_target_registered_twice_is_refused_at_import() -> None:
    registry = TargetRegistry()
    registry.add(CUSTOMERS)
    with pytest.raises(ValueError, match="registered twice"):
        registry.add(CUSTOMERS)


def test_an_unregistered_target_raises_rather_than_defaulting() -> None:
    """A key nobody declared is a caller asking to write somewhere the product
    never offered, and the only safe answer to that is no."""
    with pytest.raises(KeyError, match="never registered"):
        build_registry([CUSTOMERS]).require("shop.invoices")


# ── the file nobody meant to send ────────────────────────────────────────────


def test_a_utf8_file_with_a_byte_order_mark_is_read_as_utf8() -> None:
    """What a web application exports. The mark must not become a column name."""
    decoded = decode("﻿email,name\r\na@b.test,Ann\r\n".encode())
    assert decoded.encoding == "utf-8-sig"
    assert decoded.replaced is False
    assert decoded.text.startswith("email")


def test_a_windows_export_is_not_mangled_into_utf8() -> None:
    """`cp1252` decodes almost any byte, so trying it first would silently
    corrupt real UTF-8. This asserts the order, not just the outcome."""
    assert decode("name\nMünchen\n".encode()).encoding == "utf-8-sig"
    assert decode("name\nMünchen\n".encode("cp1252")).encoding == "cp1252"
    assert decode("name\nMünchen\n".encode("cp1252")).text.endswith("München\n")


def test_decoding_never_raises() -> None:
    """A file that decodes nowhere still produces something a person can look
    at. Refusing it outright gives them nothing to act on."""
    decoded = decode(b"name\n\xff\xfe\x00\x01\n")
    assert decoded.text
    assert decoded.encoding in {"cp1252", "latin-1"}


def test_a_european_export_is_semicolon_separated() -> None:
    assert sniff_delimiter("email;name;seats") == ";"
    assert sniff_delimiter("email,name,seats") == ","
    assert sniff_delimiter("email\tname\tseats") == "\t"


def test_a_delimiter_inside_a_quoted_heading_does_not_win() -> None:
    """`"Name, Legal";Email` is semicolon-separated with a comma in a label."""
    assert sniff_delimiter('"Name, Legal";Email') == ";"


def test_two_columns_with_one_name_are_kept_and_told_apart() -> None:
    """Dropping one would silently lose a column somebody meant to import."""
    header = read_header(lines("email,name,name\n"), delimiter=",")
    assert header.columns == ("email", "name", "name_2")
    assert header.duplicated == ("name",)


def test_a_trailing_delimiter_becomes_a_named_column() -> None:
    header = read_header(lines("email,name,\n"), delimiter=",")
    assert header.columns == ("email", "name", "column_3")
    assert header.unnamed == ("column_3",)


def test_an_empty_file_is_refused_with_a_reason() -> None:
    with pytest.raises(ReadRefused, match="empty"):
        read_header([], delimiter=",")


def test_a_trailing_newline_is_not_a_row() -> None:
    """Otherwise every real file gets a spurious error at the bottom."""
    header = read_header(lines("email,name\n"), delimiter=",")
    rows = list(
        read_rows(lines("email,name\na@b.test,Ann\n\n"), header=header, delimiter=",", limit=10)
    )
    assert len(rows) == 1


def test_a_row_number_is_what_the_spreadsheet_says() -> None:
    """1-based and including the header, so the first data row is 2. An error
    report whose numbers disagree with the file is one nobody can use."""
    header = read_header(lines("email,name\n"), delimiter=",")
    rows = list(
        read_rows(
            lines("email,name\na@b.test,Ann\nc@d.test,Bo\n"),
            header=header,
            delimiter=",",
            limit=10,
        )
    )
    assert [row.number for row in rows] == [2, 3]


def test_a_short_row_is_filled_and_flagged_and_a_long_one_is_trimmed_and_flagged() -> None:
    header = read_header(lines("email,name,seats\n"), delimiter=",")
    rows = list(
        read_rows(
            lines("email,name,seats\na@b.test,Ann\nc@d.test,Bo,3,extra\n"),
            header=header,
            delimiter=",",
            limit=10,
        )
    )
    assert rows[0].short is True and rows[0].cells["seats"] == ""
    assert rows[1].long is True and rows[1].cells["seats"] == "3"


def test_a_cell_large_enough_to_be_a_file_is_refused() -> None:
    with pytest.raises(ReadRefused, match="file in a cell"):
        read_header(lines("email," + "x" * 40_000 + "\n"), delimiter=",")


def test_counting_stops_once_the_ceiling_is_passed() -> None:
    """The answer a caller needs is "more than the ceiling", and counting nine
    million rows to say so is nine million rows of work to refuse the file."""
    text = "email\n" + "".join(f"a{n}@b.test\n" for n in range(50))
    assert count_rows(lines(text), delimiter=",", ceiling=10) == 11
    assert count_rows(lines(text), delimiter=",", ceiling=100) == 50


# ── the allowlist ────────────────────────────────────────────────────────────


def test_a_field_the_target_never_declared_is_refused_not_ignored() -> None:
    """Ignoring it is how an import writes a column it was never meant to
    reach, and how a caller learns nothing about why their data vanished."""
    with pytest.raises(MappingRefused, match="does not accept"):
        resolve(CUSTOMERS, ["Email", "Internal Id"], {"Internal Id": "tenant_id"})


def test_a_required_field_nobody_mapped_is_refused_by_name() -> None:
    with pytest.raises(MappingRefused, match=r"\['email', 'name'\]"):
        resolve(CUSTOMERS, ["Seats"], {"Seats": "seats"})


def test_two_columns_cannot_feed_one_field() -> None:
    with pytest.raises(MappingRefused, match="more than one column"):
        resolve(
            CUSTOMERS,
            ["A", "B"],
            {"A": "email", "B": "email"},
        )


def test_a_column_the_file_does_not_have_is_refused() -> None:
    with pytest.raises(MappingRefused, match="no column called"):
        resolve(CUSTOMERS, ["Email"], {"Missing": "name"})


def test_columns_the_mapping_ignores_are_not_an_error() -> None:
    """A real export carries columns the product has no field for."""
    resolved = resolve(
        CUSTOMERS,
        ["Email", "Name", "Internal Notes"],
        {"Email": "email", "Name": "name"},
    )
    assert resolved.unmapped_columns == ("Internal Notes",)


def test_a_suggestion_ignores_punctuation_spacing_and_case() -> None:
    assert suggest(CUSTOMERS, ["E-Mail", "  seats  ", "JOINED"]) == {
        "E-Mail": "email",
        "  seats  ": "seats",
        "JOINED": "joined",
    }


def test_a_suggestion_does_not_guess_at_a_name_it_only_resembles() -> None:
    """`Full Name` is probably `name`, and probably is not good enough.

    A suggestion is a starting point a person corrects, and a confident wrong
    guess costs more than a blank one: they scan a mapping that looks right and
    approve it. Matching on the normalised name exactly is the line, and it is
    drawn here rather than in a comment so that loosening it is a decision
    somebody makes on purpose.
    """
    assert suggest(CUSTOMERS, ["Full Name", "Customer Email"]) == {}


def test_an_ambiguous_suggestion_is_no_suggestion() -> None:
    """Picking the first would depend on column order, which is not a decision
    this can make on somebody's behalf."""
    assert suggest(CUSTOMERS, ["Email", "e_mail"]) == {}


# ── validation ───────────────────────────────────────────────────────────────


def _validate(text: str) -> Validation:
    header = read_header(lines(text), delimiter=",")
    resolved = resolve(
        CUSTOMERS,
        header.columns,
        {
            "email": "email",
            "name": "name",
            "seats": "seats",
            "joined": "joined",
            "active": "active",
            "tier": "tier",
        },
    )
    # Deliberately above the reported-error ceiling, so a test about that
    # ceiling exercises it rather than the read limit.
    rows = read_rows(lines(text), header=header, delimiter=",", limit=5000)
    return validate(CUSTOMERS, resolved, rows)


HEAD = "email,name,seats,joined,active,tier\n"


def test_a_good_file_validates() -> None:
    result = _validate(HEAD + "a@b.test,Ann,3,2026-09-19,yes,pro\n")
    assert result.ok and result.rows == 1 and result.valid == 1


def test_every_problem_in_a_row_is_reported_not_just_the_first() -> None:
    """A validator that stopped at the first makes fixing a hundred-row file a
    hundred attempts."""
    result = _validate(HEAD + "not-an-email,Ann,three,nope,maybe,gold\n")
    assert {error.field for error in result.errors} == {
        "email",
        "seats",
        "joined",
        "active",
        "tier",
    }


def test_an_error_names_the_column_the_person_is_looking_at() -> None:
    """Not the field the product calls it. An error about `external_reference`
    when the spreadsheet says `Ref No` is an error about somebody else's file."""
    header = read_header(lines("Ref No\n"), delimiter=",")
    target = ImportTarget(
        key="shop.things",
        label_key="k",
        permission="imports.manage",
        fields=(FieldSpec("external_reference", "k", kind=FieldKind.INTEGER, required=True),),
        operations=(Operation.CREATE,),
    )
    resolved = resolve(target, header.columns, {"Ref No": "external_reference"})
    rows = read_rows(lines("Ref No\nabc\n"), header=header, delimiter=",", limit=10)
    result = validate(target, resolved, rows)
    assert result.errors[0].column == "Ref No"
    assert result.errors[0].field == "external_reference"
    assert result.errors[0].code == "import.error.integer"


def test_an_ambiguous_date_is_refused_rather_than_guessed() -> None:
    """`03/04/2026` is the third of April or the fourth of March depending on
    where it was typed, and a date silently wrong eleven times in twelve is
    worse than one that is refused."""
    assert _validate(HEAD + "a@b.test,Ann,,2026-09-19,,\n").ok
    assert _validate(HEAD + "a@b.test,Ann,,19.09.2026,,\n").ok
    assert _validate(HEAD + "a@b.test,Ann,,19/09/2026,,\n").ok
    # Month-first is not in the accepted set at all.
    assert not _validate(HEAD + "a@b.test,Ann,,09/19/2026,,\n").ok


def test_a_blank_optional_field_is_not_an_error_and_a_blank_required_one_is() -> None:
    assert _validate(HEAD + "a@b.test,Ann,,,,\n").ok
    result = _validate(HEAD + ",Ann,,,,\n")
    assert [error.code for error in result.errors] == ["import.error.required"]


def test_an_option_matches_whatever_the_typist_capitalised() -> None:
    assert _validate(HEAD + "a@b.test,Ann,,,,PRO\n").ok


def test_a_duplicate_within_the_file_is_found_before_the_commit() -> None:
    """Two rows the commit would fight over. Finding it at commit time means
    finding it after half the file is written."""
    result = _validate(
        HEAD + "a@b.test,Ann,,,,\nA@B.TEST,Other,,,,\n"
    )
    codes = [error.code for error in result.errors]
    assert codes == ["import.error.duplicate_in_file"]
    assert result.valid == 1


def test_a_row_with_extra_cells_is_reported() -> None:
    result = _validate(HEAD + "a@b.test,Ann,1,,,,surplus\n")
    assert any(error.code == "import.error.extra_cells" for error in result.errors)


def test_a_products_own_rule_sees_a_row_that_already_passed_the_shape_checks() -> None:
    seen: list[dict[str, str]] = []

    def refuse_free_mail(row: Mapping[str, str]) -> dict[str, str]:
        seen.append(dict(row))
        return {"email": "import.error.free_mail"} if "@free." in row["email"] else {}

    target = ImportTarget(
        key="shop.people",
        label_key="k",
        permission="imports.manage",
        fields=(
            FieldSpec("email", "k", kind=FieldKind.EMAIL, required=True),
            FieldSpec("seats", "k2", kind=FieldKind.INTEGER),
        ),
        operations=(Operation.CREATE,),
        validator=refuse_free_mail,
    )
    header = read_header(lines("email,seats\n"), delimiter=",")
    resolved = resolve(target, header.columns, {"email": "email", "seats": "seats"})

    # A row that fails a shape check never reaches the product's rule, so a
    # validator never has to re-check that a number is a number.
    bad = validate(
        target,
        resolved,
        read_rows(lines("email,seats\na@b.test,three\n"), header=header, delimiter=",", limit=10),
    )
    assert [error.code for error in bad.errors] == ["import.error.integer"]
    assert seen == []

    caught = validate(
        target,
        resolved,
        read_rows(lines("email,seats\na@free.test,3\n"), header=header, delimiter=",", limit=10),
    )
    assert [error.code for error in caught.errors] == ["import.error.free_mail"]
    assert seen == [{"email": "a@free.test", "seats": "3"}]


def test_the_error_report_is_bounded_and_says_when_it_was_cut() -> None:
    """Beyond a point the report stops being a list of problems and starts
    being a second copy of the file."""
    text = HEAD + "".join("not-an-email,,,,,\n" for _ in range(1200))
    result = _validate(text)
    assert result.truncated is True
    assert len(result.errors) <= 1000
    assert result.rows == 1200


# ── the state machine ────────────────────────────────────────────────────────


def test_nothing_reaches_committed_without_having_been_validated() -> None:
    """The property the machine exists for: no row is ever written from rows
    nobody checked."""
    assert not may_move(RunState.MAPPED, RunState.COMMITTING)
    assert not may_move(RunState.CREATED, RunState.COMMIT_REQUESTED)
    assert may_move(RunState.VALIDATED, RunState.COMMIT_REQUESTED)
    assert may_move(RunState.COMMIT_REQUESTED, RunState.COMMITTING)


def test_a_failed_validation_goes_back_to_mapping_not_to_validating() -> None:
    """Re-validating the same mapping over the same file produces the same
    errors. The person changes something first."""
    assert may_move(RunState.VALIDATION_FAILED, RunState.MAPPED)
    assert not may_move(RunState.VALIDATION_FAILED, RunState.VALIDATING)


def test_a_commit_in_flight_cannot_be_cancelled() -> None:
    """A commit is one transaction. A cancellation arriving half way would
    either do nothing or leave the run claiming something untrue."""
    assert not may_move(RunState.COMMITTING, RunState.CANCELLED)
    assert may_move(RunState.COMMIT_REQUESTED, RunState.CANCELLED)


def test_every_state_but_the_two_that_write_has_written_nothing() -> None:
    assert wrote_nothing(RunState.VALIDATED)
    assert wrote_nothing(RunState.COMMIT_REQUESTED)
    assert not wrote_nothing(RunState.COMMITTING)
    assert not wrote_nothing(RunState.COMMITTED)


def test_terminal_states_go_nowhere() -> None:
    for state in (RunState.COMMITTED, RunState.FAILED, RunState.CANCELLED):
        assert is_terminal(state)


def test_a_refused_move_names_both_states_and_what_was_allowed() -> None:
    """Rather than an update that matches no row and reads as "the run
    disappeared"."""
    with pytest.raises(TransitionRefused, match="cannot become committed"):
        require_move(RunState.MAPPED, RunState.COMMITTED)
    require_move(RunState.VALIDATED, RunState.COMMIT_REQUESTED)


def test_a_target_says_which_formats_it_accepts() -> None:
    assert CUSTOMERS.accepts(Format.CSV)
    assert not CUSTOMERS.accepts(Format.XLSX)


# ── what the review found ────────────────────────────────────────────────────


def test_a_file_no_strict_encoding_fits_says_so() -> None:
    """IMP-03. `latin-1` was in `ENCODINGS` and maps all 256 byte values, so the
    loop always returned before its own fallback: the fallback was unreachable
    and `replaced` was structurally always False. The page's "some characters
    could not be read" banner could never appear, in any of three languages."""
    decoded = decode(b"name\n\x81dam\n")
    assert decoded.replaced is True
    assert decoded.encoding == "latin-1"
    # And the strict pair still wins where either fits, so this is a fallback
    # rather than a new default.
    assert decode(b"name\nAda\n").replaced is False
    assert decode("name\nMünchen\n".encode("cp1252")).replaced is False


def test_latin1_is_not_one_of_the_strict_encodings() -> None:
    """Asserted structurally, because that membership is the whole defect and
    re-adding it would make every behavioural test above pass again."""
    assert "latin-1" not in ENCODINGS
    assert FALLBACK_ENCODING == "latin-1"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Unambiguous: both separators present, so the last one is the point.
        ("1,234.56", None),
        ("1.234,56", None),
        ("1234.56", None),
        ("1234,56", None),
        # Unambiguous: one separator, and not three digits after it.
        ("1,5", None),
        ("1.5", None),
        ("12,34", None),
        ("1.2345", None),
        ("-3,7", None),
        # Ambiguous: one separator, exactly three digits after. These differ by
        # a factor of a thousand depending on which continent wrote the file,
        # and `float(value.replace(",", "."))` silently picked one.
        ("1,234", "import.error.ambiguous_decimal"),
        ("1.234", "import.error.ambiguous_decimal"),
        ("99,000", "import.error.ambiguous_decimal"),
        # Not a number at all.
        ("abc", "import.error.decimal"),
        ("1 234", "import.error.decimal"),
    ],
)
def test_a_decimal_is_parsed_or_refused_and_never_guessed(
    value: str, expected: str | None
) -> None:
    """IMP-04, and the same rule this module already applies to `%m/%d/%Y`: a
    value that is silently wrong half the time is worse than one refused."""
    spec = FieldSpec(name="amount", label_key="x", kind=FieldKind.DECIMAL)
    target = ImportTarget(
        key="shop.prices",
        label_key="x",
        permission="imports.manage",
        fields=(FieldSpec(name="sku", label_key="x", required=True), spec),
        match_keys=("sku",),
    )
    resolved = resolve(target, ("SKU", "Amount"), {"SKU": "sku", "Amount": "amount"})
    row = Row(number=2, cells={"SKU": "a", "Amount": value}, short=False, long=False)
    codes = [problem.code for problem in validate_row(target, resolved, row)]
    assert codes == ([] if expected is None else [expected])
