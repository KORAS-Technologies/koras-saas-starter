"""What a dry run and a commit cost a worker, measured as the kernel measures it.

GR-352C. `test_streaming.py` in the engine proves the worker's reader reads
what the old readers read and holds less, with `tracemalloc`.
`test_import_worker_envelope.py` beside this file proves one import runs at a
time. Neither is the figure an out-of-memory kill is decided on. This file
asks the kernel: each case runs `core/imports.examine` or `core/imports.prepare`
-- the two functions the worker's jobs reach, not the reader under them -- in a
process of its own, on a generated file, and reports how far that process's
peak resident set (`VmHWM`) rose over the file it had already been handed.

**Linux only, and skipped elsewhere rather than approximated**, for the reason
`test_preflight_memory.py` gives. Generator Integration runs this file by name
and fails if it skips.

**Each case is one of the ways a file inside the safety envelope used to cost
far more than the envelope counts**, small enough to run on every push:

- one long string named by every cell, and needing a strip -- IMPORT-DEF-016
  in the reader, a copy a cell;
- one long string in a two-part match key -- IMPORT-DEF-016 in the duplicate
  index, a copy a row;
- merged ranges, hyperlinks and data validations -- IMPORT-GAP-020, built into
  objects by the old reader and counted by nothing;
- other worksheets, a stylesheet and defined names -- IMPORT-GAP-015 in the
  worker, parsed whole by the old reader on load;
- a CSV that is ASCII but for one character, and one where every field is
  wide -- four copies of the file, at four bytes a character;
- many cells and many columns, where what was held was every row.

**Three things are asserted of them.**

*Each stays under a bound that the old reader on the same file is many times
over.* The old path -- `read_workbook`, or `decode` and a list of lines, then
every row in a list -- is kept in the child, verbatim from `1fefbc3`, and run
on the same files. Without that, a small figure could be a harness that
measures nothing.

*A dry run keeps an index entry for a row and not the row*: the same shape
at four times the rows grows by a few hundred bytes for each row added -- a
key, a row number, one cell -- where the old reader kept every cell of it.

*A commit holds one dictionary a row and no second copy*: what it grows by is
bounded per cell, and handing the rows to the writer adds nothing.

This is not the GR-352 acceptance measurement, the envelope these files sit
inside is provisional, and the bounds below are regression tripwires rather
than a ratified budget. `docs/features/data-import/worker-resource-envelope.md`
has the measurement these were set from and what is still owed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="peak resident set is read from /proc/self/status",
)

MEBIBYTE = 1024 * 1024
EMOJI = "\U0001f600"

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships"
TYPES = "application/vnd.openxmlformats-officedocument.spreadsheetml"

CHILD = """
import gc, json, os, sys, time
from datetime import datetime

for name, value in {
    "ENVIRONMENT": "dev",
    "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/db",
    "KORAS_DATABASE_URL": "postgresql://x:y@localhost/z",
    "ZITADEL_DOMAIN": "https://example.invalid",
    "ZITADEL_PROJECT_ID": "0",
}.items():
    os.environ.setdefault(name, value)

def status(field):
    with open("/proc/self/status") as handle:
        for line in handle:
            if line.startswith(field):
                return int(line.split()[1]) * 1024
    raise SystemExit("no " + field)

# Loaded before the baseline: a module the worker holds once is not what a
# job costs.
import openpyxl, openpyxl.styles.numbers, openpyxl.utils.datetime
from koras_api.core import imports as store
from koras_import import (
    FieldSpec, Format, ImportTarget, Operation, WriteRequest, decode, read_header,
    read_rows, read_workbook, request_for, resolve, rows_from, validate,
)

path, how, columns, keys = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
fmt = Format.CSV if path.endswith(".csv") else Format.XLSX
names = [f"f{n}" for n in range(1, columns + 1)]
target = ImportTarget(
    key="probe.memory",
    label_key="import.target.probe.memory",
    permission="imports.manage",
    fields=tuple(FieldSpec(name, f"import.field.{name}") for name in names),
    match_keys=tuple(names[:keys]),
    operations=(Operation.SKIP_DUPLICATE,),
    formats=(Format.CSV, Format.XLSX),
    max_rows=1_000_000,
)
run = store.Run(
    id="11111111-1111-1111-1111-111111111111", target=target.key, status="validating",
    format=fmt.value, source_file_id="x", delimiter=",", encoding="utf-8",
    columns=tuple(names), mapping={name: name for name in names},
    operation=Operation.SKIP_DUPLICATE.value, rows_total=0, rows_valid=0, errors_total=0,
    errors_cut=False, error=None, requested_by="u", committed_by=None,
    created_at=datetime.now(), started_at=None, finished_at=None,
)

def parse_as_before(raw):
    # `_parse` as it stood at 1fefbc3: every row, in a list.
    limits = store.limits_for(target, rows=True)
    if fmt is Format.XLSX:
        read = read_workbook(raw, limit=target.max_rows, ceiling=target.max_rows, limits=limits)
        header, rows = read.header, list(read.rows)
    else:
        decoded = decode(raw)
        lines = decoded.text.splitlines(keepends=True)
        header = read_header(lines, delimiter=",")
        rows = list(read_rows(lines, header=header, delimiter=",", limit=target.max_rows))
    return resolve(target, header.columns, run.mapping), rows

with open(path, "rb") as source:
    raw = source.read()
gc.collect()
before = status("VmRSS")
started = time.perf_counter()
handed = None
if how == "examine":
    examined = store.examine(raw, target, run)
    rows, keyed = examined.verdict.rows, len(examined.candidates.keys)
    ok = examined.verdict.ok
elif how == "prepare":
    verdict, mapped = store.prepare(raw, target, run)
    rows, keyed, ok = verdict.rows, len(mapped), verdict.ok
    read = status("VmHWM")
    request = WriteRequest(
        tenant_id="t", run_id=run.id, operation=Operation.SKIP_DUPLICATE,
        match_keys=tuple(target.match_keys),
        rows=rows_from(mapped, ceiling=target.max_rows, owned=True),
    )
    del mapped
    handed = max(0, status("VmHWM") - read)
elif how == "examine-as-before":
    resolved, parsed = parse_as_before(raw)
    verdict = validate(target, resolved, parsed)
    request = request_for(target, resolved, parsed, tenant_id="t", verdict=verdict)
    rows, keyed, ok = verdict.rows, len(request.keys), verdict.ok
else:
    raise SystemExit("unknown: " + how)
print(json.dumps({
    "grew": max(0, status("VmHWM") - before),
    "handed": handed,
    "seconds": round(time.perf_counter() - started, 3),
    "source": len(raw),
    "rows": rows,
    "keyed": keyed,
    "ok": ok,
}))
"""


def measure(path: Path, how: str = "examine", *, columns: int, keys: int = 1) -> dict[str, int]:
    done = subprocess.run(  # noqa: S603 - this interpreter, this file's own script
        [sys.executable, "-c", CHILD, str(path), how, str(columns), str(keys)],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        timeout=600,
    )
    answer: dict[str, int] = json.loads(done.stdout.strip().splitlines()[-1])
    return answer


# ── generating the files ─────────────────────────────────────────────────────


def letters(column: int) -> str:
    name = ""
    while column:
        column, rest = divmod(column - 1, 26)
        name = chr(65 + rest) + name
    return name


def repeated(piece: bytes, count: int) -> Iterator[bytes]:
    block = piece * 10_000
    for _ in range(count // 10_000):
        yield block
    yield piece * (count % 10_000)


def workbook(
    path: Path,
    *,
    sheet: Iterator[bytes],
    strings: Iterator[bytes] | None = None,
    after: Iterator[bytes] | None = None,
    others: int = 0,
    styles: Iterator[bytes] | None = None,
    names: Iterator[bytes] | None = None,
) -> None:
    """A workbook `openpyxl` opens, written part by part, never held whole."""
    overrides = f'<Override PartName="/xl/workbook.xml" ContentType="{TYPES}.sheet.main+xml"/>'
    relations = ""
    listed = ""
    for position in range(1, others + 2):
        overrides += (
            f'<Override PartName="/xl/worksheets/sheet{position}.xml" '
            f'ContentType="{TYPES}.worksheet+xml"/>'
        )
        relations += (
            f'<Relationship Id="rId{position}" Type="{RELS}/worksheet" '
            f'Target="worksheets/sheet{position}.xml"/>'
        )
        title = "Data" if position == 1 else f"Other{position}"
        listed += f'<sheet name="{title}" sheetId="{position}" r:id="rId{position}"/>'
    if strings is not None:
        overrides += (
            f'<Override PartName="/xl/sharedStrings.xml" ContentType="{TYPES}.sharedStrings+xml"/>'
        )
    if styles is not None:
        overrides += f'<Override PartName="/xl/styles.xml" ContentType="{TYPES}.styles+xml"/>'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            f"{overrides}</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            f'<Relationships xmlns="{PACKAGE}"><Relationship Id="rId1" '
            f'Type="{RELS}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        with archive.open("xl/workbook.xml", "w") as part:
            part.write(
                f'<workbook xmlns="{MAIN}" xmlns:r="{RELS}"><sheets>{listed}</sheets>'
                "<definedNames>".encode()
            )
            for piece in names or ():
                part.write(piece)
            part.write(b"</definedNames></workbook>")
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{PACKAGE}">{relations}</Relationships>',
        )
        if strings is not None:
            with archive.open("xl/sharedStrings.xml", "w") as part:
                part.write(f'<sst xmlns="{MAIN}">'.encode())
                for piece in strings:
                    part.write(piece)
                part.write(b"</sst>")
        if styles is not None:
            with archive.open("xl/styles.xml", "w") as part:
                for piece in styles:
                    part.write(piece)
        with archive.open("xl/worksheets/sheet1.xml", "w") as part:
            part.write(f'<worksheet xmlns="{MAIN}"><sheetData>'.encode())
            for piece in sheet:
                part.write(piece)
            part.write(b"</sheetData>")
            for piece in after or ():
                part.write(piece)
            part.write(b"</worksheet>")
        for position in range(2, others + 2):
            # No `<dimension>`: the old reader walks each of these to its end
            # when the workbook is loaded, to learn what one would have said.
            with archive.open(f"xl/worksheets/sheet{position}.xml", "w") as part:
                part.write(f'<worksheet xmlns="{MAIN}"><sheetData>'.encode())
                for row in range(1, 4001):
                    cells = "".join(
                        f'<c r="{letters(column)}{row}" t="inlineStr"><is><t>'
                        f"other sheet {row} {column}</t></is></c>"
                        for column in range(1, 11)
                    )
                    part.write(f'<row r="{row}">{cells}</row>'.encode())
                part.write(b"</sheetData></worksheet>")


def header(columns: int) -> bytes:
    cells = "".join(
        f'<c r="{letters(column)}1" t="inlineStr"><is><t>f{column}</t></is></c>'
        for column in range(1, columns + 1)
    )
    return f'<row r="1">{cells}</row>'.encode()


def naming(path: Path, texts: list[str], rows: int, columns: int) -> None:
    """Column A is each row's own short key; every other cell names a long string."""
    long = len(texts)

    def strings() -> Iterator[bytes]:
        for text in texts:
            yield f'<si><t xml:space="preserve">{text}</t></si>'.encode()
        for row in range(rows):
            yield f"<si><t>k{row}</t></si>".encode()

    def sheet() -> Iterator[bytes]:
        yield header(columns)
        for row in range(rows):
            at = row + 2
            cells = f'<c r="A{at}" t="s"><v>{long + row}</v></c>' + "".join(
                f'<c r="{letters(column)}{at}" t="s"><v>{(row + column) % long}</v></c>'
                for column in range(2, columns + 1)
            )
            yield f'<row r="{at}">{cells}</row>'.encode()

    workbook(path, strings=strings(), sheet=sheet())


def numbers(path: Path, rows: int, columns: int, **extra: object) -> None:
    def sheet() -> Iterator[bytes]:
        yield header(columns)
        for row in range(2, rows + 2):
            cells = "".join(
                f'<c r="{letters(column)}{row}"><v>{row * column}</v></c>'
                for column in range(1, columns + 1)
            )
            yield f'<row r="{row}">{cells}</row>'.encode()

    workbook(path, sheet=sheet(), **extra)  # type: ignore[arg-type]


def furnished(path: Path) -> None:
    """A small sheet, and 300,000 things that are not cells after it."""

    def after() -> Iterator[bytes]:
        yield b"<mergeCells>"
        yield from repeated(b'<mergeCell ref="AA9:AB9"/>', 120_000)
        yield b"</mergeCells><dataValidations>"
        yield from repeated(
            b'<dataValidation type="list" sqref="A2"><formula1>"a,b"</formula1></dataValidation>',
            60_000,
        )
        yield b"</dataValidations><hyperlinks>"
        yield from repeated(b'<hyperlink ref="A2" location="Data!A1" display="go"/>', 120_000)
        yield b"</hyperlinks>"

    numbers(path, 500, 4, after=after())


def beside(path: Path) -> None:
    """A small data sheet beside five others, a full stylesheet and many names."""

    def styles() -> Iterator[bytes]:
        yield f'<styleSheet xmlns="{MAIN}"><cellXfs>'.encode()
        yield from repeated(b'<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>', 60_000)
        yield b"</cellXfs></styleSheet>"

    def names() -> Iterator[bytes]:
        for position in range(150_000):
            yield f'<definedName name="n{position}">Data!$A$1</definedName>'.encode()

    numbers(path, 500, 4, others=5, styles=styles(), names=names())


def delimited(path: Path, rows: int, cell: Callable[[int, int], str], columns: int) -> None:
    with path.open("w", encoding="utf-8", newline="") as out:
        out.write(",".join(f"f{column}" for column in range(1, columns + 1)) + "\n")
        for row in range(rows):
            out.write(",".join(cell(row, column) for column in range(columns)) + "\n")


LONG = "b" * 31_999 + " "

#: The file's suffix, how to write it, how many columns it has, and how many of
#: them are the match key.
FILES: dict[str, tuple[str, Callable[[Path], None], int, int]] = {
    # 28,500 cells naming one 32,000-character string that needs its trailing
    # space stripped. A copy a cell is 870 MiB.
    "one-string": ("xlsx", lambda path: naming(path, [LONG], 1_500, 20), 20, 1),
    # The same at a quarter of the rows, for the old reader to be run on.
    "one-string-quarter": ("xlsx", lambda path: naming(path, [LONG], 375, 20), 20, 1),
    # The long string is half of every row's match key: 3,000 keys.
    "long-key-part": ("xlsx", lambda path: naming(path, ["B" * 32_000], 3_000, 3), 3, 2),
    "furnished": ("xlsx", furnished, 4, 1),
    "beside": ("xlsx", beside, 4, 1),
    # 300,000 cells, and a quarter as many.
    "cells": ("xlsx", lambda path: numbers(path, 15_000, 20), 20, 1),
    "cells-quarter": ("xlsx", lambda path: numbers(path, 3_750, 20), 20, 1),
    # 256 columns: 307,200 cells.
    "wide": ("xlsx", lambda path: numbers(path, 1_200, 256), 256, 1),
    "csv-wide": ("csv", lambda path: delimited(path, 1_200, lambda r, c: f"{r}v{c}", 256), 256, 1),
    # 12 MiB of ASCII with a single astral character on its second line.
    "csv-one-astral": (
        "csv",
        lambda path: delimited(
            path, 40_000, lambda r, c: f"{r:07d}{'x' * 66}" + (EMOJI if r == c == 0 else ""), 4
        ),
        4,
        1,
    ),
    # Every field ends in an astral character.
    "csv-astral": (
        "csv",
        lambda path: delimited(path, 40_000, lambda r, c: f"{r:07d}{'x' * 20}{EMOJI}", 4),
        4,
        1,
    ),
    "csv-rows": ("csv", lambda path: delimited(path, 60_000, lambda r, c: f"{r}v{c}", 5), 5, 1),
    "csv-rows-quarter": (
        "csv",
        lambda path: delimited(path, 15_000, lambda r, c: f"{r}v{c}", 5),
        5,
        1,
    ),
}


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> Callable[[str], Path]:
    root = tmp_path_factory.mktemp("gr352c")
    done: dict[str, Path] = {}

    def make(name: str) -> Path:
        if name not in done:
            suffix, write, _, _ = FILES[name]
            done[name] = root / f"{name}.{suffix}"
            write(done[name])
        return done[name]

    return make


#: One measurement of each file by each path, however many tests read it.
_MEASURED: dict[tuple[Path, str], dict[str, int]] = {}


def run(made: Callable[[str], Path], name: str, how: str = "examine") -> dict[str, int]:
    _, _, columns, keys = FILES[name]
    path = made(name)
    if (path, how) not in _MEASURED:
        _MEASURED[path, how] = measure(path, how, columns=columns, keys=keys)
    return _MEASURED[path, how]


# ── a dry run ────────────────────────────────────────────────────────────────

#: How far a dry run's peak may rise over the file it was handed, by case.
#:
#: Each is two to four times what was measured in `python:3.12-slim` on
#: 2026-10-01, which is the figure in the comment beside it, in mebibytes; the
#: second figure, where there is one, is the old reader on the same file or on
#: the quarter-sized one. The three CSVs of forty and sixty thousand rows are
#: the duplicate index -- a key, a row number and a cell for every row.
DRY_RUN_MAY_GROW: dict[str, int] = {
    "one-string": 8 * MEBIBYTE,  # 2.0; 218 at a quarter of the rows
    "long-key-part": 8 * MEBIBYTE,  # 2.0; 94
    "furnished": 8 * MEBIBYTE,  # 1.8; 155
    "beside": 8 * MEBIBYTE,  # 2.4; 114
    "cells": 16 * MEBIBYTE,  # 6.4
    "wide": 10 * MEBIBYTE,  # 3.3
    "csv-wide": 8 * MEBIBYTE,  # 2.0
    "csv-one-astral": 40 * MEBIBYTE,  # 19.1; 91
    "csv-astral": 48 * MEBIBYTE,  # 23.8; 78
    "csv-rows": 32 * MEBIBYTE,  # 16.5
}


@pytest.mark.parametrize("name", sorted(DRY_RUN_MAY_GROW))
def test_a_dry_run_stays_inside_its_bound(name: str, made: Callable[[str], Path]) -> None:
    answer = run(made, name)
    assert answer["grew"] < DRY_RUN_MAY_GROW[name], answer
    # And it was the dry run that ran: every row was read and judged.
    assert answer["ok"] is True and answer["rows"] >= 500, answer
    assert answer["keyed"] == answer["rows"], answer


def both(made: Callable[[str], Path], name: str) -> tuple[dict[str, int], dict[str, int]]:
    """The dry run, and the path it replaced, on one file -- with the same answer."""
    now = run(made, name)
    before = run(made, name, "examine-as-before")
    assert (before["rows"], before["keyed"], before["ok"]) == (
        now["rows"],
        now["keyed"],
        now["ok"],
    )
    return now, before


@pytest.mark.parametrize("name", ["one-string-quarter", "long-key-part", "furnished", "beside"])
def test_the_reader_the_worker_used_to_call_costs_many_times_more(
    name: str, made: Callable[[str], Path]
) -> None:
    # The proof that the bounds above measure something. Each of these is a
    # file the dry run now takes in about two mebibytes, and the old path took
    # between 94 and 218.
    now, before = both(made, name)
    assert before["grew"] > 20 * now["grew"], (now, before)
    assert before["grew"] > 60 * MEBIBYTE, before


@pytest.mark.parametrize("name", ["csv-one-astral", "csv-astral"])
def test_a_csv_is_no_longer_held_four_times(name: str, made: Callable[[str], Path]) -> None:
    # The file as one string, that string again as lines, and every row: 91
    # and 78 MiB where the dry run now takes 19 and 24, nearly all of it the
    # index.
    now, before = both(made, name)
    assert before["grew"] > 3 * now["grew"], (now, before)
    assert before["grew"] > now["grew"] + 40 * MEBIBYTE, (now, before)


@pytest.mark.parametrize(
    ("quarter", "whole"),
    [("cells-quarter", "cells"), ("csv-rows-quarter", "csv-rows")],
    ids=["xlsx", "csv"],
)
def test_a_dry_run_keeps_an_index_entry_for_a_row_and_not_the_row(
    quarter: str, whole: str, made: Callable[[str], Path]
) -> None:
    small, large = run(made, quarter), run(made, whole)
    assert large["rows"] == 4 * small["rows"]
    added = large["rows"] - small["rows"]
    # Measured at about 265 bytes for each row added, in both formats. A row
    # of twenty cells kept whole is nearer two thousand.
    assert (large["grew"] - small["grew"]) / added < 600, (small, large)


def test_a_string_every_cell_names_is_read_in_seconds(made: Callable[[str], Path]) -> None:
    """IMPORT-DEF-015, the half that was `clean_cell`.

    28,500 cells of one 32,000-character string. The old reader cleaned it
    once for every cell, a character at a time: about fifty seconds of it on
    the machine this was measured on, and half an hour for the million cells
    the envelope allows. It is cleaned once now. The bound is generous on
    purpose -- it has to hold on a busy runner -- and is still several times
    under the old figure.
    """
    answer = run(made, "one-string")
    assert answer["seconds"] < 15, answer


# ── a commit ─────────────────────────────────────────────────────────────────

#: A commit holds a dictionary for every row, because the writer's contract is
#: every row at once. Measured between 79 and 129 bytes a cell for these four
#: files; the bound is per cell so that it says what it is a bound on.
COMMIT_BYTES_A_CELL = 250


@pytest.mark.parametrize("name", ["cells", "wide", "csv-wide", "csv-rows"])
def test_a_commit_holds_one_dictionary_a_row_and_no_second_copy(
    name: str, made: Callable[[str], Path]
) -> None:
    _, _, columns, _ = FILES[name]
    answer = run(made, name, "prepare")
    cells = answer["rows"] * columns
    assert answer["keyed"] == answer["rows"] and answer["ok"] is True, answer
    assert answer["grew"] < cells * COMMIT_BYTES_A_CELL, (answer, cells)
    # Handing the rows to the writer adds nothing: they are not copied.
    assert answer["handed"] < 2 * MEBIBYTE, answer


@pytest.mark.parametrize("name", ["one-string", "long-key-part", "furnished", "beside"])
def test_a_commit_of_the_awkward_files_stays_inside_the_dry_run_s_bound_too(
    name: str, made: Callable[[str], Path]
) -> None:
    # The same four shapes through `prepare`: few rows, so the dictionaries
    # are small, and everything else is what the dry run already bounds.
    answer = run(made, name, "prepare")
    assert answer["grew"] < DRY_RUN_MAY_GROW[name] + 8 * MEBIBYTE, answer
    assert answer["ok"] is True, answer
