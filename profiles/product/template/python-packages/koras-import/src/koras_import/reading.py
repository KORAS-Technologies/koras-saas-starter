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
an error file *would* evaluate it. This module records the risk and does not
carry the fix, because the fix belongs where the file is written -- which, for
the only CSV this product hands back, is the browser: `guardCell` in
`apps/web/src/app/dashboard/imports/ImportPanel.tsx`.

This paragraph said "which is why the writer escapes" until 2026-09-22, and
`writing.py` neither escaped nor wrote a CSV. A docstring naming a control that
exists nowhere is worse than one that says nothing, because the next person
reads it and stops looking. IMP2-08 in
`docs/features/data-import/phase-2-review.md`.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

#: Tried in order, **strictly**. UTF-8 first because it is right most of the
#: time and wrong loudly; `cp1252` second because it is what a Windows
#: spreadsheet produces and it decodes almost any byte, so it must never be
#: tried first or it would silently mangle real UTF-8.
#:
#: `latin-1` is deliberately **not** in this tuple, and was until 2026-09-19.
#: It maps all 256 byte values and so cannot raise, which meant the loop below
#: always returned before reaching its own fallback: the fallback was
#: unreachable, `Decoded.replaced` was always False, and the page's "some
#: characters could not be read" banner could never be shown in any of the
#: three languages it was written in. IMP-03 in
#: `docs/features/data-import/review.md`.
ENCODINGS: tuple[str, ...] = ("utf-8-sig", "cp1252")

#: The last resort, used with replacement so the reader always produces
#: something a person can look at rather than an error they cannot act on --
#: and says that it did.
FALLBACK_ENCODING = "latin-1"

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
    #: True when no strict encoding fitted and the file was read byte-for-byte
    #: as `latin-1`. The import still proceeds — refusing a whole file because
    #: one cell has a stray byte helps nobody — and the run records it, so a
    #: customer wondering why one name looks wrong has an answer.
    replaced: bool


def decode(raw: bytes) -> Decoded:
    """Text, and which encoding produced it.

    Tries each encoding strictly before falling back, so a file that is really
    UTF-8 is never read as `cp1252`. The fallback cannot fail, so this never
    raises -- and when it is reached, the answer says so, which is the whole
    point of `replaced`.
    """
    for encoding in ENCODINGS:
        try:
            return Decoded(raw.decode(encoding), encoding, replaced=False)
        except UnicodeDecodeError:
            continue
    # `replaced` is True because the fallback was *reached*, not because a
    # character came back as U+FFFD. `latin-1` maps all 256 byte values, so
    # `errors="replace"` never replaces anything and testing for the
    # replacement character would be the same unreachable branch again, one
    # level down. What the flag means is: no strict encoding fitted this file,
    # so every byte was read as a latin-1 character and some of them are
    # probably not what the person who exported it saw.
    return Decoded(
        raw.decode(FALLBACK_ENCODING, errors="replace"),
        FALLBACK_ENCODING,
        replaced=True,
    )


def sniff_delimiter(sample: str) -> str:
    """Which delimiter the header uses.

    Counted rather than guessed by the standard library's sniffer, which reads
    a sample and can pick a character that happens to appear inside a value. A
    header is one line and its delimiter is the character that appears most
    often outside quotes — and ties go to the comma, because a header with one
    comma and one semicolon is far more likely to be comma-separated with a
    semicolon in a label than the reverse.
    """
    # Bounded before splitting. This read `sample.splitlines()[0]` and called
    # `splitlines()` a second time to test the same thing, so a whole file was
    # exploded into a list of lines twice to look at one of them.
    lines = sample[:MAX_CELL].splitlines()
    header = lines[0] if lines else ""
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
    reader = _reader(lines, delimiter=delimiter)
    try:
        raw = next(reader)
    except StopIteration:
        raise ReadRefused("the file is empty") from None
    return header_from(raw)


def header_from(raw: Sequence[str]) -> Header:
    """Column names from the first row's cells, whatever produced them.

    Factored out of `read_header` on 2026-09-29 so the workbook reader
    names, suffixes and fills columns by exactly the rule the CSV reader
    does. Two readers with two header rules would be two files that map
    differently from the same spreadsheet saved twice.
    """
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
    reader = _reader(lines, delimiter=delimiter)
    try:
        next(reader)
    except StopIteration:
        return

    produced = 0
    for offset, raw in enumerate(reader, start=2):
        if not any(cell.strip() for cell in raw):
            continue
        yield row_from(offset, raw, header)
        produced += 1
        if produced >= limit:
            return


#: C0 control characters other than tab, newline and carriage return. A NUL
#: passes every check the validator makes and fails at the database, on row
#: forty thousand, after a dry run said the file was clean -- IMP2-21 in
#: `docs/features/data-import/phase-2-review.md`. Removed at the reader, for
#: every format, because a control character in a spreadsheet cell is never
#: something the person typing meant.
_CONTROLS = {chr(code) for code in range(32) if chr(code) not in "\t\n\r"}


def clean_cell(text: str) -> str:
    """A cell as the validator should see it: stripped, and free of controls."""
    if any(char in _CONTROLS for char in text):
        text = "".join(char for char in text if char not in _CONTROLS)
    return text.strip()


def row_from(number: int, raw: Sequence[str], header: Header) -> Row:
    """One row from its cells, by the rule both readers share."""
    width = len(header.columns)
    cells = {
        name: (clean_cell(raw[index]) if index < len(raw) else "")
        for index, name in enumerate(header.columns)
    }
    return Row(
        number=number,
        cells=cells,
        short=len(raw) < width,
        long=len(raw) > width,
    )


def _bounded(lines: Iterable[str]) -> Iterator[str]:
    """Refuse a *line* large enough to be a file.

    The standard library's own field limit is process-wide and raising it is a
    global change; this bounds the input instead, which is local and testable.

    **A line is not a field**, and this used to be written as though it were. A
    quoted field may span any number of lines, so a field can be under this
    limit on every one of its lines and far over `csv`'s own field limit in
    total -- which `csv` reports by raising `csv.Error`, not `ReadRefused`. One
    unterminated double quote is enough, because `csv` then absorbs the rest of
    the file into a single field. `_reader` below is the other half of the
    bound. IMP2-07 in `docs/features/data-import/phase-2-review.md`.
    """
    for line in lines:
        if len(line) > MAX_CELL:
            raise ReadRefused(
                f"a line is {len(line)} characters, over the {MAX_CELL} limit; "
                "this is a file in a cell rather than a row"
            )
        yield line


def _reader(lines: Iterable[str], *, delimiter: str) -> Iterator[list[str]]:
    """Rows from `csv`, with its own failures turned into refusals.

    Everything this module raises is a `ReadRefused` a route can answer 422 to
    and a person can act on. `csv.Error` is neither: it escaped to the caller,
    which caught `ReadRefused` alone, and a customer with one stray quote in
    their export got a 500 with nothing to do about it.
    """
    reader = csv.reader(_bounded(lines), delimiter=delimiter)
    while True:
        try:
            row = next(reader)
        except StopIteration:
            return
        except csv.Error as broken:
            raise ReadRefused(
                "the file could not be read as a table: "
                f"{broken}. A cell running past the end of its row is usually "
                "an unclosed quotation mark"
            ) from broken
        yield row


def count_rows(lines: Iterable[str], *, delimiter: str, ceiling: int) -> int:
    """How many data rows, stopping once the ceiling is exceeded.

    Stops rather than counting to the end: the answer a caller needs is "more
    than the ceiling", and counting nine million rows to say so is nine million
    rows of work to refuse the file anyway. Returns `ceiling + 1` in that case.
    """
    reader = _reader(lines, delimiter=delimiter)
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
