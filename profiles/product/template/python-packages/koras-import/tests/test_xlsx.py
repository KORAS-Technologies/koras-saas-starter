"""A workbook reads as the CSV of the same rows would, and is bounded first.

The three typed-value findings the Phase 2 review carried -- IMP2-18 (`nan`
and `inf` pass as decimals), IMP2-19 (a parsed date is discarded) and IMP2-21
(a NUL byte passes every check) -- stop being carried here, because a workbook
cell arrives typed and the reader has to decide what text it becomes. Every
Excel-native value the brief names has a case: string, integer, decimal,
boolean, date, datetime, blank, option.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime
from decimal import Decimal

import pytest
from koras_import import (
    DECOMPRESSED_CEILING,
    FieldKind,
    FieldSpec,
    Format,
    ImportTarget,
    Operation,
    ReadRefused,
    canonical,
    cell_text,
    header_from,
    normalise_row,
    read_header,
    read_rows,
    read_workbook,
    resolve,
    row_from,
    validate,
)
from koras_import.reading_xlsx import MAX_PROPERTY_BYTES, template_identity

CUSTOMERS = ImportTarget(
    key="shop.customers",
    label_key="import.target.shop.customers",
    permission="imports.manage",
    fields=(
        FieldSpec("email", "import.field.email", kind=FieldKind.EMAIL, required=True),
        FieldSpec("name", "import.field.name", required=True),
        FieldSpec("seats", "import.field.seats", kind=FieldKind.INTEGER),
        FieldSpec("balance", "import.field.balance", kind=FieldKind.DECIMAL),
        FieldSpec("joined", "import.field.joined", kind=FieldKind.DATE),
        FieldSpec("active", "import.field.active", kind=FieldKind.BOOLEAN),
        FieldSpec("tier", "import.field.tier", options=("Basic", "Pro")),
    ),
    match_keys=("email",),
    operations=(Operation.SKIP_DUPLICATE, Operation.UPSERT),
    formats=(Format.CSV, Format.XLSX),
)

MAPPING = {name: name for name in CUSTOMERS.field_names}


def workbook(rows: list[list[object]], *, sheet: str = "Sheet1") -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    ws = book.active
    assert ws is not None
    ws.title = sheet
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


HEADER: list[object] = ["email", "name", "seats", "balance", "joined", "active", "tier"]


# ── every Excel-native value ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("Ada", "Ada"),
        (42, "42"),
        (42.0, "42"),
        (3.5, "3.5"),
        (Decimal("19.99"), "19.99"),
        (True, "true"),
        (False, "false"),
        (date(2026, 1, 31), "2026-01-31"),
        (datetime(2026, 1, 31, 0, 0), "2026-01-31"),
        (datetime(2026, 1, 31, 9, 30), "2026-01-31 09:30:00"),
        (float("nan"), "nan"),
        (float("inf"), "inf"),
    ],
)
def test_a_typed_cell_becomes_the_text_a_csv_would_have_carried(
    value: object, expected: str
) -> None:
    assert cell_text(value) == expected


def test_a_workbook_and_its_csv_validate_to_the_same_verdict() -> None:
    rows: list[list[object]] = [
        HEADER,
        ["ada@example.com", "Ada", 3, 19.99, date(2026, 1, 31), True, "pro"],
        ["not-an-address", "", 2.5, "#NUM!", datetime(2026, 1, 31, 9, 30), "maybe", "gold"],
    ]
    read = read_workbook(workbook(rows), limit=100, ceiling=1000)
    resolved = resolve(CUSTOMERS, read.header.columns, MAPPING)
    from_xlsx = validate(CUSTOMERS, resolved, read.rows)

    text = (
        "email,name,seats,balance,joined,active,tier\r\n"
        "ada@example.com,Ada,3,19.99,2026-01-31,true,pro\r\n"
        "not-an-address,,2.5,#NUM!,2026-01-31 09:30:00,maybe,gold\r\n"
    )
    lines = text.splitlines(keepends=True)
    header = read_header(lines, delimiter=",")
    from_csv = validate(CUSTOMERS, resolve(CUSTOMERS, header.columns, MAPPING), read_rows(
        lines, header=header, delimiter=",", limit=100
    ))

    assert from_xlsx.rows == from_csv.rows == 2
    assert from_xlsx.valid == from_csv.valid == 1
    assert {(e.row, e.field, e.code) for e in from_xlsx.errors} == {
        (e.row, e.field, e.code) for e in from_csv.errors
    }
    codes = {e.field: e.code for e in from_xlsx.errors}
    assert codes["email"] == "import.error.email"
    assert codes["name"] == "import.error.required"
    assert codes["seats"] == "import.error.integer"
    # A spreadsheet has no NaN: a division by zero is the error string
    # `#NUM!`, which reads as text and fails the number check. The NaN a
    # Python float can carry is covered by `cell_text` above (IMP2-18).
    assert codes["balance"] == "import.error.decimal"
    assert codes["joined"] == "import.error.date", "a time of day is not a date"
    assert codes["active"] == "import.error.boolean"
    assert codes["tier"] == "import.error.not_an_option"


def test_the_writer_receives_one_canonical_shape_whatever_the_source() -> None:
    """IMP2-19. The decision the validator made survives to the writer."""
    typed: list[list[object]] = [
        HEADER,
        ["Ada@Example.com", "Ada", 3.0, 1234.5, date(2025, 12, 31), True, "PRO"],
    ]
    read = read_workbook(workbook(typed), limit=10, ceiling=100)
    resolved = resolve(CUSTOMERS, read.header.columns, MAPPING)
    row = normalise_row(CUSTOMERS, resolved, read.rows[0])
    assert row == {
        "email": "Ada@Example.com",
        "name": "Ada",
        "seats": "3",
        "balance": "1234.5",
        "joined": "2025-12-31",
        "active": "true",
        "tier": "Pro",
    }
    spec = CUSTOMERS.spec("joined")
    assert canonical(spec, "31.12.2025") == "2025-12-31"
    assert canonical(spec, "31/12/2025") == "2025-12-31"
    assert canonical(CUSTOMERS.spec("balance"), "1.234,50") == "1234.50"
    assert canonical(CUSTOMERS.spec("balance"), "1,234.50") == "1234.50"
    assert canonical(CUSTOMERS.spec("active"), "Nein") == "false"
    assert canonical(CUSTOMERS.spec("tier"), "basic") == "Basic"
    assert canonical(CUSTOMERS.spec("name"), " kept as typed ") == " kept as typed "


def test_a_control_character_is_removed_at_the_reader_for_every_format() -> None:
    """IMP2-21. A NUL in row forty thousand discarded all forty thousand."""
    # openpyxl refuses to *write* a control character, so the workbook half
    # is asserted on the row rule both readers share rather than on a file
    # this library cannot produce; a workbook from another writer reaches the
    # same function.
    header = header_from(["email", "name"])
    built = row_from(2, ["a@example.com", "Ada\x00\x07"], header)
    assert built.cells["name"] == "Ada"
    lines = "email,name\r\na@example.com,A\x00da\x01\r\n".splitlines(keepends=True)
    header = read_header(lines, delimiter=",")
    csv_rows = list(read_rows(lines, header=header, delimiter=",", limit=10))
    assert csv_rows[0].cells["name"] == "Ada"


# ── the header and the rows ──────────────────────────────────────────────────


def test_the_data_sheet_is_preferred_and_the_first_sheet_is_the_fallback() -> None:
    from openpyxl import Workbook

    book = Workbook()
    first = book.active
    assert first is not None
    first.title = "Cover"
    first.append(["nothing", "here"])
    data = book.create_sheet("Data")
    data.append(["email", "name"])
    data.append(["a@example.com", "Ada"])
    out = io.BytesIO()
    book.save(out)
    read = read_workbook(out.getvalue(), limit=10, ceiling=10)
    assert read.sheet == "Data"
    assert read.header.columns == ("email", "name")

    fallback = read_workbook(
        workbook([["email"], ["a@example.com"]], sheet="Export"), limit=10, ceiling=10
    )
    assert fallback.sheet == "Export"


def test_row_numbers_blank_rows_and_ragged_rows_follow_the_csv_rules() -> None:
    rows: list[list[object]] = [
        ["email", "name", ""],
        ["a@example.com", "Ada"],
        [None, None, None],
        ["b@example.com", "Bo", "extra", "more"],
    ]
    read = read_workbook(workbook(rows), limit=10, ceiling=10)
    assert read.header.columns == ("email", "name")
    assert [row.number for row in read.rows] == [2, 4]
    assert read.rows[0].short is False
    assert read.rows[1].long is True
    assert read.rows_seen == 2


def test_counting_stops_past_the_ceiling_and_rows_stop_at_the_limit() -> None:
    rows: list[list[object]] = [["email"]]
    rows.extend([f"p{i}@example.com"] for i in range(20))
    read = read_workbook(workbook(rows), limit=5, ceiling=8)
    assert len(read.rows) == 5
    assert read.rows_seen == 9, "one past the ceiling, and no further"


def test_an_empty_workbook_and_a_headerless_one_are_refused_with_a_reason() -> None:
    with pytest.raises(ReadRefused, match="empty"):
        read_workbook(workbook([]), limit=10, ceiling=10)
    with pytest.raises(ReadRefused, match="names no columns"):
        read_workbook(workbook([[None, None]]), limit=10, ceiling=10)


def test_a_formula_contributes_its_cached_value_and_never_runs() -> None:
    from openpyxl import Workbook

    book = Workbook()
    ws = book.active
    assert ws is not None
    ws.append(["email", "name"])
    ws.append(["a@example.com", '=HYPERLINK("https://attacker.test","x")'])
    out = io.BytesIO()
    book.save(out)
    read = read_workbook(out.getvalue(), limit=10, ceiling=10)
    # openpyxl never calculated it, so the cached value is nothing.
    assert read.rows[0].cells["name"] == ""


# ── bounded before it is opened ──────────────────────────────────────────────


def test_what_is_not_a_workbook_is_refused_as_such() -> None:
    with pytest.raises(ReadRefused, match="not a workbook"):
        read_workbook(b"email,name\r\n", limit=10, ceiling=10)
    plain = io.BytesIO()
    with zipfile.ZipFile(plain, "w") as archive:
        archive.writestr("readme.txt", "no workbook here")
    with pytest.raises(ReadRefused, match="not a workbook"):
        read_workbook(plain.getvalue(), limit=10, ceiling=10)


def test_a_workbook_with_macros_is_refused_before_it_is_opened() -> None:
    raw = workbook([["email"]])
    with_macro = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(with_macro, "w") as out:
        for info in source.infolist():
            out.writestr(info, source.read(info))
        out.writestr("xl/vbaProject.bin", b"\x00")
    with pytest.raises(ReadRefused, match="macros"):
        read_workbook(with_macro.getvalue(), limit=10, ceiling=10)


def test_a_workbook_claiming_more_than_the_ceiling_is_refused_from_the_directory() -> None:
    """The zip directory says what each entry expands to; nothing is inflated."""
    raw = workbook([["email"]])
    bomb = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(bomb, "w") as out:
        for info in source.infolist():
            out.writestr(info, source.read(info))
        # Lie in the directory: a tiny entry whose recorded size is enormous.
        info = zipfile.ZipInfo("xl/big.bin")
        out.writestr(info, b"x")
    data = bytearray(bomb.getvalue())
    # Patch the central-directory uncompressed size of the last entry.
    marker = data.rfind(b"xl/big.bin")
    header = data.rfind(b"PK\x01\x02", 0, marker)
    size_at = header + 24
    data[size_at : size_at + 4] = (DECOMPRESSED_CEILING + 1).to_bytes(4, "little")
    with pytest.raises(ReadRefused, match="expand"):
        read_workbook(bytes(data), limit=10, ceiling=10)


def test_an_oversized_or_entity_carrying_property_part_is_not_read() -> None:
    raw = workbook([["email"]])
    for part in (
        b"<?xml version='1.0'?><!DOCTYPE p [<!ENTITY a 'b'>]><Properties/>",
        b"<Properties>" + b" " * MAX_PROPERTY_BYTES + b"</Properties>",
    ):
        rewritten = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(rewritten, "w") as out:
            for info in source.infolist():
                out.writestr(info, source.read(info))
            out.writestr("docProps/custom.xml", part)
        with zipfile.ZipFile(io.BytesIO(rewritten.getvalue())) as archive:
            assert template_identity(archive) is None
