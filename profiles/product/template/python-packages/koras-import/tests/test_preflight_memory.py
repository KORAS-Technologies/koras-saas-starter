"""The safety pass's own memory, measured as the kernel measures it.

GR-352's numbers were resident-set figures from a Linux container, because
that is what an out-of-memory kill is decided on. `tracemalloc` -- which
`test_preflight.py` uses, and which runs everywhere -- sees Python's own
allocations and nothing of `expat`'s or `zlib`'s. So this file asks the
kernel: each case runs the scan in a process of its own and reports how far
that process's peak resident set (`VmHWM`) rose while it ran.

**Linux only, and skipped elsewhere rather than approximated.** There is no
`/proc` on the other platforms and a peak-working-set figure from one of them
is a different quantity; a memory assertion that passes on a laptop and means
something else in the container is worse than none.

**Each input is far larger than the scan may grow.** A workbook of 64 MiB of
text, a 32 MiB CSV: files whose readers GR-352 measured in the hundreds of
megabytes. The scan is given limits it cannot hit, so it reads every byte and
the figure is the scan's rather than an early refusal's -- and then the same
files are scanned under the provisional limits and must be refused.

Nothing here is a fixture on disk. Every input is generated into `tmp_path`,
streamed, so the test process does not hold one either.

This is not the GR-352 acceptance measurement. That is the reader's memory
under the worst *accepted* input, against a ratified headroom, and it is still
owed. This preserves one property: the check that guards the reader does not
itself need guarding.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="peak resident set is read from /proc/self/status",
)

MEBIBYTE = 1024 * 1024

#: How far the scanning process's peak may rise over a file it has already
#: read into memory. Measured on 2026-10-01 in `python:3.12-slim`: the eleven
#: cases rose between 0.6 and 4.1 MiB, on inputs that decode to as much as
#: 256 MiB. Sixteen leaves room for an allocator on another libc, and is a
#: small fraction of what any input below would cost its reader.
MAY_GROW = 16 * MEBIBYTE

EMOJI = "\U0001f600"

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships"

#: Limits nothing below can reach, so a scan reads its whole input.
UNBOUNDED = {
    "max_source_bytes": 1 << 40,
    "max_uncompressed_bytes": 1 << 40,
    "max_decoded_string_bytes": 1 << 40,
    "max_cells": 1 << 40,
    "max_columns": 1 << 40,
}

CHILD = """
import json, sys

def peak():
    with open("/proc/self/status") as status:
        for line in status:
            if line.startswith("VmHWM"):
                return int(line.split()[1]) * 1024
    raise SystemExit("no VmHWM")

from koras_import import Format, SafetyLimits, survey

path, fmt, limits = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
with open(path, "rb") as source:
    raw = source.read()
before = peak()
found = survey(raw, Format(fmt), SafetyLimits(**limits))
print(json.dumps({
    "grew": peak() - before,
    "code": found.refusal.code if found.refusal else None,
    "decoded": found.decoded_string_bytes,
    "cells": found.cells,
    "columns": found.columns,
    "source": len(raw),
}))
"""


def scan(path: Path, fmt: str, limits: dict[str, int]) -> dict[str, int | str | None]:
    done = subprocess.run(  # noqa: S603 - this interpreter, this file's own script
        [sys.executable, "-c", CHILD, str(path), fmt, json.dumps(limits)],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        timeout=300,
    )
    answer: dict[str, int | str | None] = json.loads(done.stdout)
    return answer


def workbook(path: Path, *, strings: list[bytes] | None, sheet: list[bytes]) -> None:
    """A workbook written part by part, so no part is ever one string here."""
    relations = f'<Relationship Id="rId1" Type="{RELS}/worksheet" Target="worksheets/sheet1.xml"/>'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{MAIN}" xmlns:r="{RELS}"><sheets>'
            '<sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{PACKAGE}">{relations}</Relationships>',
        )
        with archive.open("xl/worksheets/sheet1.xml", "w") as part:
            part.write(f'<worksheet xmlns="{MAIN}"><sheetData>'.encode())
            for piece in sheet:
                part.write(piece)
            part.write(b"</sheetData></worksheet>")
        if strings is not None:
            with archive.open("xl/sharedStrings.xml", "w") as part:
                part.write(f'<sst xmlns="{MAIN}">'.encode())
                for piece in strings:
                    part.write(piece)
                part.write(b"</sst>")


#: 16 KiB of ASCII and one astral character: a string the reader stores at
#: four bytes a character. Four thousand of them are 64 MiB of file text and
#: about 256 MiB decoded.
WIDE = ("a" * 16_000 + EMOJI).encode()
MANY = 4000


@pytest.fixture(scope="module")
def shared_astral(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("gr352") / "shared-astral.xlsx"
    workbook(
        path,
        strings=[b"<si><t>" + WIDE + b"</t></si>"] * MANY,
        sheet=[
            f'<row r="{n}"><c r="A{n}" t="s"><v>{n - 1}</v></c></row>'.encode()
            for n in range(1, MANY + 1)
        ],
    )
    return path


@pytest.fixture(scope="module")
def inline_astral(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("gr352") / "inline-astral.xlsx"
    workbook(
        path,
        strings=None,
        sheet=[
            f'<row r="{n}"><c r="A{n}" t="inlineStr"><is><t>'.encode()
            + WIDE
            + b"</t></is></c></row>"
            for n in range(1, MANY + 1)
        ],
    )
    return path


@pytest.fixture(scope="module")
def many_strings(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A million short strings: the shape where a tree, not text, is the cost."""
    path = tmp_path_factory.mktemp("gr352") / "many-strings.xlsx"
    workbook(
        path,
        strings=[
            b"".join(b"<si><t>s%d</t></si>" % n for n in range(start, start + 10_000))
            for start in range(0, 1_000_000, 10_000)
        ],
        sheet=[b'<row r="1"><c r="A1" t="s"><v>0</v></c></row>'],
    )
    return path


@pytest.fixture(scope="module")
def many_columns(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Two hundred rows, three thousand numeric cells wide: 600,000 cells."""
    path = tmp_path_factory.mktemp("gr352") / "many-columns.xlsx"
    workbook(
        path,
        strings=None,
        sheet=[
            b'<row r="%d">' % n + b"<c><v>12345</v></c>" * 3000 + b"</row>"
            for n in range(1, 201)
        ],
    )
    return path


@pytest.fixture(scope="module")
def one_astral_csv(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """32 MiB of ASCII with one emoji on its second line.

    The GR-352 shape. Decoded whole, as the reader decodes it, this is a
    128 MiB string -- the emoji is early so that everything after it is wide.
    """
    path = tmp_path_factory.mktemp("gr352") / "one-astral.csv"
    line = b"Ada Lovelace,a note about her,and another column of text\n"
    with path.open("wb") as out:
        out.write(b"Name,Note,More\n" + EMOJI.encode() + b",x,y\n")
        block = line * 10_000
        for _ in range(32 * MEBIBYTE // len(block) + 1):
            out.write(block)
    return path


@pytest.fixture(scope="module")
def many_fields_csv(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Three thousand rows of a thousand three-character fields: 3M cells."""
    path = tmp_path_factory.mktemp("gr352") / "many-fields.csv"
    row = b",".join([b"abc"] * 1000) + b"\n"
    with path.open("wb") as out:
        for _ in range(3001):
            out.write(row)
    return path


XLSX_CASES = ["shared_astral", "inline_astral", "many_strings", "many_columns"]
CSV_CASES = ["one_astral_csv", "many_fields_csv"]


@pytest.mark.parametrize("case", XLSX_CASES + CSV_CASES)
def test_reading_all_of_a_large_file_barely_moves_the_peak(
    case: str, request: pytest.FixtureRequest
) -> None:
    path: Path = request.getfixturevalue(case)
    answer = scan(path, "csv" if case in CSV_CASES else "xlsx", UNBOUNDED)
    assert answer["code"] is None, answer
    assert isinstance(answer["grew"], int) and answer["grew"] < MAY_GROW, answer
    # And the file was worth measuring: what it would decode to, or how many
    # cells it holds, is many times what the scan was allowed to grow by.
    assert isinstance(answer["decoded"], int) and isinstance(answer["cells"], int)
    assert answer["decoded"] > 4 * MAY_GROW or answer["cells"] >= 600_000, answer


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("shared_astral", "import.preflight.decoded_too_large"),
        ("inline_astral", "import.preflight.decoded_too_large"),
        ("many_columns", "import.preflight.too_many_columns"),
        ("one_astral_csv", "import.preflight.decoded_too_large"),
        ("many_fields_csv", "import.preflight.too_many_columns"),
    ],
)
def test_the_provisional_limits_refuse_each_of_them_and_cheaply(
    case: str, code: str, request: pytest.FixtureRequest
) -> None:
    path: Path = request.getfixturevalue(case)
    answer = scan(path, "csv" if case in CSV_CASES else "xlsx", {})
    assert answer["code"] == code, answer
    assert isinstance(answer["grew"], int) and answer["grew"] < MAY_GROW, answer
