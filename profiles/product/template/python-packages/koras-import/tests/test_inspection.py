"""The bounded inspection: that it agrees with the readers, and that it is bounded.

GR-352B. Two kinds of assertion, and neither is worth much without the other.

**It answers what the readers answered.** `inspect_source` replaced a call to
the canonical readers in the route that draws the mapping page, so the page
must not be able to tell. `reader_view` below is what that route did until
GR-352B -- `read_workbook`, or `decode` and the three CSV functions -- and
every file in this suite is handed to both and the answers compared whole: the
header, every sample row with its number and its flags, the count, the sheet,
the identity, the delimiter, the encoding. A refusal has to be the same
sentence. The files are written by `openpyxl` where its shape is the one that
matters and by hand where it is not, and a seeded generator adds the ones
nobody thought to write.

**It is bounded.** The inspection never calls `openpyxl.load_workbook` and
never decodes a CSV whole, proved by replacing both with something that fails
the test when reached. It keeps the strings its sample points at and no
others, wherever in the table they are, measured with `tracemalloc` while the
table is many times what it may hold. And it stops: past the row ceiling the
sheet is not walked, and a sample that would not fit its budget ends early.

The two places the inspection is deliberately *not* the reader are asserted
as what they are, at the end, so none of them can be mistaken for agreement.

`test_inspection_memory.py` asks the kernel the same question on Linux.
"""

from __future__ import annotations

import io
import random
import tracemalloc
import zipfile
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from typing import Any
from xml.sax.saxutils import escape

import pytest
from koras_import import (
    MAX_CELL,
    MAX_SAMPLE_CHARACTERS,
    PROVISIONAL_LIMITS,
    FieldSpec,
    Format,
    ImportTarget,
    Operation,
    PreflightRefused,
    ReadRefused,
    RefusalCode,
    SafetyLimits,
    count_rows,
    decode,
    inspect_source,
    inspection,
    preflight,
    read_header,
    read_rows,
    read_workbook,
    render_xlsx,
    sniff_delimiter,
)

#: What `openpyxl` says of a hand-written stylesheet that declares no named
#: style. It is the canonical reader speaking, about a fixture, in this file.
pytestmark = pytest.mark.filterwarnings("ignore:Workbook contains no default style")

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELS ="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships"
EMOJI = "\U0001f600"

#: An envelope nothing in this file can reach, for the tests that measure the
#: inspection rather than the refusal in front of it.
WIDE_OPEN = SafetyLimits(
    max_decoded_string_bytes=1 << 40, max_cells=1 << 40, max_columns=1 << 20
)


# ── the two answers, side by side ────────────────────────────────────────────


def reader_view(
    raw: bytes, fmt: Format, sample: int, ceiling: int, limits: SafetyLimits
) -> tuple[Any, ...]:
    """What the analysis route read until GR-352B, by the readers themselves."""
    if fmt is Format.XLSX:
        read = read_workbook(raw, limit=sample, ceiling=ceiling, limits=limits)
        return (read.header, read.rows, read.rows_seen, read.sheet, read.identity, ",", "utf-8")
    decoded = decode(raw)
    delimiter = sniff_delimiter(decoded.text)
    lines = decoded.text.splitlines(keepends=True)
    header = read_header(lines, delimiter=delimiter)
    rows = tuple(read_rows(lines, header=header, delimiter=delimiter, limit=sample))
    seen = count_rows(lines, delimiter=delimiter, ceiling=ceiling)
    return (header, rows, seen, None, None, delimiter, decoded.encoding)


def inspected_view(
    raw: bytes, fmt: Format, sample: int, ceiling: int, limits: SafetyLimits
) -> tuple[Any, ...]:
    found = inspect_source(raw, fmt, limits, sample=sample, ceiling=ceiling)
    assert found.over_ceiling is (found.rows_seen > ceiling)
    assert found.sample_cut is False
    return (
        found.header,
        found.rows,
        found.rows_seen,
        found.sheet,
        found.identity,
        found.delimiter,
        found.encoding,
    )


#: Sample and ceiling, in the combinations that take different paths: the
#: route's own, a sample shorter than the file, a ceiling shorter than the
#: file, the mapping route's no-sample read, and a ceiling under the sample.
SHAPES = [(200, 1000), (2, 1000), (200, 3), (0, 1000), (5, 2)]


def agree(
    raw: bytes,
    fmt: Format,
    *,
    limits: SafetyLimits = PROVISIONAL_LIMITS,
    shapes: Sequence[tuple[int, int]] = SHAPES,
) -> None:
    """Both answers are the same answer, or the same refusal, in every shape."""
    for sample, ceiling in shapes:
        try:
            expected = reader_view(raw, fmt, sample, ceiling, limits)
        except ReadRefused as refused:
            with pytest.raises(ReadRefused) as caught:
                inspected_view(raw, fmt, sample, ceiling, limits)
            assert str(caught.value) == str(refused), (sample, ceiling)
            assert type(caught.value) is type(refused), (sample, ceiling)
            continue
        if fmt is Format.CSV and sample == 0:
            # `read_rows` checks its limit after it yields, so a limit of zero
            # is one row. No route ever asked the reader for none; the mapping
            # route asks the inspection for none, and gets none.
            expected = (expected[0], (), *expected[2:])
        assert inspected_view(raw, fmt, sample, ceiling, limits) == expected, (sample, ceiling)


# ── building workbooks ───────────────────────────────────────────────────────


def package(parts: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name, body in parts.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def sst(items: Sequence[str]) -> str:
    """A string table from items already written as XML."""
    return f'<sst xmlns="{MAIN}">{"".join(items)}</sst>'


def plain(text: str) -> str:
    return f"<si><t>{escape(text)}</t></si>"


def worksheet(rows: str, *, before: str = "") -> str:
    return f'<worksheet xmlns="{MAIN}">{before}<sheetData>{rows}</sheetData></worksheet>'


def letters(column: int) -> str:
    name = ""
    while column:
        column, rest = divmod(column - 1, 26)
        name = chr(65 + rest) + name
    return name


def shared(index: int, ref: str = "", style: str = "") -> str:
    return f'<c{_ref(ref)}{style} t="s"><v>{index}</v></c>'


def inline(text: str, ref: str = "") -> str:
    return f'<c{_ref(ref)} t="inlineStr"><is><t>{escape(text)}</t></is></c>'


def number(text: str, ref: str = "", style: int | None = None) -> str:
    styled = "" if style is None else f' s="{style}"'
    return f"<c{_ref(ref)}{styled}><v>{text}</v></c>"


def _ref(ref: str) -> str:
    return f' r="{ref}"' if ref else ""


def row(cells: str, at: int | None = None) -> str:
    named = "" if at is None else f' r="{at}"'
    return f"<row{named}>{cells}</row>"


def grid(rows: Sequence[Sequence[str]]) -> str:
    """Rows of cells already written as XML, numbered and referenced."""
    return "".join(
        row(
            "".join(
                cell.replace("<c", f'<c r="{letters(column)}{position}"', 1)
                for column, cell in enumerate(cells, start=1)
            ),
            position,
        )
        for position, cells in enumerate(rows, start=1)
    )


def styles(formats: dict[int, str], cell_formats: Sequence[int]) -> str:
    """A stylesheet declaring these number formats and these cell formats."""
    declared = "".join(
        f'<numFmt numFmtId="{number}" formatCode="{escape(code)}"/>'
        for number, code in formats.items()
    )
    xfs = "".join(f'<xf numFmtId="{number}"/>' for number in cell_formats)
    return (
        f'<styleSheet xmlns="{MAIN}"><numFmts>{declared}</numFmts>'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0"/></cellStyleXfs>'
        f"<cellXfs>{xfs}</cellXfs></styleSheet>"
    )


def book(
    sheet: str,
    strings: str | None = None,
    *,
    sheets: dict[str, str] | None = None,
    strings_part: str = "xl/sharedStrings.xml",
    stylesheet: str | None = None,
    properties: str = "",
    extra: dict[str, str | bytes] | None = None,
) -> bytes:
    """A workbook `openpyxl` will open, around the XML a test cares about."""
    named = sheets or {"Sheet1": sheet}
    overrides = [
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    ]
    entries = []
    relations = []
    parts: dict[str, str | bytes] = {}
    for position, (name, body) in enumerate(named.items(), start=1):
        overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{position}.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
        entries.append(f'<sheet name="{name}" sheetId="{position}" r:id="rId{position}"/>')
        relations.append(
            f'<Relationship Id="rId{position}" Type="{RELS}/worksheet" '
            f'Target="worksheets/sheet{position}.xml"/>'
        )
        parts[f"xl/worksheets/sheet{position}.xml"] = body
    if strings is not None:
        overrides.append(
            f'<Override PartName="/{strings_part}" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        )
        parts[strings_part] = strings
    if stylesheet is not None:
        overrides.append(
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        )
        parts["xl/styles.xml"] = stylesheet
    parts["[Content_Types].xml"] = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        + "".join(overrides)
        + "</Types>"
    )
    parts["_rels/.rels"] = (
        f'<Relationships xmlns="{PACKAGE}"><Relationship Id="rId1" '
        f'Type="{RELS}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    )
    parts["xl/workbook.xml"] = (
        f'<workbook xmlns="{MAIN}" xmlns:r="{RELS}">{properties}'
        f'<sheets>{"".join(entries)}</sheets></workbook>'
    )
    parts["xl/_rels/workbook.xml.rels"] = (
        f'<Relationships xmlns="{PACKAGE}">{"".join(relations)}</Relationships>'
    )
    parts.update(extra or {})
    return package(parts)


def written(sheets: dict[str, Sequence[Sequence[object]]]) -> bytes:
    """A workbook as `openpyxl` itself writes one, sheet by sheet."""
    from openpyxl import Workbook

    made = Workbook()
    first = made.active
    assert first is not None
    made.remove(first)
    for title, rows in sheets.items():
        sheet = made.create_sheet(title)
        for cells in rows:
            sheet.append(list(cells))
    buffer = io.BytesIO()
    made.save(buffer)
    return buffer.getvalue()


def one(rows: Sequence[Sequence[object]]) -> bytes:
    return written({"Sheet1": rows})


# ── CSV: the same answer ─────────────────────────────────────────────────────

CSV_FILES: dict[str, bytes] = {
    "plain": b"Name,Email\nAda,ada@example.com\nGrace,grace@example.com\n",
    "byte-order-mark": "﻿Name,Email\nZoë,zoe@example.com\n".encode(),
    "cp1252-semicolons": "Name;Straße\nJürgen;Köln\nRenée;Besançon\n".encode("cp1252"),
    "no-strict-encoding": b"Name,Email\n\x81dam,adam@example.com\nEve,eve@example.com\n",
    "tabs": b"Name\tEmail\nAda\tada@example.com\n",
    "pipes": b"Name|Email|Note\nAda|ada@example.com|a, b; c\n",
    "quoted": (
        b'Name,Note,Amount\n"Lovelace, Ada","said ""hello""\nand left",1\n'
        b'Grace,"a;b|c\td",2\n'
    ),
    "blank-lines": b"Name,Email\n\nAda,a@x.io\n , \n\n\nGrace,g@x.io\n\n",
    "duplicate-and-unnamed-headers": b"Name,Name,,Email,\nAda,Lovelace,x,a@x.io,y\n",
    "ragged": b"A,B,C\n1\n1,2,3,4,5\n1,2\n",
    "controls-and-spaces": b"Name,Note\n  Ada \x00 ,\x07bell\x1f\n\tGrace\t, x \n",
    "windows-line-endings": b"Name,Email\r\nAda,a@x.io\r\n\r\nGrace,g@x.io\r\n",
    "old-mac-line-endings": b"Name,Email\rAda,a@x.io\rGrace,g@x.io\r",
    "no-final-newline": b"Name,Email\nAda,a@x.io",
    "header-only": b"Name,Email\n",
    "empty": b"",
    "blank-first-line": b"\nName,Email\nAda,a@x.io\n",
    "one-column": b"Name\nAda\nGrace\nEdsger\nBarbara\nDonald\nAlan\n",
    "semicolon-in-a-comma-file": b"Name;Title,Email\nAda;Countess,a@x.io\n",
    "astral": f"Name,Mood\nAda,{EMOJI}\nGrace,fine\n".encode(),
    "formula-triggers": b"Name,Sum\n=cmd|' /C calc'!A0,+1\n@x,-2\n",
    "many-rows": b"N,M\n" + b"".join(b"%d,x\n" % n for n in range(1500)),
}


@pytest.mark.parametrize("name", sorted(CSV_FILES))
def test_a_csv_is_inspected_as_the_reader_read_it(name: str) -> None:
    agree(CSV_FILES[name], Format.CSV)


def test_a_csv_refusal_the_safety_pass_makes_first_is_still_a_refusal() -> None:
    # The reader stopped at the row it was asked for and never met the broken
    # quote further down; the safety pass reads to the end and refuses. That
    # was true of the analysis before this slice too -- the pass has been
    # ahead of it since GR-352A -- so it is asserted as a refusal, not as
    # agreement with a reader that would not have noticed.
    raw = b'Name\nAda\n"never closed\n' + b"more\n" * 40_000
    with pytest.raises(PreflightRefused) as caught:
        inspect_source(raw, Format.CSV, sample=1, ceiling=1)
    assert caught.value.code is RefusalCode.MALFORMED


def test_csv_chunk_boundaries_change_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    # A multi-byte character, a `\r\n` and a quoted line break, each of which
    # a boundary can fall inside. The header is shorter than every chunk size
    # used, because the delimiter is sniffed from the first chunk -- which in
    # production is never smaller than the sample the reader sniffs from.
    body = "".join(f'{n},"multi\nline {EMOJI}",złoty\r\n' for n in range(300))
    raw = ("id,note,amount\r\n" + body).encode("utf-8")
    whole = inspected_view(raw, Format.CSV, 200, 1000, PROVISIONAL_LIMITS)
    assert whole == reader_view(raw, Format.CSV, 200, 1000, PROVISIONAL_LIMITS)
    for size in (17, 23, 64, 257):
        monkeypatch.setattr(inspection, "_CHUNK", size)
        assert inspected_view(raw, Format.CSV, 200, 1000, PROVISIONAL_LIMITS) == whole


# ── XLSX: the same answer, for what `openpyxl` writes ────────────────────────

TYPED: list[list[object]] = [
    ["Name", "Count", "Price", "Active", "Born", "Seen", "At", "Took", 2026, None, "Note"],
    ["Ada", 42, 1.5, True, date(1815, 12, 10), datetime(2025, 1, 2, 3, 4, 5), time(13, 5), None],
    ["Grace", -7, 42.0, False, date(2025, 12, 31), datetime(2025, 6, 1), time(0, 0, 1), None],
    ["Big", 10**14, 1e20, None, None, None, None, timedelta(hours=30, minutes=1)],
    ["Small", 0, 1e-7, None, date(1900, 1, 1), datetime(1900, 2, 28, 12), None, timedelta(0)],
    [None, None, None, None, None, None, None, None, None, None, "only a note"],
    ["  padded  ", "007", 3.14159265358979, "true", "2025-01-01", "", " ", "x  y"],
]

WRITTEN: dict[str, bytes] = {
    "typed": one(TYPED),
    "data-sheet-preferred": written(
        {"Lookup": [["Code"], ["x"]], "Data": [["Name"], ["Ada"], ["Grace"]]}
    ),
    "first-sheet-fallback": written(
        {"Customers": [["Name"], ["Ada"]], "Other": [["Zed"], ["z"], ["z"]]}
    ),
    "blank-rows": one([["Name", "Email"], [], ["Ada", "a@x.io"], [None, None], [], ["Grace"]]),
    "ragged": one([["A", "B", "C"], [1], [1, 2, 3, 4, 5], [None, None, 3]]),
    "duplicate-and-unnamed-headers": one(
        [["Name", "Name", None, "Email", "Name"], ["a", "b", "c", "d", "e"]]
    ),
    "header-only": one([["Name", "Email"]]),
    "numeric-header": one([[1, 2.5, True, date(2025, 1, 1)], ["a", "b", "c", "d"]]),
    "many-rows": one([["N", "S"], *[[n, f"row {n}"] for n in range(1500)]]),
    "repeated-strings": one([["A", "B"], *[["same", "same"] for _ in range(300)]]),
    "empty-strings": one([["A", "B"], ["", ""], ["", "x"], [" ", ""]]),
    "astral": one([["Name", "Mood"], ["Ada", EMOJI * 3], [EMOJI, "fine"]]),
}


@pytest.mark.parametrize("name", sorted(WRITTEN))
def test_a_workbook_openpyxl_wrote_is_inspected_as_the_reader_read_it(name: str) -> None:
    agree(WRITTEN[name], Format.XLSX)


def test_a_typed_cell_is_the_text_the_reader_makes_of_it() -> None:
    # The comparison above, with the values spelled out once so a change to
    # both sides at the same time cannot pass unnoticed.
    found = inspect_source(WRITTEN["typed"], Format.XLSX, sample=200, ceiling=1000)
    assert found.header.columns == (
        "Name", "Count", "Price", "Active", "Born", "Seen", "At", "Took", "2026",
        "column_10", "Note",
    )  # fmt: skip
    ada, grace, big, small, note, padded = (row.cells for row in found.rows)
    assert (ada["Count"], ada["Price"], ada["Active"]) == ("42", "1.5", "true")
    assert (ada["Born"], ada["Seen"], ada["At"]) == (
        "1815-12-10",
        "2025-01-02 03:04:05",
        "13:05:00",
    )
    assert (grace["Count"], grace["Price"], grace["Active"]) == ("-7", "42", "false")
    assert (grace["Born"], grace["Seen"]) == ("2025-12-31", "2025-06-01")
    assert (big["Count"], big["Price"]) == ("100000000000000", "1e+20")
    assert big["Took"] == "1 day, 6:01:00"
    assert small["Price"] == "1e-07"
    assert note["Note"] == "only a note" and note["Name"] == ""
    assert (padded["Name"], padded["Count"], padded["Took"]) == ("padded", "007", "x  y")
    assert [row.number for row in found.rows] == [2, 3, 4, 5, 6, 7]


def test_a_template_s_identity_is_read_from_the_same_place() -> None:
    target = ImportTarget(
        key="probe.accounts",
        label_key="import.target.probe.accounts",
        permission="imports.manage",
        fields=(FieldSpec("email", "import.field.email", required=True),),
        operations=(Operation.CREATE,),
        formats=(Format.CSV, Format.XLSX),
        version=3,
    )
    raw = render_xlsx(target)
    agree(raw, Format.XLSX)
    found = inspect_source(raw, Format.XLSX, sample=5, ceiling=10)
    assert found.identity is not None and found.identity.startswith("probe.accounts/v3/")
    assert found.sheet == "Data"


# ── XLSX: the same answer, for what `openpyxl` does not write ────────────────

RICH = (
    "<si><r><rPr><b/></rPr><t>Ada </t></r><r><t>Lovelace</t></r>"
    "<rPh sb=\"0\" eb=\"1\"><t>PHONETIC</t></rPh><phoneticPr fontId=\"1\"/></si>"
)

HAND: dict[str, bytes] = {
    "shared-strings": book(
        worksheet(grid([[shared(0), shared(1)], [shared(2), shared(3)], [shared(2), shared(1)]])),
        sst([plain("Name"), plain("Email"), plain("Ada"), plain("a@x.io")]),
    ),
    "rich-text-and-phonetic": book(
        worksheet(grid([[shared(0)], [shared(1)], [shared(2)]])),
        sst([plain("Name"), RICH, '<si><t xml:space="preserve">  kept  </t></si>']),
    ),
    "escaped-underscore": book(
        worksheet(grid([[shared(0)], [shared(1)], [shared(2)], [shared(3)]])),
        sst([plain("Name"), plain("a_x005F_x000D_b"), plain("x005F_"), plain("after")]),
    ),
    "empty-string-makes-a-blank-row": book(
        worksheet(
            grid(
                [
                    [shared(0), shared(1)],
                    [shared(2), shared(2)],
                    [shared(3), shared(2)],
                    [shared(2), shared(4)],
                    [shared(5), shared(2)],
                ]
            )
        ),
        sst([plain("A"), plain("B"), "<si><t></t></si>", plain("x"), "<si/>", plain(" ")]),
    ),
    "inline-strings": book(
        worksheet(
            grid(
                [
                    [inline("Name"), inline("Note")],
                    [inline("Ada"), inline("")],
                    [inline(""), inline("")],
                    [
                        '<c t="inlineStr"><is><r><t>ri</t></r><r><t>ch</t></r>'
                        '<rPh sb="0" eb="1"><t>NO</t></rPh></is></c>',
                        '<c t="inlineStr"/>',
                    ],
                    ['<c t="inlineStr"><v>ignored</v></c>', inline("kept")],
                ]
            )
        )
    ),
    "typed-by-attribute": book(
        worksheet(
            grid(
                [
                    [inline("Kind"), inline("Value")],
                    [inline("cached string"), '<c t="str"><f>A1&amp;"x"</f><v>Kindx</v></c>'],
                    [inline("error"), '<c t="e"><v>#DIV/0!</v></c>'],
                    [inline("true"), '<c t="b"><v>1</v></c>'],
                    [inline("false"), '<c t="b"><v>0</v></c>'],
                    [inline("iso date"), '<c t="d"><v>2025-03-04</v></c>'],
                    [inline("iso datetime"), '<c t="d"><v>2025-03-04T05:06:07Z</v></c>'],
                    [inline("iso time"), '<c t="d"><v>05:06:07</v></c>'],
                    [inline("unknown type"), '<c t="zz"><v>as it is</v></c>'],
                    [inline("float"), number("1.50")],
                    [inline("exponent"), number("1E3")],
                    [inline("integral float"), number("7.0")],
                    [inline("large"), number("12345678901234567890")],
                ]
            )
        )
    ),
    "formulas": book(
        worksheet(
            grid(
                [
                    [inline("A"), inline("B")],
                    ["<c><f>1+1</f><v>2</v></c>", "<c><f>NOW()</f></c>"],
                    ["<c><f>1/0</f></c>", "<c><f>A1</f></c>"],
                    ['<c t="str"><f>"=cmd"</f><v>=cmd</v></c>', "<c><v></v></c>"],
                ]
            )
        )
    ),
    "no-references": book(
        worksheet(
            row(inline("A") + inline("B") + inline("C"))
            + row(inline("1") + inline("2"))
            + row(inline("x"))
        )
    ),
    "mixed-references": book(
        worksheet(
            row(inline("A", "A1") + inline("B") + inline("D", "D1") + inline("E"), 1)
            + row(inline("1", "B2") + inline("2"), 2)
        )
    ),
    "row-gaps": book(
        worksheet(
            row(inline("Name", "A1"), 1)
            + row(inline("Ada", "A5"), 5)
            + row(inline("Grace", "A9"), 9)
            + row(inline("", "A12"), 12)
            + row(inline("Edsger", "A400"), 400)
        )
    ),
    "starts-below-row-one": book(worksheet(row(inline("Name", "A3"), 3) + row(inline("Ada"), 4))),
    "no-rows": book(worksheet("")),
    "empty-first-row": book(worksheet(row("", 1) + row(inline("Ada", "A2"), 2))),
    "first-row-of-empties": book(
        worksheet(row(inline("", "A1") + "<c r=\"B1\"/>", 1) + row(inline("Ada", "A2"), 2))
    ),
    "rows-out-of-order": book(
        worksheet(
            row(inline("Name", "A1"), 1)
            + row(inline("third", "A3"), 3)
            + row(inline("dropped", "A2"), 2)
            + row(inline("again", "A3"), 3)
            + row(inline("fourth"))
        )
    ),
    "last-cell-not-rightmost": book(
        worksheet(
            row(inline("A", "A1") + inline("B", "B1") + inline("C", "C1"), 1)
            + row(inline("3", "C2") + inline("1", "A2"), 2)
            + row(inline("3", "C3") + inline("2", "B3"), 3)
            + row(inline("first", "A4") + inline("second", "A4"), 4)
        )
    ),
    "lying-dimension": book(
        worksheet(
            grid([[inline("A"), inline("B"), inline("C")], [inline("1"), inline("2")]]),
            before='<dimension ref="B2:B2"/>',
        )
    ),
    "narrow-dimension": book(
        worksheet(
            grid([[inline("A"), inline("B")], [inline("1"), inline("2")], [inline("3")]]),
            before='<dimension ref="A1"/>',
        )
    ),
    "dates-by-style": book(
        worksheet(
            grid(
                [
                    [inline("What"), inline("Value")],
                    [inline("built-in date"), number("45000", style=1)],
                    [inline("custom date"), number("45000.5", style=2)],
                    [inline("duration"), number("1.25", style=3)],
                    [inline("time of day"), number("0.75", style=1)],
                    [inline("not a date"), number("45000", style=0)],
                    [inline("quoted letters"), number("45000", style=4)],
                    [inline("out of range"), number("99999999999", style=1)],
                    [inline("leap bug"), number("59", style=1)],
                    [inline("unknown style"), number("45000", style=40)],
                ]
            )
        ),
        stylesheet=styles(
            {164: "dd/mm/yyyy hh:mm", 165: "[h]:mm:ss", 166: '0.00 "days"'},
            [0, 14, 164, 165, 166],
        ),
    ),
    "dates-from-1904": book(
        worksheet(grid([[inline("When")], [number("45000", style=1)], [number("0.5", style=1)]])),
        stylesheet=styles({}, [0, 14]),
        properties='<workbookPr date1904="1"/>',
    ),
    "string-table-elsewhere": book(
        worksheet(grid([[shared(0)], [shared(1)]])),
        sst([plain("Name"), plain("Ada")]),
        strings_part="xl/strs/table.xml",
    ),
    "prefixed-namespace": book(
        f'<x:worksheet xmlns:x="{MAIN}"><x:sheetData>'
        '<x:row r="1"><x:c r="A1" t="inlineStr"><x:is><x:t>Name</x:t></x:is></x:c></x:row>'
        '<x:row r="2"><x:c r="A2"><x:v>5</x:v></x:c></x:row>'
        "</x:sheetData></x:worksheet>"
    ),
    "another-namespace": book(
        '<worksheet xmlns="http://purl.oclc.org/ooxml/spreadsheetml/main"><sheetData>'
        '<row r="1"><c r="A1"><v>1</v></c></row></sheetData></worksheet>'
    ),
    "data-sheet-among-three": book(
        "",
        sheets={
            "First": worksheet(grid([[inline("no")]])),
            "Data": worksheet(grid([[inline("yes")], [inline("row")]])),
            "Last": worksheet(grid([[inline("no")]])),
        },
    ),
    "whitespace-cells": book(
        worksheet(
            grid(
                [
                    [inline("A"), inline("B")],
                    [inline(" "), inline("")],
                    [inline("\t"), inline("x")],
                ]
            )
        )
    ),
    "a-cell-that-is-a-file": book(
        worksheet(grid([[inline("A")], [inline("ok")], [inline("x" * (MAX_CELL + 1))]]))
    ),
    "a-shared-string-that-is-a-file": book(
        worksheet(grid([[shared(0)], [shared(0)], [shared(1)]])),
        sst([plain("A"), plain("y" * (MAX_CELL + 7))]),
    ),
    # The reader did not refuse this until IMPORT-DEF-017 was closed: it
    # raised whatever `openpyxl` raised. It is a sentence now, and the same
    # sentence from both.
    "a-string-the-table-lacks": book(
        worksheet(grid([[shared(0)], [shared(7)]])), sst([plain("Name")])
    ),
    # A string table and a sheet whose root elements are called something
    # else. `openpyxl` reads both, by the workbook's index; since
    # IMPORT-DEF-017 the safety pass scans both, and so the inspection reads
    # them as the reader does.
    "a-string-table-with-another-root": book(
        worksheet(grid([[shared(0), shared(1)], [shared(2), shared(1)]])),
        f'<strings xmlns="{MAIN}">{plain("Name")}{plain("Email")}{plain("Ada")}</strings>',
    ),
    "a-worksheet-with-another-root": book(
        f'<sheet xmlns="{MAIN}"><sheetData>'
        f'{grid([[inline("Name")], [inline("Ada")], [inline("Grace")]])}'
        "</sheetData></sheet>"
    ),
    "a-cached-string-that-is-a-file": book(
        worksheet(
            grid([[inline("A")], [inline("ok")], [f'<c t="str"><v>{"z" * (MAX_CELL + 3)}</v></c>']])
        )
    ),
}


@pytest.mark.parametrize("name", sorted(HAND))
def test_a_workbook_written_by_hand_is_inspected_as_the_reader_read_it(name: str) -> None:
    # A cell that is a file is refused wherever the walk meets it, so those
    # three are compared in the shapes that reach their third row.
    shapes = [(200, 1000), (1, 1000), (0, 1000)] if "is-a-file" in name else SHAPES
    agree(HAND[name], Format.XLSX, shapes=shapes)


def test_the_sample_s_strings_are_found_wherever_the_table_keeps_them() -> None:
    # The first rows name the *last* strings. A sampler that kept the head of
    # the table and stopped would show a page of somebody else's text.
    count = 3000
    table = sst([plain(f"string {n}") for n in range(count)])
    rows = [[shared(count - 1 - n), shared((n * 977) % count)] for n in range(count // 2)]
    raw = book(worksheet(grid(rows)), table)
    agree(raw, Format.XLSX, shapes=[(200, 5000), (3, 5000), (0, 5000), (200, 10)])
    found = inspect_source(raw, Format.XLSX, sample=2, ceiling=5000)
    assert found.header.columns == ("string 2999", "string 0")
    assert found.rows[0].cells == {"string 2999": "string 2998", "string 0": "string 977"}


#: Every kind of value a cell holds, and a blank, for the generated workbooks.
def _value(rng: random.Random) -> object:
    kind = rng.randrange(12)
    if kind < 3:
        return None
    if kind == 3:
        return rng.choice(["", " ", "x", "Ada Lovelace", "ż", EMOJI, "a_x0000_b", "  pad  "])
    if kind == 4:
        return rng.randrange(-1000, 100000)
    if kind == 5:
        return rng.choice([0.5, 1.0, 1e20, -3.25, 1e-9, 12345.678])
    if kind == 6:
        return rng.choice([True, False])
    if kind == 7:
        return date(1990 + rng.randrange(40), 1 + rng.randrange(12), 1 + rng.randrange(28))
    if kind == 8:
        return datetime(2020, 5, 17, rng.randrange(24), rng.randrange(60), rng.randrange(60))
    if kind == 9:
        return time(rng.randrange(24), rng.randrange(60))
    if kind == 10:
        return timedelta(minutes=rng.randrange(5000))
    return f"shared {rng.randrange(6)}"


@pytest.mark.parametrize("seed", range(40))
def test_generated_workbooks_are_inspected_as_the_reader_read_them(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - a reproducible workbook, not a secret
    width = rng.randrange(1, 9)
    header = [rng.choice(["Name", "Email", "Qty", None, "Name", f"c{n}"]) for n in range(width)]
    header[0] = header[0] or "First"
    rows = [
        [_value(rng) for _ in range(rng.randrange(0, width + 3))]
        for _ in range(rng.randrange(0, 40))
    ]
    raw = one([header, *rows])
    agree(raw, Format.XLSX, shapes=[(200, 1000), (rng.randrange(6), rng.randrange(1, 12))])


@pytest.mark.parametrize("seed", range(40))
def test_generated_hand_written_sheets_are_inspected_as_the_reader_read_them(seed: int) -> None:
    rng = random.Random(1000 + seed)  # noqa: S311 - a reproducible workbook, not a secret
    table = [plain(rng.choice(["", "x", "Name", " ", "ż", "a" * 40])) for _ in range(12)]
    width = rng.randrange(1, 7)

    def cell() -> str:
        kind = rng.randrange(8)
        if kind < 2:
            return ""
        if kind < 5:
            return shared(rng.randrange(len(table)))
        if kind == 5:
            return inline(rng.choice(["", "in", " ", "Name"]))
        if kind == 6:
            return number(rng.choice(["1", "2.5", "45000", "0"]), style=rng.randrange(3))
        return rng.choice(['<c t="b"><v>1</v></c>', '<c t="str"><v>s</v></c>', "<c/>"])

    body = ""
    position = 0
    for _ in range(rng.randrange(1, 30)):
        position += rng.choice([1, 1, 1, 2, 5])
        cells = ""
        column = 0
        for _ in range(rng.randrange(0, width + 2)):
            column += rng.choice([1, 1, 2])
            made = cell()
            if made:
                cells += made.replace("<c", f'<c r="{letters(column)}{position}"', 1)
        body += row(cells, position)
    raw = book(
        worksheet(body), sst(table), stylesheet=styles({164: "yyyy-mm-dd"}, [0, 164, 14])
    )
    agree(raw, Format.XLSX, shapes=[(200, 1000), (rng.randrange(6), rng.randrange(1, 12))])


# ── bounded: the readers are not called ──────────────────────────────────────


@pytest.fixture
def no_readers(monkeypatch: pytest.MonkeyPatch) -> None:
    """From here on, reaching either whole-file read fails the test."""
    import openpyxl
    from koras_import import reading, reading_xlsx

    def workbook_reached(*_: object, **__: object) -> None:
        raise AssertionError("openpyxl.load_workbook was reached by the inspection")

    def decode_reached(*_: object, **__: object) -> None:
        raise AssertionError("the whole-file decode was reached by the inspection")

    monkeypatch.setattr(openpyxl, "load_workbook", workbook_reached)
    monkeypatch.setattr(reading_xlsx, "read_workbook", workbook_reached)
    monkeypatch.setattr(reading, "decode", decode_reached)


@pytest.mark.usefixtures("no_readers")
def test_the_inspection_reaches_neither_reader() -> None:
    workbook = inspect_source(WRITTEN["typed"], Format.XLSX, sample=200, ceiling=1000)
    assert len(workbook.rows) == 6
    text = inspect_source(CSV_FILES["quoted"], Format.CSV, sample=200, ceiling=1000)
    assert len(text.rows) == 2


def test_the_guard_above_does_fail_when_a_reader_is_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A guard that cannot fire proves nothing about the code behind it.
    import openpyxl

    def reached(*_: object, **__: object) -> None:
        raise AssertionError("reached")

    monkeypatch.setattr(openpyxl, "load_workbook", reached)
    with pytest.raises(ReadRefused) as caught:
        read_workbook(WRITTEN["typed"], limit=1, ceiling=1)
    assert isinstance(caught.value.__cause__, AssertionError)


# ── bounded: what is held ────────────────────────────────────────────────────


def peak_of(raw: bytes, fmt: Format, **options: Any) -> tuple[inspection.Inspection, int]:  # noqa: ANN401
    """The inspection's own allocations at their highest, safety pass excluded.

    The pass has its own measurement in `test_preflight.py`. Here it is run
    first and handed in, so the figure is what GR-352B added.
    """
    limits = options.pop("limits", WIDE_OPEN)
    checked = preflight(raw, fmt, limits)
    tracemalloc.start()
    try:
        if fmt is Format.XLSX:
            found = inspection._inspect_xlsx(raw, checked, limits, **options)
        else:
            found = inspection._inspect_csv(raw, checked, **options)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return found, peak


def heavy_table(count: int) -> bytes:
    """`count` shared strings of 8 KiB and an emoji; rows naming them backwards."""
    table = sst([plain(f"{'a' * 8_000}{EMOJI}{n}") for n in range(count)])
    rows = [[shared(count - 1 - n)] for n in range(count)]
    return book(worksheet(grid(rows)), table)


def test_a_workbook_s_string_table_is_never_held() -> None:
    # A thousand strings that decode to about 32 MiB, the way the reader
    # decodes them. The header is the last of them and the sample is the three
    # before it, so the table is read to its end -- and three strings of it
    # are kept.
    raw = heavy_table(1000)
    found, peak = peak_of(raw, Format.XLSX, sample=3, ceiling=5000, budget=MAX_SAMPLE_CHARACTERS)
    assert found.header.columns[0].endswith(f"{EMOJI}999")
    assert [next(iter(row.cells.values()))[-3:] for row in found.rows] == ["998", "997", "996"]
    assert found.rows_seen == 999
    assert found.preflight.decoded_string_bytes > 30 * 1024 * 1024
    assert peak < 2 * 1024 * 1024, peak


def test_what_is_held_does_not_grow_with_what_is_not_sampled() -> None:
    # Four times the text, the same sample: the same peak, give or take the
    # four bytes a string the lengths cost.
    _, small = peak_of(
        heavy_table(250), Format.XLSX, sample=3, ceiling=5000, budget=MAX_SAMPLE_CHARACTERS
    )
    _, large = peak_of(
        heavy_table(1000), Format.XLSX, sample=3, ceiling=5000, budget=MAX_SAMPLE_CHARACTERS
    )
    assert large < small + 256 * 1024, (small, large)


def test_a_csv_is_never_held_as_text() -> None:
    # Four megabytes of ASCII and one emoji on the second line: sixteen once
    # decoded whole. The sample is the first two hundred rows and the walk
    # goes to the end, because the file is under its ceiling.
    raw = b"Name,Note\n" + EMOJI.encode() + b",x\n" + b"Ada Lovelace,a note about her\n" * 140_000
    assert len(raw) > 4 * 1024 * 1024
    found, peak = peak_of(
        raw, Format.CSV, sample=200, ceiling=1_000_000, budget=MAX_SAMPLE_CHARACTERS
    )
    assert found.rows_seen == 140_001 and len(found.rows) == 200
    # A few chunk-sized pieces, and the chunk holding the emoji is four bytes
    # a character: the chunk, the chunk joined to what was carried, its lines.
    assert peak < 4 * 1024 * 1024, peak


# ── bounded: it stops ────────────────────────────────────────────────────────


def test_a_csv_over_its_ceiling_is_not_decoded_to_the_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"Name,Note\n" + b"Ada Lovelace,a note about her\n" * 140_000
    decoded: list[int] = []
    pieces = inspection._pieces

    def counted(*arguments: Any) -> Any:  # noqa: ANN401
        for piece in pieces(*arguments):
            decoded.append(len(piece))
            yield piece

    monkeypatch.setattr(inspection, "_pieces", counted)
    found = inspect_source(raw, Format.CSV, sample=200, ceiling=500)
    assert found.rows_seen == 501 and found.over_ceiling
    assert len(found.rows) == 200
    # One chunk of a file that is sixteen of them.
    assert len(decoded) == 1 and len(raw) > 15 * decoded[0]


def test_a_worksheet_over_its_ceiling_is_not_walked_to_the_end() -> None:
    # The row after the ceiling's is a file in a cell. The reader breaks
    # before it and so must this; reaching it is a refusal.
    rows = [[inline("Name")], *[[inline(f"r{n}")] for n in range(6)]]
    tail = row(inline("x" * (MAX_CELL + 1), "A9"), 9)
    raw = book(worksheet(grid(rows) + tail))
    found = inspect_source(raw, Format.XLSX, sample=200, ceiling=5)
    assert found.rows_seen == 6 and found.over_ceiling
    assert len(found.rows) == 5
    with pytest.raises(ReadRefused, match="file in a cell"):
        inspect_source(raw, Format.XLSX, sample=200, ceiling=10)


def test_a_file_over_the_ceiling_and_outside_the_envelope_is_outside_the_envelope() -> None:
    # The safety pass reads the whole file whatever the ceiling, on purpose:
    # the refusal a person is given must not depend on which limit the walk
    # happened to meet first.
    raw = b"Name\n" + b"Ada\n" * 50
    tight = replace(PROVISIONAL_LIMITS, max_cells=20)
    with pytest.raises(PreflightRefused) as caught:
        inspect_source(raw, Format.CSV, tight, sample=5, ceiling=3)
    assert caught.value.code is RefusalCode.TOO_MANY_CELLS


# ── bounded: the sample ──────────────────────────────────────────────────────


def test_an_ordinary_file_s_sample_is_untouched_by_the_budget() -> None:
    raw = one([["Name", "Email", "Note"], *[[f"n{n}", f"{n}@x.io", "x" * 200] for n in range(400)]])
    found = inspect_source(raw, Format.XLSX, sample=200, ceiling=1000)
    assert len(found.rows) == 200 and found.sample_cut is False
    assert found.rows_seen == 400


def test_one_string_named_by_every_cell_does_not_become_a_page_of_it() -> None:
    # 30,000 characters in the file once; 200 rows of 60 cells naming it would
    # be 360 million in the answer. The sample stops when the next row would
    # pass its budget, and the count carries on.
    big = "wide " * 6000
    table = sst([plain("H"), plain(big)])
    header = [inline(f"c{n}") for n in range(60)]
    rows = [header, *[[shared(1)] * 60 for _ in range(300)]]
    raw = book(worksheet(grid(rows)), table)
    found, peak = peak_of(
        raw,
        Format.XLSX,
        limits=PROVISIONAL_LIMITS,
        sample=200,
        ceiling=1000,
        budget=MAX_SAMPLE_CHARACTERS,
    )
    assert found.sample_cut is True
    assert 0 < len(found.rows) < 200
    held = sum(len(value) for cells in found.rows for value in cells.cells.values())
    assert held <= MAX_SAMPLE_CHARACTERS
    assert found.rows_seen == 300
    # Every row after the first is the first row again, less its trailing
    # space: one stripped copy shared would be ideal and this is not that, but
    # it is the budget and not the file that bounds it.
    assert peak < 4 * MAX_SAMPLE_CHARACTERS, peak


def test_a_csv_sample_stops_at_its_budget_too() -> None:
    line = ",".join(["y" * 3000] * 10)
    raw = ("a,b,c,d,e,f,g,h,i,j\n" + (line + "\n") * 300).encode()
    found = inspect_source(raw, Format.CSV, sample=200, ceiling=1000, sample_budget=100_000)
    assert found.sample_cut is True
    assert len(found.rows) == 3
    assert found.rows_seen == 300


def test_no_sample_at_all_is_the_header_and_the_count() -> None:
    for raw, fmt in ((WRITTEN["many-rows"], Format.XLSX), (CSV_FILES["many-rows"], Format.CSV)):
        found = inspect_source(raw, fmt, sample=0, ceiling=1000)
        assert found.rows == () and found.sample_cut is False
        assert found.rows_seen == 1001 and found.over_ceiling
        assert found.header.columns[0] == "N"


# ── the safety pass is still first ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "fmt"),
    [
        (("Name\n" + "Ada Lovelace\n" * 2000 + EMOJI + "\n").encode(), Format.CSV),
        (one([["Name"], ["a" * 20_000 + EMOJI]]), Format.XLSX),
    ],
    ids=["csv", "xlsx"],
)
def test_an_unsafe_source_is_refused_before_any_of_it_is_inspected(
    monkeypatch: pytest.MonkeyPatch, raw: bytes, fmt: Format
) -> None:
    def reached(*_: object, **__: object) -> None:
        raise AssertionError("the inspection ran on a source the safety pass refuses")

    monkeypatch.setattr(inspection, "_inspect_csv", reached)
    monkeypatch.setattr(inspection, "_inspect_xlsx", reached)
    monkeypatch.setattr(inspection, "_stream", reached)
    tight = SafetyLimits(max_decoded_string_bytes=50_000)
    with pytest.raises(PreflightRefused) as caught:
        inspect_source(raw, fmt, tight, sample=200, ceiling=1000)
    assert caught.value.code is RefusalCode.DECODED_TOO_LARGE
    # And the same replacement is reached by a source that passes.
    safe = b"Name\nAda\n" if fmt is Format.CSV else one([["Name"], ["Ada"]])
    with pytest.raises(AssertionError, match="the inspection ran"):
        inspect_source(safe, fmt, tight, sample=200, ceiling=1000)


def test_the_inspection_carries_what_the_safety_pass_counted() -> None:
    found = inspect_source(CSV_FILES["many-rows"], Format.CSV, sample=1, ceiling=10)
    # The pass counted every row; the inspection stopped at the eleventh.
    assert found.preflight.rows == 1500 and found.rows_seen == 11
    assert found.preflight.safe


def test_a_format_nobody_reads_is_refused_by_name() -> None:
    with pytest.raises(ReadRefused, match="json files are not read"):
        inspect_source(b"[]", Format.JSON, sample=1, ceiling=1)


# ── where this is deliberately not the reader ────────────────────────────────


def test_a_number_that_is_not_one_is_a_refusal_in_the_sample_and_unseen_past_it() -> None:
    raw = book(worksheet(grid([[inline("N")], [number("1")], [number("not a number")]])))
    with pytest.raises(ReadRefused, match="could not be read as a workbook"):
        inspect_source(raw, Format.XLSX, sample=5, ceiling=5)
    # Past the sample a cell is asked only whether it is empty. The dry run
    # reads every row through the canonical reader, which refuses it there.
    found = inspect_source(raw, Format.XLSX, sample=1, ceiling=5)
    assert found.rows_seen == 2 and len(found.rows) == 1
    with pytest.raises(ReadRefused, match="could not be read as a workbook"):
        read_workbook(raw, limit=1, ceiling=5)


def test_a_stylesheet_that_is_not_one_is_refused_rather_than_walked() -> None:
    crowded = styles({}, [0] * (inspection.MAX_STYLES + 1))
    raw = book(worksheet(grid([[inline("N")], [number("1")]])), stylesheet=crowded)
    with pytest.raises(ReadRefused, match="could not be read as a workbook"):
        inspect_source(raw, Format.XLSX, WIDE_OPEN, sample=5, ceiling=5)


def test_a_part_the_mapping_page_never_needs_is_not_opened() -> None:
    # A theme that is not XML. `openpyxl` keeps it as bytes; a broken core
    # properties part it parses, and refuses the workbook for. The inspection
    # opens neither, and the dry run -- the canonical reader -- still refuses.
    raw = book(
        worksheet(grid([[inline("Name")], [inline("Ada")]])),
        extra={"docProps/core.xml": "<not closed"},
    )
    with pytest.raises(ReadRefused, match="could not be read as a workbook"):
        read_workbook(raw, limit=5, ceiling=5)
    found = inspect_source(raw, Format.XLSX, sample=5, ceiling=5)
    assert found.header.columns == ("Name",) and found.rows_seen == 1


@pytest.mark.parametrize(
    "name", ["a-string-table-with-another-root", "a-worksheet-with-another-root"]
)
def test_a_part_with_another_root_is_scanned_before_it_is_inspected(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # IMPORT-DEF-017, from this side. The pass used to cost nothing of these
    # parts, and the inspection refused them rather than read what nothing
    # had counted. The pass scans them now -- so the same package, under an
    # envelope its text does not fit, is refused by the pass, and neither the
    # inspection nor `openpyxl` is reached.
    import openpyxl

    def reached(*_: object, **__: object) -> None:
        raise AssertionError("reached with a workbook the safety pass must refuse")

    monkeypatch.setattr(openpyxl, "load_workbook", reached)
    monkeypatch.setattr(inspection, "_inspect_xlsx", reached)
    tight = SafetyLimits(max_decoded_string_bytes=64)
    for read in (
        lambda: inspect_source(HAND[name], Format.XLSX, tight, sample=5, ceiling=1000),
        lambda: read_workbook(HAND[name], limit=5, ceiling=1000, limits=tight),
    ):
        with pytest.raises(PreflightRefused) as caught:
            read()
        assert caught.value.code is RefusalCode.DECODED_TOO_LARGE
