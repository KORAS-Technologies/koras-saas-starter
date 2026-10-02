"""The analysis route's memory, measured as the kernel measures it.

GR-352B. `test_import_inspection.py` proves the route answers what it
answered; `koras-import`'s own suite proves, with `tracemalloc`, that the
inspection keeps nothing it does not show. Neither is the figure an
out-of-memory kill is decided on. This file asks the kernel: each case runs
`core/imports.analyse` -- the function both routes reach, not the parser under
it -- in a process of its own, on a file generated to sit just inside one edge
of the safety envelope, and reports how far that process's peak resident set
(`VmHWM`) rose while it ran.

**Linux only, and skipped elsewhere rather than approximated**, for the reason
`test_preflight_memory.py` gives. Generator Integration runs both files by
name and fails if either skips.

**Three things are asserted.**

*The analysis of a file at the edge of the envelope barely moves the peak.*
Sixty-four mebibytes of decoded text, a million cells: files whose readers
GR-352 measured in the hundreds of megabytes.

*It does not grow with what it does not show.* The same shape at a quarter of
the size and at full size cost the same, because what is held is the sample.

*The measurement can tell the difference.* The same file is handed to the
canonical reader -- what the route called until GR-352B -- and must cost many
times more. Without that, a figure this small could be a harness that
measures nothing.

Nothing here is a fixture on disk. Every input is generated into a temporary
directory, streamed, so the test process holds none of them either.

This is not the GR-352 acceptance measurement, and the limits these files sit
inside are provisional. What it preserves is one property of one path: the
API's inspection is bounded by its sample and not by the file.
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

#: How far the analysing process's peak may rise over a file it has already
#: read into memory. Measured on 2026-10-01 in `python:3.12-slim`: the cases
#: below rose between 1.8 and 6.7 MiB over seven runs. Sixteen is the bound
#: the safety pass's own memory test uses, and leaves the same room for
#: another allocator.
MAY_GROW = 16 * MEBIBYTE

EMOJI = "\U0001f600"

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships"

CHILD = """
import gc, json, os, sys, time

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

# Loaded before the baseline: a module the API holds once is not what a
# request costs.
import openpyxl, openpyxl.styles.numbers, openpyxl.utils.datetime
from koras_api.core import imports as store
from koras_import import (
    FieldSpec, Format, ImportTarget, Operation, count_rows, decode, read_header,
    read_rows, read_workbook, sniff_delimiter,
)

path, fmt, how, max_rows = sys.argv[1], Format(sys.argv[2]), sys.argv[3], int(sys.argv[4])
target = ImportTarget(
    key="probe.memory",
    label_key="import.target.probe.memory",
    permission="imports.manage",
    fields=tuple(FieldSpec(f"f{n}", f"import.field.f{n}") for n in range(1, 9)),
    operations=(Operation.CREATE,),
    formats=(Format.CSV, Format.XLSX),
    max_rows=max_rows,
)
with open(path, "rb") as source:
    raw = source.read()
gc.collect()
before = status("VmRSS")
started = time.perf_counter()
if how == "inspected":
    found = store.analyse(raw, target, fmt)
    shown, seen = len(found.preview), found.rows_seen
elif fmt is Format.XLSX:
    # What the route called until GR-352B.
    read = read_workbook(
        raw, limit=store.PREVIEW, ceiling=max_rows, limits=store.limits_for(target, rows=False)
    )
    shown, seen = len(read.rows), read.rows_seen
else:
    decoded = decode(raw)
    delimiter = sniff_delimiter(decoded.text)
    lines = decoded.text.splitlines(keepends=True)
    header = read_header(lines, delimiter=delimiter)
    shown = len(list(read_rows(lines, header=header, delimiter=delimiter, limit=store.PREVIEW)))
    seen = count_rows(lines, delimiter=delimiter, ceiling=max_rows)
print(json.dumps({
    "grew": max(0, status("VmHWM") - before),
    "seconds": round(time.perf_counter() - started, 3),
    "source": len(raw),
    "shown": shown,
    "seen": seen,
}))
"""


def measure(path: Path, how: str = "inspected", *, max_rows: int = 50_000) -> dict[str, int]:
    fmt = "csv" if path.suffix == ".csv" else "xlsx"
    done = subprocess.run(  # noqa: S603 - this interpreter, this file's own script
        [sys.executable, "-c", CHILD, str(path), fmt, how, str(max_rows)],
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


def workbook(path: Path, *, strings: Iterator[bytes] | None, sheet: Iterator[bytes]) -> None:
    """A workbook `openpyxl` opens, written part by part, never held whole."""
    overrides = (
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    )
    if strings is not None:
        overrides += (
            '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        )
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
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{MAIN}" xmlns:r="{RELS}"><sheets>'
            '<sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{PACKAGE}"><Relationship Id="rId1" '
            f'Type="{RELS}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        if strings is not None:
            with archive.open("xl/sharedStrings.xml", "w") as part:
                part.write(f'<sst xmlns="{MAIN}">'.encode())
                for piece in strings:
                    part.write(piece)
                part.write(b"</sst>")
        with archive.open("xl/worksheets/sheet1.xml", "w") as part:
            part.write(f'<worksheet xmlns="{MAIN}"><sheetData>'.encode())
            for piece in sheet:
                part.write(piece)
            part.write(b"</sheetData></worksheet>")


def header(columns: int) -> bytes:
    cells = "".join(
        f'<c r="{letters(column)}1" t="inlineStr"><is><t>f{column}</t></is></c>'
        for column in range(1, columns + 1)
    )
    return f'<row r="1">{cells}</row>'.encode()


def shared(path: Path, count: int, text: str, *, late: bool = False) -> None:
    """`count` distinct shared strings, three to a row.

    With `late`, the sheet's first rows name the table's *last* strings, so a
    sample cannot be had from the head of the table.
    """

    def strings() -> Iterator[bytes]:
        for position in range(count):
            yield f"<si><t>{position:07d}{text}</t></si>".encode()

    def sheet() -> Iterator[bytes]:
        yield header(3)
        for row in range(2, count // 3 + 2):
            cells = ""
            for column in range(3):
                position = (row - 2) * 3 + column
                index = count - 1 - position if late else position
                cells += f'<c r="{letters(column + 1)}{row}" t="s"><v>{index}</v></c>'
            yield f'<row r="{row}">{cells}</row>'.encode()

    workbook(path, strings=strings(), sheet=sheet())


def inline(path: Path, count: int, text: str) -> None:
    def sheet() -> Iterator[bytes]:
        yield header(3)
        for row in range(2, count // 3 + 2):
            cells = "".join(
                f'<c r="{letters(column)}{row}" t="inlineStr"><is><t>{row:07d}{text}</t></is></c>'
                for column in range(1, 4)
            )
            yield f'<row r="{row}">{cells}</row>'.encode()

    workbook(path, strings=None, sheet=sheet())


def numbers(path: Path, rows: int, columns: int) -> None:
    def sheet() -> Iterator[bytes]:
        yield header(columns)
        for row in range(2, rows + 2):
            cells = "".join(
                f'<c r="{letters(column)}{row}"><v>{row * column}</v></c>'
                for column in range(1, columns + 1)
            )
            yield f'<row r="{row}">{cells}</row>'.encode()

    workbook(path, strings=None, sheet=sheet())


def delimited(
    path: Path, rows: int, columns: int, cell: str, *, second: str | None = None
) -> None:
    line = (",".join([cell] * columns) + "\n").encode()
    with path.open("wb") as out:
        out.write((",".join(f"f{column}" for column in range(1, columns + 1)) + "\n").encode())
        written = 0
        if second is not None:
            out.write((",".join([second] * columns) + "\n").encode())
            written = 1
        block = line * 1000
        while written + 1000 <= rows:
            out.write(block)
            written += 1000
        out.write(line * (rows - written))


#: Each file sits just inside one edge of the envelope `SAFETY_LIMITS` gives a
#: route: 64 MiB of source, 64 MiB of decoded text at its real width, a
#: million cells, 256 columns. All of them are accepted, which is the point --
#: these are the files the route still has to answer.
FILES: dict[str, tuple[str, Callable[[Path], None]]] = {
    # 60,000 strings of 250 characters, one astral: 63.8 MiB of decoded budget.
    "shared-astral": ("xlsx", lambda path: shared(path, 60_000, "a" * 242 + EMOJI)),
    # 60,000 strings of 1,000 ASCII characters: the same budget, a byte wide.
    "shared-ascii": ("xlsx", lambda path: shared(path, 60_000, "a" * 993)),
    # A quarter of it, for the comparison.
    "shared-ascii-quarter": ("xlsx", lambda path: shared(path, 15_000, "a" * 993)),
    # The same table, with the sample naming its last strings.
    "shared-late": ("xlsx", lambda path: shared(path, 60_000, "a" * 993, late=True)),
    "inline-astral": ("xlsx", lambda path: inline(path, 60_000, "a" * 242 + EMOJI)),
    # 49,900 rows of twenty numbers and a header: 998,020 cells.
    "cells": ("xlsx", lambda path: numbers(path, 49_900, 20)),
    # 240,000 rows of four 65-character fields: 960,000 cells and 63 MiB.
    "csv-large": ("csv", lambda path: delimited(path, 240_000, 4, "a" * 65)),
    "csv-quarter": ("csv", lambda path: delimited(path, 60_000, 4, "a" * 65)),
    # Every field ends in an emoji: 16.6 million characters, four bytes each.
    "csv-astral": ("csv", lambda path: delimited(path, 60_000, 4, "a" * 67 + EMOJI)),
    # ASCII but for one emoji on the second line. Decoded whole, as the reader
    # decodes it, every character of the file is four bytes wide.
    "csv-one-astral": ("csv", lambda path: delimited(path, 60_000, 4, "a" * 68, second=EMOJI)),
    # 256 columns, 3,900 rows: 998,656 three-character fields.
    "csv-many-fields": ("csv", lambda path: delimited(path, 3_900, 256, "abc")),
}

#: A target that takes every row of every file above, so the walk goes to the
#: end of each rather than stopping at a ceiling.
EVERY_ROW = 1_000_000


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> Callable[[str], Path]:
    root = tmp_path_factory.mktemp("gr352b")
    done: dict[str, Path] = {}

    def make(name: str) -> Path:
        if name not in done:
            suffix, write = FILES[name]
            done[name] = root / f"{name}.{suffix}"
            write(done[name])
        return done[name]

    return make


@pytest.mark.parametrize(
    "name", [name for name in sorted(FILES) if not name.endswith("quarter")]
)
def test_analysing_a_file_at_the_edge_of_the_envelope_barely_moves_the_peak(
    name: str, made: Callable[[str], Path]
) -> None:
    answer = measure(made(name), max_rows=EVERY_ROW)
    assert answer["grew"] < MAY_GROW, answer
    # And it was the analysis that ran: the sample is full and every row of
    # the file was counted.
    assert answer["shown"] == 200, answer
    assert answer["seen"] >= 3_900, answer


def test_a_file_over_its_ceiling_costs_no_more(made: Callable[[str], Path]) -> None:
    # The same 63 MiB CSV against a target that takes 50,000 rows of it: the
    # inspection stops one row past the ceiling, and the safety pass in front
    # of it still reads to the end.
    answer = measure(made("csv-large"), max_rows=50_000)
    assert answer["grew"] < MAY_GROW, answer
    assert answer["seen"] == 50_001 and answer["shown"] == 200, answer


@pytest.mark.parametrize(
    ("quarter", "whole"),
    [("shared-ascii-quarter", "shared-ascii"), ("csv-quarter", "csv-large")],
    ids=["xlsx", "csv"],
)
def test_four_times_the_file_is_not_four_times_the_memory(
    quarter: str, whole: str, made: Callable[[str], Path]
) -> None:
    small = measure(made(quarter), max_rows=EVERY_ROW)
    large = measure(made(whole), max_rows=EVERY_ROW)
    assert large["source"] > 3 * small["source"]
    # Not proportional, and not close to it: the same few megabytes. Measured
    # at 2.1 and 2.8 MiB for the workbooks and 1.8 and 1.8 for the CSVs.
    assert large["grew"] < small["grew"] + 4 * MEBIBYTE, (small, large)


@pytest.mark.parametrize("name", ["shared-astral", "csv-one-astral"])
def test_the_reader_the_route_used_to_call_costs_many_times_more(
    name: str, made: Callable[[str], Path]
) -> None:
    # The proof that the figures above measure something. Both readers are
    # handed a file the inspection takes in a few megabytes, and must not.
    path = made(name)
    inspected = measure(path, max_rows=EVERY_ROW)
    read = measure(path, "read", max_rows=EVERY_ROW)
    assert (read["shown"], read["seen"]) == (inspected["shown"], inspected["seen"])
    assert read["grew"] > 4 * MAY_GROW, read
    assert read["grew"] > 10 * inspected["grew"], (inspected, read)
