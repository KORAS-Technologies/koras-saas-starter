"""Whether a file is safe to hand to the reader, decided before the reader runs.

The readers in this package are honest about rows and dishonest about memory.
`read_workbook` hands the bytes to `openpyxl`, which builds the workbook's
whole shared-string table before the first row is asked for; the CSV path
decodes the whole file into one string before the first line is split. Both
then discover the file was too much -- after holding all of it.

GR-352 measured what that costs on Linux, in a container, on 2026-10-01: a
workbook inside every limit this package had could take a worker to about
1.46 GiB resident. Four things it found decide the shape of this module.

**Compressed size predicts nothing.** A 0.3 MiB workbook reached 1.4 GiB.

**Uncompressed size is not enough either.** The same 234 MiB of workbook text
cost 406 MiB as plain ASCII and 1,458 MiB with one emoji in each cell, because
CPython stores a string at the width of its *widest* character: one byte a
character, two, or four. One astral character makes every other character in
that string four bytes wide.

**Cells are a dimension of their own.** Sixteen million three-character fields
are 61 MiB of file and 1.4 GiB of worker.

**The checks came too late.** Every one of those was refused, where it was
refused at all, after the materialisation it should have prevented.

So this module reads the file the cheap way first. A workbook's parts are
streamed through `expat` with no tree built, so its memory does not grow with
the workbook's text; a CSV is decoded a chunk at a time, so no string the size
of the file ever exists here. Both stop at the first limit crossed.

**It decides nothing about the data.** No value is converted, trimmed or
reinterpreted. The answer is only whether the existing reader may be called.

**It scans the parts the reader will read, found the way the reader finds
them.** Until IMPORT-DEF-017 was closed on 2026-10-01 it did not: it knew a
string table and a worksheet by their root element, read the sheet list from a
fixed part name, and counted only cells called `c` -- while `openpyxl` takes
the string table from the content types, the workbook part from the content
types, the sheet from the *last* `sheets` element through whatever relationship
it names, and treats every child of a row as a cell. Nine different packages
were called safe with their text and cells uncounted, and then read in full.
`_package` below is the reader's own resolution, restated; `read_workbook`
then refuses any sheet this pass did not scan, so the two cannot drift apart
quietly again.

**The numbers are provisional.** `SafetyLimits` carries interim GR-352
defaults, chosen to be conservative and not ratified by anybody: the memory
envelope these protect is an open NFR decision, and GR-352 stays open until it
is taken and measured. See `docs/features/data-import/preflight-safety-envelope.md`.
"""

from __future__ import annotations

import codecs
import io
import posixpath
import zipfile
import zlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from itertools import chain
from xml.parsers import expat

from .reading import (
    ENCODINGS,
    FALLBACK_ENCODING,
    MAX_CELL,
    ReadRefused,
    _reader,
    sniff_delimiter,
)
from .targets import Format

# ── the limits ───────────────────────────────────────────────────────────────

#: The compressed ceiling the API has enforced from the file index since
#: IMP-02. Repeated here so the engine refuses on its own, whoever calls it.
MAX_SOURCE_BYTES = 64 * 1024 * 1024

#: Summed from the zip directory before any entry is opened. ADR 0012 D12.
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024

#: PROVISIONAL (GR-352, pending NFR ratification). The estimated bytes of
#: decoded text the reader would hold, by `decoded_cost` below. Set equal to
#: the source ceiling on purpose: no one-byte-wide CSV accepted before this
#: existed is refused by it. What it newly refuses is amplification -- a
#: workbook whose strings decompress past it, and text made two or four bytes
#: wide by its widest character.
MAX_DECODED_STRING_BYTES = 64 * 1024 * 1024

#: PROVISIONAL (GR-352, pending NFR ratification). Cells the file contains,
#: counted rather than inferred from rows and declared fields. GR-352 measured
#: roughly 100 bytes of worker memory a cell.
MAX_CELLS = 1_000_000

#: PROVISIONAL (GR-352, pending NFR ratification). The widest row, by the cell
#: references actually present and never by the sheet's own `<dimension>`.
MAX_COLUMNS = 256

#: PROVISIONAL (GR-352, pending NFR ratification). `zipfile` builds an object
#: for every directory entry before anything else can be asked of the archive;
#: a workbook has tens. Measured on 2026-10-01 while building this: 400,000
#: empty entries are a 33 MiB file, about 180 MiB of directory objects by
#: `tracemalloc`, and seventeen seconds to open -- inside the source ceiling
#: and before any other check could run.
MAX_ARCHIVE_ENTRIES = 4096


@dataclass(frozen=True)
class SafetyLimits:
    """The envelope a source must fit before it is parsed.

    The first two are the limits this framework already had. The rest are
    interim GR-352 defaults -- see the constants above -- and a product or a
    ratified NFR replaces them by constructing its own.

    `max_rows` is None when the caller answers the row ceiling itself. The
    analysis route does: it reports `over_ceiling` and the mapping route
    refuses, and moving that refusal here would change what the route answers.
    """

    max_source_bytes: int = MAX_SOURCE_BYTES
    max_uncompressed_bytes: int = MAX_UNCOMPRESSED_BYTES
    max_decoded_string_bytes: int = MAX_DECODED_STRING_BYTES
    max_cells: int = MAX_CELLS
    max_columns: int = MAX_COLUMNS
    max_archive_entries: int = MAX_ARCHIVE_ENTRIES
    max_rows: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "max_source_bytes",
            "max_uncompressed_bytes",
            "max_decoded_string_bytes",
            "max_cells",
            "max_columns",
            "max_archive_entries",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be at least 1")
        if self.max_rows is not None and self.max_rows < 1:
            raise ValueError("max_rows must be at least 1 when it is set")


#: The interim defaults, named so a caller says which envelope it means.
PROVISIONAL_LIMITS = SafetyLimits()


# ── the refusal ──────────────────────────────────────────────────────────────


class RefusalCode(StrEnum):
    """Why a source was refused, for a machine. The sentence is for a person."""

    SOURCE_TOO_LARGE = "import.preflight.source_too_large"
    UNCOMPRESSED_TOO_LARGE = "import.preflight.uncompressed_too_large"
    DECODED_TOO_LARGE = "import.preflight.decoded_too_large"
    TOO_MANY_CELLS = "import.preflight.too_many_cells"
    TOO_MANY_COLUMNS = "import.preflight.too_many_columns"
    TOO_MANY_ROWS = "import.preflight.too_many_rows"
    TOO_MANY_ENTRIES = "import.preflight.too_many_entries"
    LINE_TOO_LONG = "import.preflight.line_too_long"
    MACROS = "import.preflight.macros"
    MALFORMED = "import.preflight.malformed"


#: The refusals that mean "too big for one run" rather than "not a table".
ENVELOPE_CODES: frozenset[RefusalCode] = frozenset(
    {
        RefusalCode.SOURCE_TOO_LARGE,
        RefusalCode.UNCOMPRESSED_TOO_LARGE,
        RefusalCode.DECODED_TOO_LARGE,
        RefusalCode.TOO_MANY_CELLS,
        RefusalCode.TOO_MANY_COLUMNS,
        RefusalCode.TOO_MANY_ENTRIES,
    }
)


class PreflightRefused(ReadRefused):
    """The source is outside the envelope, or is not a table at all.

    A `ReadRefused`, so every caller that already answers one answers this
    without changing: the routes with a 422 and the worker with a failed run
    carrying the sentence. `code` is what lets a caller say something narrower.
    """

    def __init__(
        self,
        code: RefusalCode,
        message: str,
        *,
        limit: int | None = None,
        observed: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.limit = limit
        #: How far the count had got when it was stopped. A lower bound: the
        #: scan stops at the first limit crossed rather than measuring how far
        #: past it the file goes.
        self.observed = observed


@dataclass(frozen=True)
class Refusal:
    code: RefusalCode
    message: str
    limit: int | None = None
    observed: int | None = None


@dataclass(frozen=True)
class Preflight:
    """What a source contains, as far as safety is concerned.

    One shape for both formats. When `refusal` is set the counts are what had
    been seen when the scan stopped, so they are lower bounds.
    """

    format: Format
    source_bytes: int
    #: The zip directory's declared total. None for a CSV.
    uncompressed_bytes: int | None
    #: By `decoded_cost`: an estimate of string storage, not of process memory.
    decoded_string_bytes: int
    #: Bytes a character of the widest text seen: 1, 2 or 4.
    widest_character: int
    cells: int
    columns: int
    #: Data rows by the reader's own rule: the header is not one and a blank
    #: row is not one.
    rows: int
    #: The encoding the CSV decoded under. None for a workbook.
    encoding: str | None = None
    refusal: Refusal | None = None
    #: The workbook part the reader will open, the worksheet part it will
    #: read rows from with that sheet's title, and the part it will load its
    #: string table from -- each resolved the way the reader resolves it, and
    #: each scanned by this pass whatever its root element is called. None for
    #: a CSV, and where the package cannot be followed.
    workbook_part: str | None = None
    sheet_part: str | None = None
    sheet_title: str | None = None
    strings_part: str | None = None

    @property
    def safe(self) -> bool:
        return self.refusal is None


# ── what a string costs ──────────────────────────────────────────────────────

#: A string object's own header and terminator. CPython 3.12 needs 41 bytes
#: for an empty ASCII string and at most 60 before the characters of a wide
#: one; sixty-four covers each of them.
STRING_OVERHEAD = 64


def width_of(text: str) -> int:
    """Bytes CPython stores each character of this string in: 1, 2 or 4.

    PEP 393. The width is the string's, not the character's: it is set by the
    widest character present, so `"a" * 1000 + "\\U0001F600"` is four bytes a
    character throughout. Counting code points alone misses a factor of four.
    """
    if text.isascii():
        return 1
    top = ord(max(text))
    if top < 0x100:
        return 1
    return 2 if top < 0x10000 else 4


def decoded_cost(characters: int, width: int) -> int:
    """An upper bound on the bytes one decoded string of that shape occupies.

    `STRING_OVERHEAD + characters * width`. Not the allocator's figure to the
    byte: it bounds the character payload, which is the term GR-352 found
    dominating, and it is never below `sys.getsizeof` of the real string.
    """
    return STRING_OVERHEAD + characters * width


def string_cost(text: str) -> int:
    return decoded_cost(len(text), width_of(text))


# ── counting, and stopping ───────────────────────────────────────────────────


class _Tally:
    """The running counts, each checked against its limit as it moves."""

    def __init__(self, limits: SafetyLimits) -> None:
        self.limits = limits
        self.decoded = 0
        self.widest = 1
        self.cells = 0
        self.columns = 0
        self.rows = 0
        self.uncompressed: int | None = None
        self.encoding: str | None = None
        self.package: _Package | None = None

    def reset(self) -> None:
        self.decoded = 0
        self.widest = 1
        self.cells = 0
        self.columns = 0
        self.rows = 0

    def check_decoded(self, pending: int = 0) -> None:
        total = self.decoded + pending
        if total > self.limits.max_decoded_string_bytes:
            self.decoded = total
            raise PreflightRefused(
                RefusalCode.DECODED_TOO_LARGE,
                "this file's text would take more memory than one import run "
                "is allowed; split it into smaller files",
                limit=self.limits.max_decoded_string_bytes,
                observed=total,
            )

    def add_decoded(self, cost: int) -> None:
        self.decoded += cost
        self.check_decoded()

    def add_cells(self, count: int) -> None:
        self.cells += count
        if self.cells > self.limits.max_cells:
            raise PreflightRefused(
                RefusalCode.TOO_MANY_CELLS,
                f"this file has more than the {self.limits.max_cells} cells one "
                "import run reads; split it into smaller files",
                limit=self.limits.max_cells,
                observed=self.cells,
            )

    def note_columns(self, count: int) -> None:
        if count > self.columns:
            self.columns = count
        if count > self.limits.max_columns:
            raise PreflightRefused(
                RefusalCode.TOO_MANY_COLUMNS,
                f"this file has a row more than {self.limits.max_columns} columns "
                "wide, which is more than one import run reads",
                limit=self.limits.max_columns,
                observed=count,
            )

    def note_rows(self, count: int) -> None:
        if count > self.rows:
            self.rows = count
        ceiling = self.limits.max_rows
        if ceiling is not None and count > ceiling:
            raise PreflightRefused(
                RefusalCode.TOO_MANY_ROWS,
                f"this file has more than the {ceiling} rows one import run takes",
                limit=ceiling,
                observed=count,
            )

    def result(self, fmt: Format, source_bytes: int, refusal: Refusal | None) -> Preflight:
        found = self.package
        return Preflight(
            format=fmt,
            source_bytes=source_bytes,
            uncompressed_bytes=self.uncompressed,
            decoded_string_bytes=self.decoded,
            widest_character=self.widest,
            cells=self.cells,
            columns=self.columns,
            rows=self.rows,
            encoding=self.encoding,
            refusal=refusal,
            workbook_part=found.workbook if found else None,
            sheet_part=found.sheet if found else None,
            sheet_title=found.title if found else None,
            strings_part=found.strings[0] if found and found.strings else None,
        )


# ── CSV ──────────────────────────────────────────────────────────────────────

#: Bytes decoded at a time. At least four times `MAX_CELL`, so the first chunk
#: always holds the `MAX_CELL` characters the delimiter is sniffed from.
_CHUNK = 256 * 1024

#: How much of a workbook part may go by without the parser reporting
#: anything. No real part has a megabyte between two events.
_MAX_TOKEN = 4 * _CHUNK


def _decodes(raw: bytes, encoding: str) -> bool:
    """Whether the whole file is valid in this encoding, keeping none of it."""
    decoder = codecs.getincrementaldecoder(encoding)("strict")
    try:
        for start in range(0, len(raw), _CHUNK):
            decoder.decode(raw[start : start + _CHUNK], start + _CHUNK >= len(raw))
    except UnicodeDecodeError:
        return False
    return True


def _csv_pass(
    raw: bytes, tally: _Tally, *, encoding: str, errors: str, delimiter: str | None
) -> None:
    """One pass over the file in one encoding, a chunk at a time.

    **The cost is the whole text at the file's widest character**, not a sum
    of lines, because that is what the reader this guards will build: it
    decodes the file into one string. A 63 MiB ASCII file with a single emoji
    in it is a 252 MiB string, and GR-352 measured exactly that. Here the
    emoji widens one chunk and the arithmetic, and nothing else.
    """
    decoder = codecs.getincrementaldecoder(encoding)(errors)
    characters = 0

    def pieces() -> Iterator[str]:
        nonlocal characters
        for start in range(0, len(raw), _CHUNK):
            text = decoder.decode(raw[start : start + _CHUNK], start + _CHUNK >= len(raw))
            if not text:
                continue
            characters += len(text)
            tally.widest = max(tally.widest, width_of(text))
            tally.decoded = decoded_cost(characters, tally.widest)
            tally.check_decoded()
            yield text

    stream = pieces()
    first = next(stream, "")
    chosen = delimiter or sniff_delimiter(first)

    try:
        header = True
        for record in _reader(_lines(chain((first,), stream)), delimiter=chosen):
            tally.add_cells(len(record))
            tally.note_columns(len(record))
            if header:
                header = False
                continue
            # The reader's own rule for what a row is. `count_rows` in
            # `reading.py` is the other copy.
            if any(cell.strip() for cell in record):
                tally.note_rows(tally.rows + 1)
    except PreflightRefused:
        raise
    except ReadRefused as broken:
        raise PreflightRefused(RefusalCode.MALFORMED, str(broken)) from broken


def _lines(pieces: Iterable[str]) -> Iterator[str]:
    """Lines from decoded pieces, on the boundaries `str.splitlines` gives.

    Found without the whole text: the last piece of each chunk is carried,
    because it may be half a line -- or a `\\r` whose `\\n` is in the next
    chunk. A function of its own since GR-352B, so the inspection that reads a
    CSV's head splits lines by the rule this pass counted them with.
    """
    carry = ""
    for text in pieces:
        parts = (carry + text).splitlines(keepends=True)
        carry = parts.pop() if parts else ""
        for line in parts:
            yield _line(line)
        if len(carry) > MAX_CELL:
            _line(carry)
    if carry:
        yield _line(carry)


def _line(line: str) -> str:
    if len(line) > MAX_CELL:
        raise PreflightRefused(
            RefusalCode.LINE_TOO_LONG,
            f"a line is over the {MAX_CELL} character limit; "
            "this is a file in a cell rather than a row",
            limit=MAX_CELL,
            observed=len(line),
        )
    return line


def _survey_csv(raw: bytes, tally: _Tally, delimiter: str | None) -> None:
    """The reader's own encoding order, strictly, then its fallback.

    A refusal met under a strict encoding is only believed once the rest of
    the file is known to be valid in it. Otherwise bytes that happen to form a
    four-byte UTF-8 sequence in a `cp1252` file would be costed as an emoji
    the reader will never see.
    """
    for encoding in ENCODINGS:
        tally.reset()
        try:
            _csv_pass(raw, tally, encoding=encoding, errors="strict", delimiter=delimiter)
        except UnicodeDecodeError:
            continue
        except PreflightRefused:
            if _decodes(raw, encoding):
                tally.encoding = encoding
                raise
            continue
        tally.encoding = encoding
        return
    tally.reset()
    tally.encoding = FALLBACK_ENCODING
    _csv_pass(raw, tally, encoding=FALLBACK_ENCODING, errors="replace", delimiter=delimiter)


# ── XLSX ─────────────────────────────────────────────────────────────────────

_WORKBOOK_PART = "xl/workbook.xml"
_MACRO_PART = "xl/vbaProject.bin"
_CONTENT_TYPES = "[Content_Types].xml"

#: What the content types call a string table. `openpyxl` loads the first
#: part declared with it, whatever that part's root element is.
_STRINGS_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"

#: What the content types may call the workbook part, in the order `openpyxl`
#: looks for them: macro template, template, macro workbook, workbook.
#: `test_preflight_package.py` compares this against `openpyxl`'s own list.
_WORKBOOK_TYPES = (
    "application/vnd.ms-excel.template.macroEnabled.main+xml",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml",
    "application/vnd.ms-excel.sheet.macroEnabled.main+xml",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
)

#: The namespace a sheet's relationship id is written in.
_RELATIONSHIPS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

#: How deep a part's elements may nest. A workbook part nests about ten deep;
#: the scan keeps one name a level, so this is what bounds that.
_MAX_DEPTH = 256
_DIRECTORY_ENTRY = b"PK\x01\x02"

#: The sheet the reader prefers. `reading_xlsx.DATA_SHEET` is the same word;
#: it cannot be imported from there because that module imports this one.
_DATA_SHEET = "Data"

_NOT_A_WORKBOOK = "the file is not a workbook"
_UNREADABLE = "the file could not be read as a workbook"

#: What reading one zip entry can raise that is the file's fault.
_ENTRY_ERRORS = (
    zipfile.BadZipFile,
    zlib.error,
    EOFError,
    OSError,
    RuntimeError,
    NotImplementedError,
    ValueError,
)


class _Stop(Exception):  # noqa: N818 - a signal, not an error
    """This part is not one the scan needs, or it has seen enough of it."""


def _local(name: str) -> str:
    """An element or attribute name without its prefix.

    Namespaces are deliberately not resolved: a part that calls its string
    item `x:si` is counted like one that calls it `si`. Counting something the
    reader would have ignored errs toward refusing, which is the safe side.
    """
    return name.rpartition(":")[2]


def _column(reference: str) -> int:
    """The 1-based column a cell reference such as `AB12` names, or 0."""
    index = 0
    for char in reference:
        if "A" <= char <= "Z":
            index = index * 26 + ord(char) - 64
        elif "a" <= char <= "z":
            index = index * 26 + ord(char) - 96
        else:
            break
        if index > 1 << 24:
            break
    return index


class _Strings:
    """Which shared strings are empty -- one byte each, and nothing else kept.

    The reader calls a row blank when every cell in it is empty, and a cell
    that points at an empty shared string is empty. Counting rows by the
    reader's rule therefore needs this, and only this, about each string.
    """

    def __init__(self) -> None:
        self.present = bytearray()
        self.tables = 0

    def has_text(self, index: str) -> bool:
        # Anything this cannot answer is treated as text: a row counted that
        # the reader would have skipped errs toward refusing.
        if self.tables != 1 or not index.isdigit():
            return True
        position = int(index)
        if position >= len(self.present):
            return True
        return bool(self.present[position])


class _Scanner:
    """`expat` handlers for one part. No tree: nothing is kept but counts."""

    def __init__(
        self, tally: _Tally, strings: _Strings, *, sheet: bool, force: str | None = None
    ) -> None:
        self.tally = tally
        self.strings = strings
        #: True on the pass that reads worksheets, False on the one that
        #: reads string tables and notes which parts are worksheets.
        self.sheet = sheet
        #: What this part *is*, when the package says so. The reader takes its
        #: string table and its sheet from the package's index and reads them
        #: whatever their root element is called, so a part it will read is
        #: scanned as what it will be read as. Without this the root decides,
        #: which is all the pass had until IMPORT-DEF-017.
        self.force = force
        self.kind: str | None = None
        #: The names of the open elements, outermost first. Bounded by
        #: `_MAX_DEPTH`. Kept so a cell is known by where it is: `openpyxl`
        #: reads *every* child of a row as a cell, whatever it is called.
        self.path: list[str] = []
        self.cell_depth = 0
        #: Handler calls so far. `_scan` watches it to notice a token that
        #: never ends.
        self.events = 0
        self.phonetic = 0
        self.in_text = False
        # A logical string: a shared item, or one cell's own text.
        self.in_item = False
        self.characters = 0
        self.width = 1
        self.real = 0
        # A worksheet.
        self.rows_seen = 0
        self.data_rows = 0
        self.row_has_value = False
        self.column = 0
        self.in_cell = False
        self.cell_type = "n"
        self.in_value = False
        self.in_inline = False
        self.index = ""

    def doctype(self, *_: object) -> None:
        # A workbook part declares no document type. One that does could
        # declare entities, and this refuses the file rather than trusting
        # every parser downstream of it to bound their expansion.
        raise PreflightRefused(RefusalCode.MALFORMED, _UNREADABLE)

    def start(self, name: str, attributes: dict[str, str]) -> None:
        self.events += 1
        local = _local(name)
        parent = self.path[-1] if self.path else ""
        if len(self.path) >= _MAX_DEPTH:
            raise PreflightRefused(RefusalCode.MALFORMED, _UNREADABLE)
        self.path.append(local)
        if self.kind is None:
            self.kind = self.force or (local if local in ("sst", "worksheet") else "other")
            if self.kind == "other" or (self.kind == "worksheet") != self.sheet:
                raise _Stop
            if self.kind == "sst":
                self.strings.tables += 1
            return
        if self.kind == "worksheet" and (parent == "row" or local == "c"):
            # A cell is a child of a row, by position and not by name. Asked
            # before anything else, so no name a cell is given -- `rPh`, `row`,
            # `t` -- can make it something other than a cell.
            self.tally.add_cells(1)
            named = _column(attributes.get("r", ""))
            self.column = named or self.column + 1
            self.tally.note_columns(self.column)
            self.cell_type = attributes.get("t", "n")
            self.in_cell = True
            self.cell_depth = len(self.path)
            self.in_value = False
            self.in_inline = False
            self.in_text = False
            self.index = ""
            self._begin_string()
        elif local == "rPh":
            self.phonetic += 1
        elif self.kind == "sst":
            if local == "si":
                self._begin_string()
                self.in_item = True
            elif local == "t" and self.in_item:
                self.in_text = True
        elif local == "row":
            self.row_has_value = False
            self.column = 0
        elif self.in_cell:
            if local == "v":
                self.in_value = True
            elif local == "is":
                self.in_inline = True
            elif local == "t" and self.in_inline:
                self.in_text = True

    def _begin_string(self) -> None:
        self.characters = 0
        self.width = 1
        self.real = 0

    def text(self, data: str) -> None:
        self.events += 1
        width = width_of(data)
        if width > self.tally.widest:
            self.tally.widest = width
        if not (self.in_text or self.in_value):
            # A formula, a header or footer, the space between elements. The
            # reader's parser holds this text too, so it is costed -- without
            # it a single enormous formula would walk around the budget.
            self.tally.add_decoded(len(data) * width)
            return
        self.characters += len(data)
        if width > self.width:
            self.width = width
        if not self.phonetic:
            self.real += len(data)
        if self.in_value and self.cell_type == "s" and len(self.index) < 16:
            self.index += data
        # Checked as the text arrives, not when its element closes, so one
        # enormous string is refused partway through rather than after it.
        self.tally.check_decoded(self.characters * self.width)

    def end(self, name: str) -> None:
        self.events += 1
        local = _local(name)
        depth = len(self.path)
        if self.path:
            self.path.pop()
        if self.in_cell and depth == self.cell_depth:
            self._end_cell()
            return
        if local == "rPh":
            self.phonetic -= 1
        elif local == "t":
            self.in_text = False
        elif self.kind == "sst":
            if local == "si" and self.in_item:
                self.in_item = False
                self.tally.add_decoded(decoded_cost(self.characters, self.width))
                self.strings.present.append(1 if self.real else 0)
        elif local == "v":
            self.in_value = False
        elif local == "is":
            self.in_inline = False
        elif local == "row":
            self.rows_seen += 1
            # The first row is the header, whatever is in it.
            if self.rows_seen > 1 and self.row_has_value:
                self.data_rows += 1
                self.tally.note_rows(self.data_rows)

    def _end_cell(self) -> None:
        self.in_cell = False
        self.in_value = False
        self.in_inline = False
        if self.cell_type == "s":
            # A reference: its digits are text the parser holds, and the
            # string itself was costed when its table was read.
            self.tally.add_decoded(self.characters * self.width)
            has_value = self.strings.has_text(self.index.strip())
        elif self.cell_type in ("inlineStr", "str", "e"):
            # Text the reader keeps as a string of its own.
            self.tally.add_decoded(decoded_cost(self.characters, self.width))
            has_value = self.real > 0
        else:
            self.tally.add_decoded(self.characters * self.width)
            has_value = self.characters > 0
        if has_value:
            self.row_has_value = True


def _scan(archive: zipfile.ZipFile, info: zipfile.ZipInfo, scanner: _Scanner) -> None:
    """Stream one entry through the scanner, a chunk at a time."""
    parser = expat.ParserCreate()
    parser.buffer_text = True
    parser.StartDoctypeDeclHandler = scanner.doctype
    parser.StartElementHandler = scanner.start
    parser.EndElementHandler = scanner.end
    parser.CharacterDataHandler = scanner.text
    stalled = 0
    try:
        # `open` stops at the size the directory declared, so a part cannot
        # yield more than the total already checked against the ceiling.
        with archive.open(info) as part:
            while chunk := part.read(_CHUNK):
                before = scanner.events
                parser.Parse(chunk, False)
                # `expat` hands text over as it arrives and holds everything
                # else -- an attribute value, a comment -- until it closes.
                # Chunks that produce no event at all are one such token
                # growing, and it is refused before it is a string.
                stalled = stalled + len(chunk) if scanner.events == before else 0
                if stalled > _MAX_TOKEN:
                    raise PreflightRefused(RefusalCode.MALFORMED, _UNREADABLE)
        parser.Parse(b"", True)
    except _Stop:
        return
    except PreflightRefused:
        # A `ValueError`, like every refusal here, so it is named before the
        # clause below can mistake it for a broken entry.
        raise
    except (expat.ExpatError, *_ENTRY_ERRORS) as broken:
        if scanner.kind in ("sst", "worksheet"):
            # A part the reader would open, and cannot.
            raise PreflightRefused(RefusalCode.MALFORMED, _UNREADABLE) from broken
        # Anything else is a picture, a binary or a part nobody parses.


class _Attributes:
    """The attributes of every element with one name, from one small part."""

    def __init__(self, wanted: str, ceiling: int) -> None:
        self.wanted = wanted
        self.ceiling = ceiling
        self.found: list[dict[str, str]] = []

    def doctype(self, *_: object) -> None:
        raise _Stop

    def start(self, name: str, attributes: dict[str, str]) -> None:
        if _local(name) != self.wanted:
            return
        if len(self.found) >= self.ceiling:
            raise _Stop
        self.found.append({_local(key): value for key, value in attributes.items()})


def _attributes(
    archive: zipfile.ZipFile, name: str, wanted: str, ceiling: int
) -> list[dict[str, str]]:
    collector = _Attributes(wanted, ceiling)
    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = collector.doctype
    parser.StartElementHandler = collector.start
    try:
        with archive.open(name) as part:
            while chunk := part.read(_CHUNK):
                parser.Parse(chunk, False)
        parser.Parse(b"", True)
    except (_Stop, KeyError, expat.ExpatError, *_ENTRY_ERRORS):
        return []
    return collector.found


# ── the package, resolved as the reader resolves it ──────────────────────────


@dataclass(frozen=True)
class _Package:
    """The parts `openpyxl` will consume, by its own rules.

    Not a guess at them. Each rule below is the one `openpyxl` 3.1 applies,
    including the ones that look like accidents -- the last `sheets` element
    wins, a duplicated relationship id resolves to the later one, a target
    marked external is used as it is written -- because a pass that resolves
    a tidier package than the reader does is scanning a different file.
    """

    #: The workbook part: what the content types call one, or the usual name.
    workbook: str
    #: The part rows will be read from and its sheet's title, or None when
    #: the package gives the reader no worksheet -- in which case it reads
    #: none, and every worksheet-shaped part is counted instead.
    sheet: str | None
    title: str | None
    #: Every part the content types call a string table. The reader loads the
    #: first; all of them are scanned as one, which can only refuse more.
    strings: tuple[str, ...]


class _Outline:
    """A part's top two levels: the root's children, and one kind's children.

    Names are resolved against their namespaces, unlike the scan below: a
    sheet's relationship id is an attribute in a namespace, and a pass that
    read it by its prefix would be told which sheet to scan by whoever chose
    the prefix.
    """

    def __init__(self, inside: str | None, ceiling: int) -> None:
        self.inside = inside
        self.ceiling = ceiling
        self.events = 0
        self.depth = 0
        self.within = False
        #: `(depth, local name, attributes)`, in document order.
        self.found: list[tuple[int, str, dict[str, str]]] = []

    def doctype(self, *_: object) -> None:
        raise PreflightRefused(RefusalCode.MALFORMED, _UNREADABLE)

    def start(self, name: str, attributes: dict[str, str]) -> None:
        self.events += 1
        self.depth += 1
        if self.depth == 2 or (self.depth == 3 and self.within):
            if len(self.found) >= self.ceiling:
                # More entries than a spreadsheet has parts. Stopping here and
                # resolving from what was read would be resolving a different
                # package than the reader, which reads to the end.
                raise PreflightRefused(RefusalCode.MALFORMED, _UNREADABLE)
            local = name.rpartition(" ")[2]
            self.found.append((self.depth, local, attributes))
            if self.depth == 2:
                self.within = local == self.inside

    def text(self, _data: str) -> None:
        self.events += 1

    def end(self, _name: str) -> None:
        self.events += 1
        self.depth -= 1


def _outline(
    archive: zipfile.ZipFile, name: str, ceiling: int, *, inside: str | None = None
) -> list[tuple[int, str, dict[str, str]]] | None:
    """One small part's outline, or None when the reader could not read it either."""
    collector = _Outline(inside, ceiling)
    parser = expat.ParserCreate(namespace_separator=" ")
    parser.buffer_text = True
    parser.StartDoctypeDeclHandler = collector.doctype
    parser.StartElementHandler = collector.start
    parser.EndElementHandler = collector.end
    parser.CharacterDataHandler = collector.text
    stalled = 0
    try:
        with archive.open(name) as part:
            while chunk := part.read(_CHUNK):
                before = collector.events
                parser.Parse(chunk, False)
                stalled = stalled + len(chunk) if collector.events == before else 0
                if stalled > _MAX_TOKEN:
                    raise PreflightRefused(RefusalCode.MALFORMED, _UNREADABLE)
        parser.Parse(b"", True)
    except PreflightRefused:
        raise
    except (KeyError, expat.ExpatError, *_ENTRY_ERRORS):
        return None
    return collector.found


def _relationships(
    archive: zipfile.ZipFile, owner: str, ceiling: int
) -> dict[str, tuple[str, str]]:
    """Relationship id to `(type, target)`, for the part that owns them.

    `openpyxl.packaging.relationship.get_dependents`: a target is relative to
    the owning part's folder unless it starts with a slash, in which case one
    slash is dropped and nothing else is done to it; a target marked external
    is left exactly as written. A later relationship with an id already seen
    replaces the earlier one.
    """
    folder, part = posixpath.split(owner)
    found = _outline(archive, posixpath.join(folder, "_rels", f"{part}.rels"), ceiling)
    resolved: dict[str, tuple[str, str]] = {}
    for _, _, attributes in found or ():
        target = attributes.get("Target", "")
        if attributes.get("TargetMode") != "External":
            if target.startswith("/"):
                target = target[1:]
            else:
                target = posixpath.normpath(posixpath.join(folder, target))
        resolved[attributes.get("Id", "")] = (attributes.get("Type", ""), target)
    return resolved


def _package(archive: zipfile.ZipFile, names: set[str], ceiling: int) -> _Package:
    """Which parts the reader will consume. See `_Package`."""
    declared = [
        attributes
        for depth, local, attributes in _outline(archive, _CONTENT_TYPES, ceiling) or ()
        if depth == 2 and local == "Override"
    ]

    def part(content_type: str) -> str | None:
        for override in declared:
            if override.get("ContentType") == content_type:
                return override.get("PartName", "")[1:]
        return None

    strings = tuple(
        dict.fromkeys(
            name
            for name in (
                override.get("PartName", "")[1:]
                for override in declared
                if override.get("ContentType") == _STRINGS_TYPE
            )
            if name in names
        )
    )
    workbook = next(
        (found for found in map(part, _WORKBOOK_TYPES) if found is not None), _WORKBOOK_PART
    )

    # The sheets: the children, whatever they are called, of the *last*
    # `sheets` element directly under the root.
    entries: list[dict[str, str]] = []
    for depth, local, attributes in _outline(archive, workbook, ceiling, inside="sheets") or ():
        if depth == 2:
            if local == "sheets":
                entries = []
        else:
            entries.append(attributes)

    relationships = _relationships(archive, workbook, ceiling)
    worksheets: list[tuple[str, str]] = []
    for entry in entries:
        # The id in the relationships namespace, or a plain one where there
        # is none: the reader accepts either, and prefers the first.
        link = entry.get(f"{_RELATIONSHIPS} id", entry.get("id", ""))
        if not link or link not in relationships:
            continue
        kind, target = relationships[link]
        if target in names and "chartsheet" not in kind:
            worksheets.append((entry.get("name", ""), target))

    # `Data`, or the first worksheet. `reading_xlsx.read_workbook` chooses the
    # same way, and then checks that it chose the part named here.
    title, sheet = next(
        (found for found in worksheets if found[0] == _DATA_SHEET),
        worksheets[0] if worksheets else (None, None),
    )
    return _Package(workbook=workbook, sheet=sheet, title=title, strings=strings)


def _survey_xlsx(raw: bytes, tally: _Tally) -> None:
    limits = tally.limits
    # Counted in the bytes, before `zipfile` builds an object for each entry.
    # The directory's own count field is not trusted: `zipfile` does not read
    # it either, and walks the directory by its size.
    entries = raw.count(_DIRECTORY_ENTRY)
    if entries > limits.max_archive_entries:
        raise PreflightRefused(
            RefusalCode.TOO_MANY_ENTRIES,
            "this workbook has far more parts than a spreadsheet does, and is not read",
            limit=limits.max_archive_entries,
            observed=entries,
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except _ENTRY_ERRORS as broken:
        raise PreflightRefused(RefusalCode.MALFORMED, _NOT_A_WORKBOOK) from broken
    with archive:
        infos = archive.infolist()
        names = {info.filename for info in infos}
        if _WORKBOOK_PART not in names:
            raise PreflightRefused(RefusalCode.MALFORMED, _NOT_A_WORKBOOK)
        if _MACRO_PART in names:
            raise PreflightRefused(
                RefusalCode.MACROS,
                "a workbook with macros is not read; save it as .xlsx first",
            )
        total = sum(info.file_size for info in infos)
        tally.uncompressed = total
        if total > limits.max_uncompressed_bytes:
            raise PreflightRefused(
                RefusalCode.UNCOMPRESSED_TOO_LARGE,
                f"this workbook would expand to {total} bytes, over the "
                f"{limits.max_uncompressed_bytes} limit",
                limit=limits.max_uncompressed_bytes,
                observed=total,
            )

        # The parts the reader will read, found the way the reader finds
        # them, and scanned as what it will read them as -- whatever their
        # root element is called. IMPORT-DEF-017.
        package = _package(archive, names, limits.max_archive_entries)
        tally.package = package

        # And, beside those, every part that *is* a string table by its root,
        # wherever it is kept. Neither rule alone is enough: the index names
        # what will be read, the root catches what an index left out, and a
        # part caught by both is scanned once.
        strings = _Strings()
        worksheets: list[zipfile.ZipInfo] = []
        for info in infos:
            if info.is_dir() or not info.file_size:
                continue
            named = info.filename in package.strings
            # Emptiness is asked of the table the reader will load, when the
            # package names one; any other table is costed and not consulted.
            consulted = not package.strings or info.filename == package.strings[0]
            scanner = _Scanner(
                tally,
                strings if consulted else _Strings(),
                sheet=False,
                force="sst" if named else None,
            )
            _scan(archive, info, scanner)
            if scanner.kind == "worksheet":
                worksheets.append(info)

        if package.sheet is not None:
            # Exactly the sheet the reader reads -- a workbook is not refused
            # for a lookup sheet nobody opens.
            _scan(
                archive,
                archive.getinfo(package.sheet),
                _Scanner(tally, strings, sheet=True, force="worksheet"),
            )
        else:
            # The package gives the reader no worksheet, so it will read none.
            # Every part shaped like one is counted, which can only refuse more.
            for info in worksheets:
                _scan(archive, info, _Scanner(tally, strings, sheet=True))


# ── the two ways in ──────────────────────────────────────────────────────────


def survey(
    raw: bytes,
    fmt: Format,
    limits: SafetyLimits = PROVISIONAL_LIMITS,
    *,
    delimiter: str | None = None,
) -> Preflight:
    """What the source contains and whether it is safe. Never raises a refusal.

    `delimiter` is for a CSV whose delimiter is already recorded on its run;
    without it the header is sniffed exactly as the reader sniffs it.
    """
    tally = _Tally(limits)
    refusal: Refusal | None = None
    try:
        if len(raw) > limits.max_source_bytes:
            raise PreflightRefused(
                RefusalCode.SOURCE_TOO_LARGE,
                "this file is larger than one import run reads",
                limit=limits.max_source_bytes,
                observed=len(raw),
            )
        if fmt is Format.XLSX:
            _survey_xlsx(raw, tally)
        elif fmt is Format.CSV:
            _survey_csv(raw, tally, delimiter)
    except PreflightRefused as refused:
        refusal = Refusal(
            code=refused.code,
            message=str(refused),
            limit=refused.limit,
            observed=refused.observed,
        )
    return tally.result(fmt, len(raw), refusal)


def preflight(
    raw: bytes,
    fmt: Format,
    limits: SafetyLimits = PROVISIONAL_LIMITS,
    *,
    delimiter: str | None = None,
) -> Preflight:
    """`survey`, raising `PreflightRefused` when the source is not safe.

    The call every path makes before it hands a source to a reader.
    """
    found = survey(raw, fmt, limits, delimiter=delimiter)
    if found.refusal is not None:
        raise PreflightRefused(
            found.refusal.code,
            found.refusal.message,
            limit=found.refusal.limit,
            observed=found.refusal.observed,
        )
    return found


__all__ = [
    "ENVELOPE_CODES",
    "MAX_ARCHIVE_ENTRIES",
    "MAX_CELLS",
    "MAX_COLUMNS",
    "MAX_DECODED_STRING_BYTES",
    "MAX_SOURCE_BYTES",
    "MAX_UNCOMPRESSED_BYTES",
    "PROVISIONAL_LIMITS",
    "STRING_OVERHEAD",
    "Preflight",
    "PreflightRefused",
    "Refusal",
    "RefusalCode",
    "SafetyLimits",
    "decoded_cost",
    "preflight",
    "string_cost",
    "survey",
    "width_of",
]
