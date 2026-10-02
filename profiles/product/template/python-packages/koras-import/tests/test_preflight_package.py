"""The safety pass scans the parts the reader reads. IMPORT-DEF-017.

GR-352A promised that nothing reaches `openpyxl` unscanned, and for a day it
was not true. The pass found a workbook's parts by its own rules -- a string
table is a part whose root is `sst`, the sheets are listed in `xl/workbook.xml`,
a cell is an element called `c` -- and `openpyxl` finds them by different ones.
Wherever the two disagreed, the pass scanned one part and the reader read
another: a workbook was called safe with none of its text and none of its cells
counted, and then loaded in full.

Every case here is one such disagreement, as the smallest package that shows
it, and each is asked three things.

**The pass refuses it**, under an envelope the same content in an ordinary
package breaks.

**The reader is never reached.** `openpyxl.load_workbook` is replaced with
something that fails the test, and `read_workbook` is called. A refusal that
arrived after the workbook was loaded would have the right code and would
have cost what it refuses -- so this, and not the code, is the assertion.

**The pass names the parts `openpyxl` goes on to use.** For the same package
made small enough to pass, `openpyxl` is allowed to load it, and the sheet it
chose and the part it read its strings from are compared with the two the pass
reported. That is the property the fix exists for, asked of the library itself
rather than of this file's idea of it.

Then the other direction: a package whose index is broken is a refusal, a
sentence, and never whatever `openpyxl` happened to raise.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence
from typing import Any
from xml.sax.saxutils import escape

import pytest
from koras_import import (
    Format,
    PreflightRefused,
    ReadRefused,
    RefusalCode,
    SafetyLimits,
    preflight,
    read_workbook,
    safety,
)

pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships"
TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
WORKBOOK = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
WORKSHEET = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
STRINGS = "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"

#: The envelope every unsafe package below breaks, and every safe one fits.
TIGHT = SafetyLimits(max_decoded_string_bytes=20_000, max_cells=60, max_columns=8)


# ── building packages, part by part ──────────────────────────────────────────


def package(parts: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name, body in parts.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def types(*overrides: tuple[str, str]) -> str:
    declared = "".join(
        f'<Override PartName="{name}" ContentType="{kind}"/>' for name, kind in overrides
    )
    return (
        f'<Types xmlns="{TYPES}"><Default Extension="rels" ContentType="application/vnd.'
        'openxmlformats-package.relationships+xml"/><Default Extension="xml" '
        f'ContentType="application/xml"/>{declared}</Types>'
    )


def workbook(sheets: str) -> str:
    return f'<workbook xmlns="{MAIN}" xmlns:r="{RELS}">{sheets}</workbook>'


def sheet(name: str, link: str, position: int = 1) -> str:
    return f'<sheet name="{name}" sheetId="{position}" r:id="{link}"/>'


def relationships(*entries: str) -> str:
    return f'<Relationships xmlns="{PACKAGE}">{"".join(entries)}</Relationships>'


def relation(link: str, target: str, kind: str = "worksheet", more: str = "") -> str:
    return f'<Relationship Id="{link}" Type="{RELS}/{kind}" Target="{target}"{more}/>'


def inline(text: str) -> str:
    return f'<c t="inlineStr"><is><t>{escape(text)}</t></is></c>'


def rows(cells: Sequence[Sequence[str]]) -> str:
    return "".join(f'<row r="{n}">{"".join(row)}</row>' for n, row in enumerate(cells, start=1))


def worksheet(body: str, root: str = "worksheet") -> str:
    return f'<{root} xmlns="{MAIN}"><sheetData>{body}</sheetData></{root}>'


def table(strings: Sequence[str], root: str = "sst") -> str:
    items = "".join(f"<si><t>{escape(text)}</t></si>" for text in strings)
    return f'<{root} xmlns="{MAIN}">{items}</{root}>'


def content(long: str) -> str:
    """A sheet of a header and two rows, each holding `long`."""
    return worksheet(rows([[inline("Name")], [inline(long)], [inline(long)]]))


LIGHT = worksheet(rows([[inline("Name")], [inline("x")]]))

#: What is the same in every package: where the workbook is, and a decoy sheet
#: that is small and safe. A case adds or replaces parts.
BASE = {
    "[Content_Types].xml": types(("/xl/workbook.xml", WORKBOOK)),
    "_rels/.rels": relationships(
        f'<Relationship Id="rId1" Type="{RELS}/officeDocument" Target="xl/workbook.xml"/>'
    ),
    "xl/workbook.xml": workbook(f"<sheets>{sheet('Light', 'rId1')}</sheets>"),
    "xl/_rels/workbook.xml.rels": relationships(relation("rId1", "worksheets/sheet1.xml")),
    "xl/worksheets/sheet1.xml": LIGHT,
}


def shaped(long: str) -> dict[str, dict[str, str]]:
    """Every package shape, holding `long` in the part the reader will read.

    The value is the parts that differ from `BASE`. Called with a long string
    for the unsafe file and a short one for the safe file of the same shape.
    """
    heavy = content(long)
    cells = worksheet(
        rows(
            [[inline("Name")]]
            + [[f"<x><v>{column}</v></x>" for column in range(20)] for _ in range(5)]
        )
    )
    return {
        "ordinary": {"xl/worksheets/sheet1.xml": heavy},
        # ── the string table ────────────────────────────────────────────────
        "strings: the root is not sst": {
            "[Content_Types].xml": types(
                ("/xl/workbook.xml", WORKBOOK), ("/xl/sharedStrings.xml", STRINGS)
            ),
            "xl/sharedStrings.xml": table(["Name", long], root="strings"),
            "xl/worksheets/sheet1.xml": worksheet(
                rows([['<c t="s"><v>0</v></c>'], ['<c t="s"><v>1</v></c>']])
            ),
        },
        "strings: an unusual name and place, and no relationship": {
            "[Content_Types].xml": types(("/xl/workbook.xml", WORKBOOK), ("/data/p7.bin", STRINGS)),
            "data/p7.bin": table(["Name", long], root="t"),
            "xl/worksheets/sheet1.xml": worksheet(
                rows([['<c t="s"><v>0</v></c>'], ['<c t="s"><v>1</v></c>']])
            ),
        },
        # ── the worksheet ───────────────────────────────────────────────────
        "sheet: the root is not worksheet": {
            "xl/worksheets/sheet1.xml": worksheet(
                rows([[inline("Name")], [inline(long)], [inline(long)]]), root="sheet"
            ),
        },
        "sheet: an unusual name and place": {
            "xl/_rels/workbook.xml.rels": relationships(relation("rId1", "../data/q.bin")),
            "data/q.bin": heavy,
        },
        "sheet: a relative target that climbs and returns": {
            "xl/_rels/workbook.xml.rels": relationships(
                relation("rId1", "./worksheets/../worksheets/./sheet9.xml")
            ),
            "xl/worksheets/sheet9.xml": heavy,
        },
        "sheet: an absolute target": {
            "xl/_rels/workbook.xml.rels": relationships(relation("rId1", "/other/sheet.xml")),
            "other/sheet.xml": heavy,
        },
        "sheet: a relationship that is not a worksheet's": {
            "xl/workbook.xml": workbook(
                f"<sheets>{sheet('Heavy', 'rId2')}{sheet('Light', 'rId1', 2)}</sheets>"
            ),
            "xl/_rels/workbook.xml.rels": relationships(
                relation("rId2", "worksheets/sheet2.xml", kind="dialogsheet"),
                relation("rId1", "worksheets/sheet1.xml"),
            ),
            "xl/worksheets/sheet2.xml": heavy,
        },
        "sheet: a second workbook part, named by the content types": {
            "[Content_Types].xml": types(("/xl/real.xml", WORKBOOK)),
            "xl/real.xml": workbook(f"<sheets>{sheet('Heavy', 'rId2')}</sheets>"),
            "xl/_rels/real.xml.rels": relationships(relation("rId2", "worksheets/sheet2.xml")),
            "xl/worksheets/sheet2.xml": heavy,
        },
        "sheet: two sheets elements, and the reader takes the last": {
            "xl/workbook.xml": workbook(
                f"<sheets>{sheet('Light', 'rId1')}</sheets>"
                f"<sheets>{sheet('Heavy', 'rId2', 2)}</sheets>"
            ),
            "xl/_rels/workbook.xml.rels": relationships(
                relation("rId1", "worksheets/sheet1.xml"),
                relation("rId2", "worksheets/sheet2.xml"),
            ),
            "xl/worksheets/sheet2.xml": heavy,
        },
        "sheet: a plain id beside the namespaced one": {
            "xl/workbook.xml": workbook(
                '<sheets><sheet name="S" sheetId="1" r:id="rId2" id="rId1"/></sheets>'
            ),
            "xl/_rels/workbook.xml.rels": relationships(
                relation("rId1", "worksheets/sheet1.xml"),
                relation("rId2", "worksheets/sheet2.xml"),
            ),
            "xl/worksheets/sheet2.xml": heavy,
        },
        "sheet: the id's prefix is bound to another namespace": {
            "xl/workbook.xml": (
                f'<workbook xmlns="{MAIN}" xmlns:r="urn:not-relationships" xmlns:q="{RELS}">'
                '<sheets><sheet name="S" sheetId="1" r:id="rId1" q:id="rId2"/></sheets></workbook>'
            ),
            "xl/_rels/workbook.xml.rels": relationships(
                relation("rId1", "worksheets/sheet1.xml"),
                relation("rId2", "worksheets/sheet2.xml"),
            ),
            "xl/worksheets/sheet2.xml": heavy,
        },
        "sheet: an entry that is not called sheet": {
            "xl/workbook.xml": workbook(
                '<sheets><entry name="Heavy" sheetId="2" r:id="rId2"/>'
                f"{sheet('Light', 'rId1')}</sheets>"
            ),
            "xl/_rels/workbook.xml.rels": relationships(
                relation("rId1", "worksheets/sheet1.xml"),
                relation("rId2", "worksheets/sheet2.xml"),
            ),
            "xl/worksheets/sheet2.xml": heavy,
        },
        "sheet: a relationship id used twice, and the later one wins": {
            "xl/_rels/workbook.xml.rels": relationships(
                relation("rId1", "worksheets/sheet1.xml"),
                relation("rId1", "worksheets/sheet2.xml"),
            ),
            "xl/worksheets/sheet2.xml": heavy,
        },
        "sheet: two slashes, so the first sheet is not a part": {
            "xl/workbook.xml": workbook(
                f"<sheets>{sheet('Light', 'rId1')}{sheet('Heavy', 'rId2', 2)}</sheets>"
            ),
            "xl/_rels/workbook.xml.rels": relationships(
                relation("rId1", "//xl/worksheets/sheet1.xml"),
                relation("rId2", "worksheets/sheet2.xml"),
            ),
            "xl/worksheets/sheet2.xml": heavy,
        },
        "sheet: an external target that is a part's name": {
            "xl/workbook.xml": workbook(
                f"<sheets>{sheet('Gone', 'rId1')}{sheet('Heavy', 'rId2', 2)}</sheets>"
            ),
            "xl/_rels/workbook.xml.rels": relationships(
                relation("rId1", "worksheets/missing.xml"),
                relation("rId2", "xl/worksheets/sheet2.xml", more=' TargetMode="External"'),
            ),
            "xl/worksheets/sheet2.xml": heavy,
        },
        "sheet: Data is preferred, wherever it is listed": {
            "xl/workbook.xml": workbook(
                f"<sheets>{sheet('Light', 'rId1')}{sheet('Data', 'rId2', 2)}</sheets>"
            ),
            "xl/_rels/workbook.xml.rels": relationships(
                relation("rId1", "worksheets/sheet1.xml"),
                relation("rId2", "worksheets/sheet2.xml"),
            ),
            "xl/worksheets/sheet2.xml": heavy,
        },
        "sheet: a chart sheet first, then the worksheet": {
            "xl/workbook.xml": workbook(
                f"<sheets>{sheet('Chart', 'rId1')}{sheet('Heavy', 'rId2', 2)}</sheets>"
            ),
            "xl/_rels/workbook.xml.rels": relationships(
                relation("rId1", "worksheets/missing.xml", kind="chartsheet"),
                relation("rId2", "worksheets/sheet2.xml"),
            ),
            "xl/worksheets/sheet2.xml": heavy,
        },
        # ── inside the sheet ────────────────────────────────────────────────
        "cells: the children of a row are not called c": {
            "xl/worksheets/sheet1.xml": cells if len(long) > 100 else LIGHT,
        },
    }


def built(shape: str, long: str) -> bytes:
    return package({**BASE, **shaped(long)[shape]})


SHAPES = sorted(shaped("x"))
UNSAFE = "a" * 30_000
SAFE = "short"


# ── the reader, replaced or watched ──────────────────────────────────────────


@pytest.fixture
def no_reader(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """From here on, reaching `openpyxl.load_workbook` fails the test."""
    import openpyxl

    reached: list[int] = []

    def load(*_: object, **__: object) -> None:
        reached.append(1)
        raise AssertionError("openpyxl was reached with a workbook the safety pass must refuse")

    monkeypatch.setattr(openpyxl, "load_workbook", load)
    return reached


def consumed(raw: bytes, monkeypatch: pytest.MonkeyPatch) -> tuple[str | None, str | None]:
    """The sheet part `openpyxl` chooses and the part it reads strings from.

    Asked of `openpyxl` itself: the workbook is loaded as `read_workbook`
    loads it, the string reader is watched for the part it is handed, and the
    sheet is chosen by `read_workbook`'s own rule.
    """
    import openpyxl
    from openpyxl.reader import excel

    read: list[str] = []
    original = excel.read_string_table  # type: ignore[attr-defined]

    def watched(source: Any) -> Any:  # noqa: ANN401 - a file inside the archive
        read.append(source.name)
        return original(source)

    monkeypatch.setattr(excel, "read_string_table", watched)
    book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        worksheets = book.worksheets
        chosen = next(
            (found for found in worksheets if found.title == "Data"),
            worksheets[0] if worksheets else None,
        )
        path = getattr(chosen, "_worksheet_path", None)
    finally:
        book.close()
    return path, (read[0] if read else None)


# ── the three questions ──────────────────────────────────────────────────────


@pytest.mark.parametrize("shape", SHAPES)
def test_the_pass_refuses_what_the_reader_would_have_read(shape: str) -> None:
    with pytest.raises(PreflightRefused) as caught:
        preflight(built(shape, UNSAFE), Format.XLSX, TIGHT)
    expected = (
        {RefusalCode.TOO_MANY_CELLS, RefusalCode.TOO_MANY_COLUMNS}
        if shape.startswith("cells")
        else {RefusalCode.DECODED_TOO_LARGE}
    )
    assert caught.value.code in expected


@pytest.mark.parametrize("shape", SHAPES)
def test_the_reader_is_never_reached(shape: str, no_reader: list[int]) -> None:
    # The primary assertion. Not the code: that the refusal came first.
    with pytest.raises(PreflightRefused):
        read_workbook(built(shape, UNSAFE), limit=200, ceiling=1000, limits=TIGHT)
    assert no_reader == []


def test_the_guard_above_does_fail_when_the_reader_is_reached(no_reader: list[int]) -> None:
    # A guard that cannot fire proves nothing. A safe file reaches the reader,
    # and `read_workbook` turns what the replacement raised into its refusal.
    with pytest.raises(ReadRefused) as caught:
        read_workbook(built("ordinary", SAFE), limit=200, ceiling=1000, limits=TIGHT)
    assert no_reader == [1]
    assert isinstance(caught.value.__cause__, AssertionError)


@pytest.mark.parametrize("shape", SHAPES)
def test_the_pass_names_the_parts_openpyxl_goes_on_to_use(
    shape: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = built(shape, SAFE)
    counted = preflight(raw, Format.XLSX, TIGHT)
    sheet_part, strings_part = consumed(raw, monkeypatch)
    assert sheet_part is not None
    assert counted.sheet_part == sheet_part
    assert counted.strings_part == strings_part
    # And the canonical reader reads it, from that part, without complaint.
    read = read_workbook(raw, limit=200, ceiling=1000, limits=TIGHT)
    assert read.sheet == counted.sheet_title
    assert read.rows_seen >= 1


def test_the_workbook_types_are_openpyxl_s_own_in_its_own_order() -> None:
    from openpyxl.reader import excel
    from openpyxl.xml.constants import SHARED_STRINGS, XLSM, XLSX, XLTM, XLTX

    assert safety._WORKBOOK_TYPES == (XLTM, XLTX, XLSM, XLSX)
    assert safety._STRINGS_TYPE == SHARED_STRINGS
    # The order is the one `_find_workbook_part` walks, read from its source
    # so that a release which reorders it is noticed here.
    import inspect

    assert "workbook_types = [XLTM, XLTX, XLSM, XLSX]" in inspect.getsource(
        excel._find_workbook_part  # type: ignore[attr-defined]
    )


# ── every child of a row is a cell ───────────────────────────────────────────


def test_a_cell_is_counted_by_where_it_is_and_not_by_what_it_is_called() -> None:
    # Not `row`: a row inside a row is a row to `openpyxl` as well as a cell,
    # and its own children are cells in turn. The pass counts all of them,
    # which is more than the reader lays out and never fewer.
    names = ["c", "x", "rPh", "t", "v", "is", "si"]
    body = rows([[f"<{name}><v>1</v></{name}>" for name in names]])
    raw = package({**BASE, "xl/worksheets/sheet1.xml": worksheet(body)})
    counted = preflight(raw, Format.XLSX)
    assert counted.cells == len(names) and counted.columns == len(names)
    # `openpyxl` agrees about how wide that row is.
    read = read_workbook(raw, limit=5, ceiling=5)
    assert len(read.header.columns) == len(names)


def test_a_part_nested_deeper_than_a_workbook_nests_is_refused() -> None:
    deep = "<a>" * 400 + "</a>" * 400
    raw = package({**BASE, "xl/worksheets/sheet1.xml": worksheet(deep)})
    with pytest.raises(PreflightRefused) as caught:
        preflight(raw, Format.XLSX)
    assert caught.value.code is RefusalCode.MALFORMED


def test_an_index_longer_than_a_spreadsheet_s_is_refused_rather_than_cut_short() -> None:
    # Resolving from the first few thousand entries would be resolving a
    # different package than the reader, which reads them all and takes the
    # last word on several questions.
    many = "".join(sheet(f"S{n}", "rId1", n) for n in range(1, 40))
    raw = package({**BASE, "xl/workbook.xml": workbook(f"<sheets>{many}</sheets>")})
    with pytest.raises(PreflightRefused) as caught:
        preflight(raw, Format.XLSX, SafetyLimits(max_archive_entries=20))
    assert caught.value.code is RefusalCode.MALFORMED


# ── a package whose index is broken ──────────────────────────────────────────

BROKEN: dict[str, dict[str, str]] = {
    "the sheet's target is not in the archive": {
        "xl/_rels/workbook.xml.rels": relationships(relation("rId1", "worksheets/gone.xml")),
    },
    "the sheet names a relationship nobody declared": {
        "xl/workbook.xml": workbook(f"<sheets>{sheet('S', 'rId9')}</sheets>"),
    },
    "the sheet names no relationship at all": {
        "xl/workbook.xml": workbook('<sheets><sheet name="S" sheetId="1"/></sheets>'),
    },
    "there is no relationships part": {"xl/_rels/workbook.xml.rels": ""},
    "the relationships part is not XML": {"xl/_rels/workbook.xml.rels": "<Relationships"},
    "a relationship has no target": {
        "xl/_rels/workbook.xml.rels": relationships(
            f'<Relationship Id="rId1" Type="{RELS}/worksheet"/>'
        ),
    },
    "there are no sheets": {"xl/workbook.xml": workbook("<sheets/>")},
    "the workbook part is not XML": {"xl/workbook.xml": "<workbook"},
    "the only sheet is a chart sheet": {
        "xl/_rels/workbook.xml.rels": relationships(
            relation("rId1", "worksheets/sheet1.xml", kind="chartsheet")
        ),
    },
    "the content types are not XML": {"[Content_Types].xml": "<Types"},
    "the content types name a workbook part that is not there": {
        "[Content_Types].xml": types(("/xl/absent.xml", WORKBOOK)),
    },
    "the content types name a string table that is not there": {
        "[Content_Types].xml": types(("/xl/workbook.xml", WORKBOOK), ("/xl/absent.xml", STRINGS)),
    },
    "a cell names a string the table does not have": {
        "[Content_Types].xml": types(
            ("/xl/workbook.xml", WORKBOOK), ("/xl/sharedStrings.xml", STRINGS)
        ),
        "xl/sharedStrings.xml": table(["Name"]),
        "xl/worksheets/sheet1.xml": worksheet(
            rows([['<c t="s"><v>0</v></c>'], ['<c t="s"><v>7</v></c>']])
        ),
    },
    "a number is not a number": {
        "xl/worksheets/sheet1.xml": worksheet(rows([[inline("N")], ["<c><v>seven</v></c>"]])),
    },
    "a cell reference is not a reference": {
        "xl/worksheets/sheet1.xml": worksheet(
            '<row r="1"><c r="1A" t="inlineStr"><is><t>N</t></is></c></row>'
        ),
    },
}


@pytest.mark.parametrize("fault", sorted(BROKEN))
def test_a_broken_package_is_a_refusal_and_a_sentence(fault: str) -> None:
    parts = {**BASE, **BROKEN[fault]}
    raw = package({name: body for name, body in parts.items() if body})
    # Not `KeyError`, not `IndexError`, not a parser's own error and not
    # whatever `openpyxl` raised: a refusal a route answers and a job records.
    with pytest.raises(ReadRefused) as caught:
        read_workbook(raw, limit=200, ceiling=1000)
    sentence = str(caught.value).lower()
    for internal in ("openpyxl", "expat", "zipfile", "keyerror", "traceback", "xml"):
        assert internal not in sentence, sentence
    assert 0 < len(sentence) <= 400


# ── the reader's own half of the guarantee ───────────────────────────────────


def test_the_reader_refuses_a_sheet_the_pass_did_not_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The pass is made to resolve the wrong sheet -- the mistake the fix
    # removed, put back. `openpyxl` still chooses the right one, and the
    # reader notices that the two differ and reads neither.
    raw = package(
        {
            **BASE,
            "xl/workbook.xml": workbook(
                f"<sheets>{sheet('First', 'rId1')}{sheet('Second', 'rId2', 2)}</sheets>"
            ),
            "xl/_rels/workbook.xml.rels": relationships(
                relation("rId1", "worksheets/sheet1.xml"),
                relation("rId2", "worksheets/sheet2.xml"),
            ),
            "xl/worksheets/sheet2.xml": LIGHT,
        }
    )
    assert read_workbook(raw, limit=5, ceiling=5).sheet == "First"

    resolve = safety._package

    def mistaken(*arguments: Any) -> Any:  # noqa: ANN401
        found = resolve(*arguments)
        return safety._Package(
            workbook=found.workbook,
            sheet="xl/worksheets/sheet2.xml",
            title="Second",
            strings=found.strings,
        )

    monkeypatch.setattr(safety, "_package", mistaken)
    with pytest.raises(ReadRefused, match="could not be read as a workbook"):
        read_workbook(raw, limit=5, ceiling=5)


# ── an ordinary workbook is still an ordinary workbook ───────────────────────


def test_a_workbook_openpyxl_wrote_resolves_to_its_usual_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openpyxl import Workbook

    made = Workbook()
    first = made.active
    assert first is not None
    first.title = "Lookup"
    first.append(["code"])
    data = made.create_sheet("Data")
    data.append(["Name", "Email"])
    data.append(["Ada", "ada@example.com"])
    buffer = io.BytesIO()
    made.save(buffer)
    raw = buffer.getvalue()

    counted = preflight(raw, Format.XLSX)
    assert counted.safe
    assert counted.workbook_part == "xl/workbook.xml"
    assert counted.sheet_part == "xl/worksheets/sheet2.xml"
    assert counted.sheet_title == "Data"
    # The string table too, where there is one: `openpyxl` writes strings
    # inline in this shape of workbook and reads no table back.
    assert (counted.sheet_part, counted.strings_part) == consumed(raw, monkeypatch)
    # Only the sheet that is read is counted: four cells, not five.
    assert counted.cells == 4 and counted.rows == 1
    read = read_workbook(raw, limit=5, ceiling=5)
    assert read.sheet == "Data" and read.header.columns == ("Name", "Email")


def test_a_csv_has_no_parts_to_name() -> None:
    counted = preflight(b"Name\nAda\n", Format.CSV)
    assert counted.sheet_part is None and counted.strings_part is None
    assert counted.workbook_part is None
