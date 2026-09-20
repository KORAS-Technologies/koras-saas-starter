"""Turning a file somebody exported from something else into rows.

Everything here is about the gap between what a spreadsheet produces and what a
parser expects, because that gap is where an import feature is actually judged.
A file exported from Excel on a European machine is `cp1252` with semicolons; a
file exported from a web application is UTF-8 with a byte-order mark; a file
somebody edited by hand has a trailing blank line and one row with an extra
comma. None of those is malformed to the person who sent it.

**The reader streams.** Every function here takes an iterable of lines and
yields rows, so nothing holds the whole file. Phase 1's caller happens to hand
it the whole text, because the size ceiling makes that safe and a chunked
worker is Phase 4 — but the seam is here from the start, so Phase 4 is a
different caller rather than a different reader.

**A cell is never evaluated.** A value beginning `=`, `+`, `-` or `@` is text
here and stays text. The danger is on the way back out: a spreadsheet opening
an error file *would* evaluate it, which is why the writer escapes. This module
records the risk and does not carry the fix, because the fix belongs where the
file is written.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

#: Tried in order. UTF-8 first because it is right most of the time and wrong
#: loudly; `cp1252` second because it is what a Windows spreadsheet produces
#: and it decodes almost any byte, so it must never be tried first or it would
#: silently mangle real UTF-8. `latin-1` last, which cannot fail, so the reader
#: always produces something a person can look at rather than an error they
#: cannot act on.
ENCODINGS: tuple[str, ...] = ("utf-8-sig", "cp1252", "latin-1")

#: Sniffed from the header, in this order. Comma first; semicolon next, because
#: it is what a European Excel writes; then tab and pipe.
DELIMITERS: tuple[str, ...] = (",", ";", "\t", "|")

#: How many rows a preview shows. Enough to see whether a mapping is right and
#: few enough that the browser draws it through a client-paginated table, which
#: is what the shared table is as of 2026-09-19.
PREVIEW_ROWS = 200

#: A single field longer than this is refused rather than stored. The default
#: field limit is about 128 KiB and a cell that large is a file in a cell.
MAX_CELL = 32 * 1024


class ReadRefused(ValueError):
    """The file cannot be read as a table at all."""


@dataclass(frozen=True)
class Decoded:
    text: str
    encoding: str
    #: True when characters could not be decoded and were replaced. The import
    #: still proceeds — refusing a whole file because one cell has a stray byte
    #: helps nobody — and the run records it, so a customer wondering why one
    #: name looks wrong has an answer.
    replaced: bool


def decode(raw: bytes) -> Decoded:
    """Text, and which encoding produced it.

    Tries each encoding strictly before falling back, so a file that is really
    UTF-8 is never read as `cp1252`. The last encoding cannot fail, so this
    never raises.
    """
    for encoding in ENCODINGS:
        try:
            return Decoded(raw.decode(encoding), encoding, replaced=False)
        except UnicodeDecodeError:
            continue
    return Decoded(raw.decode("latin-1", errors="replace"), "latin-1", replaced=True)


def sniff_delimiter(sample: str) -> str:
    """Which delimiter the header uses.

    Counted rather than guessed by the standard library's sniffer, which reads
    a sample and can pick a character that happens to appear inside a value. A
    header is one line and its delimiter is the character that appears most
    often outside quotes — and ties go to the comma, because a header with one
    comma and one semicolon is far more likely to be comma-separated with a
    semicolon in a label than the reverse.
    """
    header = sample.splitlines()[0] if sample.splitlines() else ""
    best = ","
    most = 0
    for candidate in DELIMITERS:
        count = _count_outside_quotes(header, candidate)
        if count > most:
            best, most = candidate, count
    return best


def _count_outside_quotes(line: str, character: str) -> int:
    inside = False
    count = 0
    for char in line:
        if char == '"':
            inside = not inside
        elif char == character and not inside:
            count += 1
    return count


@dataclass(frozen=True)
class Header:
    columns: tuple[str, ...]
    #: Columns whose name appeared more than once. They are kept, suffixed, so
    #: a mapping can still name one of them — dropping them would silently lose
    #: a column somebody meant to import.
    duplicated: tuple[str, ...]
    #: Columns with no name at all, which a trailing delimiter produces. Kept
    #: and named, for the same reason.
    unnamed: tuple[str, ...]


def read_header(lines: Iterable[str], *, delimiter: str) -> Header:
    """The first row, as column names.

    Refuses an empty file and a header with no usable column. Everything else
    is repaired rather than refused: a person cannot edit the export they were
    given.
    """
    reader = csv.reader(_bounded(lines), delimiter=delimiter)
    try:
        raw = next(reader)
    except StopIteration:
        raise ReadRefused("the file is empty") from None

    seen: dict[str, int] = {}
    columns: list[str] = []
    duplicated: list[str] = []
    unnamed: list[str] = []
    for index, cell in enumerate(raw):
        name = cell.strip()
        if not name:
            name = f"column_{index + 1}"
            unnamed.append(name)
        if name in seen:
            seen[name] += 1
            duplicated.append(name)
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        columns.append(name)

    if not columns:
        raise ReadRefused("the file's first row names no columns")
    return Header(tuple(columns), tuple(dict.fromkeys(duplicated)), tuple(unnamed))


@dataclass(frozen=True)
class Row:
    """One data row, with the number a person would count to in their file."""

    #: 1-based and **including the header**, so row 2 is the first data row.
    #: That is what a spreadsheet's left margin says, and an error report whose
    #: numbers disagree with the file is an error report nobody can use.
    number: int
    cells: dict[str, str]
    #: True when the row had fewer cells than the header. The missing ones are
    #: empty, which is usually what was meant; recorded so a validation failure
    #: on a required field can say why it was empty.
    short: bool
    #: True when the row had more cells than the header. The extra ones are
    #: dropped — there is no column to put them in — and this is what lets the
    #: run report that rather than silently losing them.
    long: bool


def read_rows(
    lines: Iterable[str], *, header: Header, delimiter: str, limit: int
) -> Iterator[Row]:
    """Every data row, in order, up to `limit`.

    A blank line is skipped rather than producing an empty row: a trailing
    newline is not a record, and treating it as one puts a spurious error at
    the bottom of every report.
    """
    reader = csv.reader(_bounded(lines), delimiter=delimiter)
    try:
        next(reader)
    except StopIteration:
        return

    width = len(header.columns)
    produced = 0
    for offset, raw in enumerate(reader, start=2):
        if not any(cell.strip() for cell in raw):
            continue
        cells = {
            name: (raw[index].strip() if index < len(raw) else "")
            for index, name in enumerate(header.columns)
        }
        yield Row(
            number=offset,
            cells=cells,
            short=len(raw) < width,
            long=len(raw) > width,
        )
        produced += 1
        if produced >= limit:
            return


def _bounded(lines: Iterable[str]) -> Iterator[str]:
    """Refuse a cell large enough to be a file.

    The standard library's own field limit is process-wide and raising it is a
    global change; this bounds the input instead, which is local and testable.
    """
    for line in lines:
        if len(line) > MAX_CELL:
            raise ReadRefused(
                f"a line is {len(line)} characters, over the {MAX_CELL} limit; "
                "this is a file in a cell rather than a row"
            )
        yield line


def count_rows(lines: Iterable[str], *, delimiter: str, ceiling: int) -> int:
    """How many data rows, stopping once the ceiling is exceeded.

    Stops rather than counting to the end: the answer a caller needs is "more
    than the ceiling", and counting nine million rows to say so is nine million
    rows of work to refuse the file anyway. Returns `ceiling + 1` in that case.
    """
    reader = csv.reader(_bounded(lines), delimiter=delimiter)
    try:
        next(reader)
    except StopIteration:
        return 0
    count = 0
    for raw in reader:
        if not any(cell.strip() for cell in raw):
            continue
        count += 1
        if count > ceiling:
            return count
    return count
