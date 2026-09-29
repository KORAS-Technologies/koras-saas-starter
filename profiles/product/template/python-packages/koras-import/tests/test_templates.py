"""A template is the declaration written out, and it reads back as itself.

Every assertion here renders a file and opens it again, because a test that
reads the renderer's source would pass over a workbook Excel refuses to open.
The two properties worth the most are that the header a template writes is
exactly what the reader maps from, and that the identity a workbook carries is
what `compare` recognises -- a template the importer could not recognise would
be a file with metadata nobody reads.
"""

from __future__ import annotations

import io
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from koras_import import (
    PROPERTY_NAME,
    TEMPLATE_FORMATS,
    FieldKind,
    FieldSpec,
    Format,
    ImportTarget,
    Operation,
    TemplateRefused,
    compare,
    example_for,
    fingerprint,
    format_hint,
    identity,
    parse_identity,
    read_header,
    read_workbook,
    render,
    render_csv,
    template_identity,
)
from koras_import.reading_xlsx import inspect

if TYPE_CHECKING:
    from openpyxl import Workbook

ACCOUNTS = ImportTarget(
    key="crm.accounts",
    label_key="import.target.crm.accounts",
    permission="imports.manage",
    fields=(
        FieldSpec(
            "email",
            "import.field.email",
            kind=FieldKind.EMAIL,
            required=True,
            help="The address the account signs in with.",
        ),
        FieldSpec("name", "import.field.name", required=True, max_length=80, example="Acme Ltd"),
        FieldSpec("seats", "import.field.seats", kind=FieldKind.INTEGER),
        FieldSpec("balance", "import.field.balance", kind=FieldKind.DECIMAL),
        FieldSpec("joined", "import.field.joined", kind=FieldKind.DATE),
        FieldSpec("active", "import.field.active", kind=FieldKind.BOOLEAN),
        FieldSpec("tier", "import.field.tier", options=("basic", "pro")),
        # A name a spreadsheet would evaluate, to prove the guard reaches
        # every string the renderer writes.
        FieldSpec("note", "import.field.note", example="=HYPERLINK(\"x\")", help="+plus"),
    ),
    match_keys=("email",),
    operations=(Operation.SKIP_DUPLICATE, Operation.UPSERT),
    formats=(Format.CSV, Format.XLSX),
    version=3,
)


# ── the vocabulary ───────────────────────────────────────────────────────────


def test_json_is_in_the_vocabulary_and_not_rendered() -> None:
    """ADR 0012 D4: deferred by decision, refused by name rather than by absence."""
    assert Format.JSON not in TEMPLATE_FORMATS
    json_target = replace(ACCOUNTS, formats=(Format.CSV, Format.JSON))
    with pytest.raises(TemplateRefused, match="json"):
        render(json_target, Format.JSON)


def test_a_format_the_target_does_not_accept_is_refused() -> None:
    csv_only = replace(ACCOUNTS, formats=(Format.CSV,))
    with pytest.raises(TemplateRefused, match="xlsx"):
        render(csv_only, Format.XLSX)


def test_every_kind_has_a_synthesised_example_and_a_hint() -> None:
    for kind in FieldKind:
        spec = FieldSpec("f", "k", kind=kind)
        assert example_for(spec), kind
    assert example_for(FieldSpec("t", "k", options=("x", "y"))) == "x"
    assert example_for(FieldSpec("n", "k", example="Given")) == "Given"
    assert format_hint(FieldSpec("d", "k", kind=FieldKind.DATE)) == "YYYY-MM-DD"
    assert "basic" in format_hint(FieldSpec("t", "k", options=("basic", "pro")))


# ── CSV ──────────────────────────────────────────────────────────────────────


def test_the_csv_is_a_header_and_nothing_else() -> None:
    rendered = render(ACCOUNTS, Format.CSV)
    assert rendered.filename == "crm-accounts-template-v3.csv"
    assert rendered.media_type.startswith("text/csv")
    raw = rendered.content
    assert raw.startswith("﻿".encode())
    lines = raw.decode("utf-8-sig").split("\r\n")
    assert lines[1:] == [""], "a CSV template carries no example row and no metadata"
    assert lines[0] == "email,name,seats,balance,joined,active,tier,note"


def test_the_csv_header_maps_straight_back_onto_the_target() -> None:
    text = render_csv(ACCOUNTS).decode("utf-8-sig")
    header = read_header(text.splitlines(keepends=True), delimiter=",")
    verdict = compare(ACCOUNTS, header.columns)
    assert verdict.verdict == "compatible"
    assert verdict.missing_required == ()
    assert verdict.unknown_columns == ()


# ── XLSX ─────────────────────────────────────────────────────────────────────


def _book(raw: bytes) -> Workbook:
    from openpyxl import load_workbook

    return load_workbook(io.BytesIO(raw))


def test_the_workbook_has_a_data_sheet_and_an_instructions_sheet() -> None:
    rendered = render(ACCOUNTS, Format.XLSX)
    assert rendered.filename == "crm-accounts-template-v3.xlsx"
    book = _book(rendered.content)
    assert book.sheetnames[:2] == ["Data", "Instructions"]
    data = book["Data"]
    header = [cell.value for cell in data[1]]
    assert header == ["email", "name", "seats", "balance", "joined", "active", "tier", "note"]
    assert data.max_row == 1, "no example row on the sheet a person fills in"
    assert data.freeze_panes == "A2"


def test_required_columns_are_marked_and_every_column_has_a_comment() -> None:
    data = _book(render(ACCOUNTS, Format.XLSX).content)["Data"]
    filled = {cell.value for cell in data[1] if cell.fill.fill_type == "solid"}
    assert filled == {"email", "name"}
    for cell in data[1]:
        assert cell.comment is not None, cell.value
        assert "Example:" in cell.comment.text
    assert "signs in with" in data["A1"].comment.text


def test_the_instructions_sheet_lists_every_field() -> None:
    sheet = _book(render(ACCOUNTS, Format.XLSX).content)["Instructions"]
    rows = [[cell.value for cell in row] for row in sheet.iter_rows()]
    flat = [str(value) for row in rows for value in row if value is not None]
    assert "crm.accounts" in flat
    assert "v3" in flat
    assert fingerprint(ACCOUNTS) in flat
    table = rows[rows.index(next(r for r in rows if r[0] == "Column")) + 1 :]
    assert [row[0] for row in table] == list(ACCOUNTS.field_names)
    by_name = {row[0]: row for row in table}
    assert by_name["email"][1] == "required"
    assert by_name["seats"][1] == "optional"
    assert by_name["tier"][2] == "choice"
    assert by_name["tier"][4] == "basic, pro"
    assert by_name["joined"][3] == "YYYY-MM-DD"
    assert by_name["name"][5] == "Acme Ltd"


def test_enumerated_date_and_number_columns_carry_data_validation() -> None:
    data = _book(render(ACCOUNTS, Format.XLSX).content)["Data"]
    validations = {v.type: v for v in data.data_validations.dataValidation}
    assert set(validations) == {"list", "date", "whole", "decimal"}
    assert validations["list"].formula1 == '"basic,pro"'
    ranges = str(validations["list"].sqref)
    assert ranges.startswith("G2:G")


def test_a_long_option_set_is_referenced_rather_than_inlined() -> None:
    options = tuple(f"option-number-{index:03d}" for index in range(40))
    wide = replace(
        ACCOUNTS,
        fields=(FieldSpec("kind", "import.field.kind", options=options),),
        match_keys=(),
        operations=(Operation.CREATE,),
    )
    book = _book(render(wide, Format.XLSX).content)
    assert "Lists" in book.sheetnames
    validation = book["Data"].data_validations.dataValidation[0]
    assert validation.formula1.startswith("=Lists!")
    assert [row[0].value for row in book["Lists"].iter_rows()] == list(options)


def test_every_string_the_renderer_writes_opens_as_text() -> None:
    """The guard reaches the example, the help, the header and the sheet."""
    book = _book(render(ACCOUNTS, Format.XLSX).content)
    values = [
        cell.value
        for sheet in book.worksheets
        for row in sheet.iter_rows()
        for cell in row
        if isinstance(cell.value, str)
    ]
    dangerous = [value for value in values if value[:1] in "=+-@"]
    assert dangerous == []
    assert any(value.startswith("'=HYPERLINK") for value in values)
    assert any(value.startswith("'+plus") for value in values)
    comments = [cell.comment.text for cell in book["Data"][1] if cell.comment]
    assert all(not text.startswith(("=", "+", "-", "@")) for text in comments)


# ── identity ─────────────────────────────────────────────────────────────────


def test_the_workbook_carries_the_identity_as_a_property_and_reads_it_back() -> None:
    raw = render(ACCOUNTS, Format.XLSX).content
    book = _book(raw)
    props = book.custom_doc_props.props  # type: ignore[attr-defined]
    stored = {prop.name: prop.value for prop in props}
    assert stored[PROPERTY_NAME] == identity(ACCOUNTS)
    assert template_identity(inspect(raw)) == identity(ACCOUNTS)
    parsed = parse_identity(identity(ACCOUNTS))
    assert parsed is not None
    assert (parsed.target, parsed.version, parsed.fingerprint) == (
        "crm.accounts",
        3,
        fingerprint(ACCOUNTS),
    )


def test_the_rendered_workbook_reads_as_compatible_and_current() -> None:
    raw = render(ACCOUNTS, Format.XLSX).content
    read = read_workbook(raw, limit=10, ceiling=100)
    assert read.sheet == "Data"
    assert read.header.columns == ACCOUNTS.field_names
    assert read.rows == ()
    verdict = compare(ACCOUNTS, read.header.columns, found=read.identity)
    assert verdict.verdict == "compatible"
    assert verdict.version_found == 3
    assert verdict.stale is False


def test_a_template_from_an_older_version_is_named_stale_and_still_usable() -> None:
    older = replace(ACCOUNTS, version=2)
    raw = render(older, Format.XLSX).content
    read = read_workbook(raw, limit=10, ceiling=100)
    verdict = compare(ACCOUNTS, read.header.columns, found=read.identity)
    assert verdict.stale is True
    assert verdict.version_found == 2
    assert verdict.compatible is True, "an older template whose header still fits is not refused"


def test_a_shape_change_without_a_bump_is_still_recognised() -> None:
    """The fingerprint does the job the version cannot: a forgotten bump."""
    renamed = replace(
        ACCOUNTS,
        fields=ACCOUNTS.fields[:-1] + (FieldSpec("remark", "import.field.remark"),),
    )
    assert fingerprint(renamed) != fingerprint(ACCOUNTS)
    raw = render(ACCOUNTS, Format.XLSX).content
    read = read_workbook(raw, limit=10, ceiling=100)
    verdict = compare(renamed, read.header.columns, found=read.identity)
    assert verdict.stale is True
    assert verdict.verdict == "unknown_columns"
    assert verdict.unknown_columns == ("note",)


def test_the_fingerprint_ignores_what_a_file_does_not_depend_on() -> None:
    relabelled = replace(
        ACCOUNTS,
        fields=tuple(replace(spec, help="changed", example="changed") for spec in ACCOUNTS.fields),
        version=9,
    )
    assert fingerprint(relabelled) == fingerprint(ACCOUNTS)
    narrowed = replace(
        ACCOUNTS,
        fields=tuple(
            replace(spec, options=("basic",)) if spec.name == "tier" else spec
            for spec in ACCOUNTS.fields
        ),
    )
    assert fingerprint(narrowed) != fingerprint(ACCOUNTS)


def test_an_ordinary_file_with_no_identity_is_judged_by_its_header_alone() -> None:
    verdict = compare(ACCOUNTS, ("Email", "Name", "Phone"), found=None)
    assert verdict.verdict == "unknown_columns"
    assert verdict.unknown_columns == ("Phone",)
    assert verdict.version_found is None
    assert verdict.stale is False
    missing = compare(ACCOUNTS, ("Email", "Phone"))
    assert missing.verdict == "incompatible"
    assert missing.missing_required == ("name",)


def test_an_identity_from_another_target_is_no_identity() -> None:
    verdict = compare(ACCOUNTS, ACCOUNTS.field_names, found="shop.customers/v1/abcdefabcdef")
    assert verdict.version_found is None
    assert verdict.stale is False
    assert parse_identity("garbage") is None
    assert parse_identity("a.b/vx/abc") is None
    assert parse_identity("") is None
