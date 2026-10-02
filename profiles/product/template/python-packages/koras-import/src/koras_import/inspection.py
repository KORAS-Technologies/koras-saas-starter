"""What a file's head looks like, without reading the file into memory.

A route that shows somebody two hundred rows and offers a mapping needs the
header, those rows, and whether the file is longer than the target takes. Until
GR-352B it got them from the readers the dry run uses -- `read_workbook`, which
has `openpyxl` build the workbook's whole shared-string table, and `decode`,
which makes one string of the whole CSV -- and threw away everything past the
two hundredth row. GR-352 measured that at 989 MiB resident for a workbook
near the limits and 126 seconds for a wide one, on the API's event loop.

This module answers the same three questions by streaming.

**It is not what a dry run or a commit reads through.** What is validated
and what is written comes from `streaming.open_rows`, which reads every row;
this answers only what the mapping page draws. Both are held to
`reading.py` and `reading_xlsx.py`, which say what a file's rows are: this
module on the header, the first rows as text and the count, by
`test_inspection.py`, and the stream on every row, by `test_streaming.py`.
The stream is built from this module's sheet walk -- `_Sheet`, `_Strings`,
`_Styles` -- asked for every row instead of a sample, so a change to one of
those is a change to what a commit writes. Until GR-352C the dry run and the
commit called the two readers themselves.

**The safety pass runs first, inside `inspect_source`.** A caller chooses the
envelope; it cannot choose to have none, which is the arrangement
`read_workbook` already has. Nothing here runs on a source `preflight` refused.

**A workbook's strings are resolved selectively.** The string table is
streamed twice and never held: once keeping four bytes an item, its length,
which is what decides whether a row is blank and what a sample would cost; and
once more, after the sheet has said which strings the header and the sample
actually point at, keeping those and stopping at the last of them. Nothing
assumes the first rows use the first strings.

**What a workbook cell becomes** is `cell_text`'s rule, applied to the value
`openpyxl` would have produced, by `openpyxl`'s own date functions -- one rule,
not a copy of it. Those functions are imported; `load_workbook` is not called.
Only the header and the sample are converted. A cell past the sample is asked
two things alone: whether it is empty, and whether it is a file in a cell.

**Two places this is deliberately not the canonical reader**, each of them a
malformed workbook and none of them a file a spreadsheet writes:

- A part `openpyxl` loads eagerly and the mapping page never needs -- the
  theme, the document properties, a broken stylesheet's unused corners -- is
  not opened, so a workbook broken only there is inspected here and refused by
  the dry run.
- A numeric cell past the sample that is not a number is not noticed here.

**Which parts are read is not decided here.** The safety pass resolves the
package the way `openpyxl` does and says which part is the sheet and which the
string table; this module reads those and no others. It had its own, narrower
answer for a day, while the pass and the reader disagreed -- IMPORT-DEF-017 --
and a third opinion about which part is the sheet is one more than is safe.

**The sample has a budget of its own.** Two hundred rows is the contract, and
`MAX_SAMPLE_CHARACTERS` is what keeps it from being a contract for memory: one
32 KiB string named by every cell of two hundred wide rows is 1.6 GiB of
response from 32 KiB of file. The number is provisional. See
`docs/features/data-import/bounded-inspection.md`.
"""

from __future__ import annotations

import codecs
import zipfile
from array import array
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import chain
from typing import Any
from xml.parsers import expat

from .reading import (
    FALLBACK_ENCODING,
    MAX_CELL,
    Header,
    ReadRefused,
    Row,
    _reader,
    header_from,
    row_from,
    sniff_delimiter,
)
from .reading_xlsx import cell_text, cell_too_long, template_identity
from .reading_xlsx import inspect as open_workbook
from .safety import (
    _CHUNK,
    _ENTRY_ERRORS,
    _MAX_TOKEN,
    _UNREADABLE,
    PROVISIONAL_LIMITS,
    Preflight,
    SafetyLimits,
    _attributes,
    _column,
    _lines,
    _Stop,
    preflight,
)
from .targets import Format

#: PROVISIONAL (GR-352, pending NFR ratification). Characters the sample may
#: carry, counting each row's column names with its cells because that is what
#: the response repeats. Four mebibytes of characters is at most sixteen of
#: response; an ordinary file's two hundred rows are a few hundred kibibytes.
#: A sample that would pass it stops short -- the rows before it are still a
#: head of the file -- and says so in `sample_cut`.
MAX_SAMPLE_CHARACTERS = 4 * 1024 * 1024

#: What a cell format index may reach. Excel's own limit is 65,490; a
#: stylesheet declaring more is not one, and is not walked to its end.
MAX_STYLES = 65_536

#: Excel's last column, `XFD`. A cell claiming to be further right is not
#: placed, so one reference cannot make a row sixteen million cells wide.
MAX_WIDTH = 16_384

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_ROW = f"{_MAIN} row"
_VALUE = f"{_MAIN} v"
_INLINE = f"{_MAIN} is"
_ITEM = f"{_MAIN} si"

_STYLES_PART = "xl/styles.xml"

_NO_COLUMNS = "the file's first row names no columns"
_EMPTY = "the file is empty"


@dataclass(frozen=True)
class Inspection:
    """A source's head: enough to offer a mapping, and nothing past it."""

    format: Format
    header: Header
    #: Up to `sample` rows, in order, as the reader would have produced them.
    rows: tuple[Row, ...]
    #: Data rows by the reader's rule, counted no further than `ceiling + 1`.
    rows_seen: int
    #: What the CSV was split on; `","` for a workbook, as the store records it.
    delimiter: str
    #: What the CSV decoded under; `"utf-8"` for a workbook.
    encoding: str
    #: True when no strict encoding fitted a CSV. `reading.Decoded.replaced`.
    replaced: bool
    #: The workbook sheet that was read; None for a CSV.
    sheet: str | None
    #: The template identity a workbook carried; None for a CSV.
    identity: str | None
    #: True when the sample stopped short of `sample` rows that were there,
    #: because the next one would have passed the sample's budget.
    sample_cut: bool
    #: What the safety pass counted before any of this ran.
    preflight: Preflight
    #: The ceiling the count stopped past. Kept so `over_ceiling` cannot be
    #: asked against a different number than the one the count used.
    ceiling: int

    @property
    def over_ceiling(self) -> bool:
        return self.rows_seen > self.ceiling


# ── the sample ───────────────────────────────────────────────────────────────


class _Budget:
    """How many rows the sample has, and how many characters they cost."""

    def __init__(self, sample: int, characters: int) -> None:
        self.wanted = max(0, sample)
        self.characters = characters
        self.used = 0
        self.taken = 0
        self.cut = False

    @property
    def open(self) -> bool:
        return self.taken < self.wanted and not self.cut

    def take(self, cost: int) -> bool:
        """Whether a row of that cost joins the sample. Closes on the first no."""
        if not self.open:
            return False
        if self.used + cost > self.characters:
            self.cut = True
            return False
        self.used += cost
        self.taken += 1
        return True


# ── CSV ──────────────────────────────────────────────────────────────────────


def _pieces(raw: bytes, encoding: str, errors: str) -> Iterator[str]:
    """The file as text, a chunk at a time. No string the size of the file."""
    decoder = codecs.getincrementaldecoder(encoding)(errors)
    for start in range(0, len(raw), _CHUNK):
        text = decoder.decode(raw[start : start + _CHUNK], start + _CHUNK >= len(raw))
        if text:
            yield text


def _inspect_csv(
    raw: bytes, checked: Preflight, *, sample: int, ceiling: int, budget: int
) -> Inspection:
    # The safety pass has already decided the encoding, by the reader's own
    # order and over the whole file -- a head that happens to be valid UTF-8
    # says nothing about byte forty million.
    encoding = checked.encoding or FALLBACK_ENCODING
    replaced = encoding == FALLBACK_ENCODING
    pieces = _pieces(raw, encoding, "replace" if replaced else "strict")
    first = next(pieces, "")
    delimiter = sniff_delimiter(first)
    reader = _reader(_lines(chain((first,), pieces)), delimiter=delimiter)
    try:
        header = header_from(next(reader))
    except StopIteration:
        raise ReadRefused(_EMPTY) from None

    taking = _Budget(sample, budget)
    names = sum(len(name) for name in header.columns)
    rows: list[Row] = []
    # `read_rows`: the same records, the same numbering, the same idea of a
    # blank row. The walk ends when the sample is settled, and the generator
    # is simply not asked again -- so what is decoded here is the head.
    if taking.open:
        for number, record in enumerate(reader, start=2):
            if not any(cell.strip() for cell in record):
                continue
            row = row_from(number, record, header)
            if taking.take(names + sum(len(cell) for cell in row.cells.values())):
                rows.append(row)
            if not taking.open:
                break
    return Inspection(
        format=Format.CSV,
        header=header,
        rows=tuple(rows),
        # `count_rows`, without a second walk. The safety pass counted every
        # row of the file a moment ago, through this same reader and by this
        # same rule -- the header is not a row and a blank line is not one --
        # so its count, held to one past the ceiling, is the reader's own.
        rows_seen=min(checked.rows, ceiling + 1),
        delimiter=delimiter,
        encoding=encoding,
        replaced=replaced,
        sheet=None,
        identity=None,
        sample_cut=taking.cut,
        preflight=checked,
        ceiling=ceiling,
    )


# ── XLSX: streaming one part ─────────────────────────────────────────────────


def _local(name: str) -> str:
    """An element name without its namespace, as this module's parser gives it."""
    return name.rpartition(" ")[2]


def _no_doctype(*_: object) -> None:
    raise ReadRefused(_UNREADABLE)


def _stream(archive: zipfile.ZipFile, name: str, handler: Any) -> None:  # noqa: ANN401
    """One part through one handler, a chunk at a time, with no tree built.

    Namespaces are resolved here, unlike in the safety pass: that pass errs
    toward counting and this one has to agree with a reader that matches a
    row by its full name.
    """
    for _ in _feed(archive, name, handler):
        pass


def _feed(archive: zipfile.ZipFile, name: str, handler: Any) -> Iterator[None]:  # noqa: ANN401
    """`_stream`, handing control back after every chunk.

    What lets a caller take what the handler has gathered so far instead of
    waiting for the whole part: the worker's reader drains a sheet's rows
    between chunks, so the rows of a worksheet are never all held at once.
    GR-352C, `streaming.py`.
    """
    parser = expat.ParserCreate(namespace_separator=" ")
    parser.buffer_text = True
    parser.StartDoctypeDeclHandler = _no_doctype
    parser.StartElementHandler = handler.start
    parser.EndElementHandler = handler.end
    parser.CharacterDataHandler = handler.text
    stalled = 0
    try:
        with archive.open(name) as part:
            while chunk := part.read(_CHUNK):
                before = handler.events
                parser.Parse(chunk, False)
                # The safety pass's own guard against a token that never ends.
                stalled = stalled + len(chunk) if handler.events == before else 0
                if stalled > _MAX_TOKEN:
                    raise ReadRefused(_UNREADABLE)
                yield
        parser.Parse(b"", True)
    except _Stop:
        return
    except ReadRefused:
        # A `ValueError`, so it is named before the clause below.
        raise
    except (KeyError, IndexError, OverflowError, expat.ExpatError, *_ENTRY_ERRORS) as broken:
        raise ReadRefused(_UNREADABLE) from broken


class _Text:
    """The text of a string item or an inline string, as `openpyxl` joins it.

    A plain `t`, then each run's `t`. Phonetic runs are a third kind of child
    and are left out, which is why depth is tracked rather than every `t`
    collected.
    """

    def __init__(self) -> None:
        self.reset(0)

    def reset(self, depth: int) -> None:
        self.depth = depth
        self.zone = 0
        self.child = ""
        self.count = 0
        self.plain: list[str] = []
        self.runs: list[str] = []

    def start(self, depth: int, local: str) -> None:
        below = depth - self.depth
        if below == 1:
            self.child = local
            if local == "t":
                self.zone = 1
        elif below == 2 and local == "t" and self.child == "r":
            self.zone = 2

    def end(self, depth: int) -> None:
        if self.zone and depth - self.depth == self.zone:
            self.zone = 0

    def text(self, data: str) -> None:
        if not self.zone:
            return
        self.count += len(data)
        # Counted to its end and kept only while it could still be a cell.
        if self.count <= MAX_CELL:
            (self.plain if self.zone == 1 else self.runs).append(data)

    def content(self) -> str:
        return "".join(self.plain) + "".join(self.runs)


class _Strings:
    """The string table, streamed: every item's length, or a few items' text.

    With `wanted` None this measures. Four bytes an item are kept -- its
    length -- because that is what the sheet pass needs of a string it will
    not show: whether the cell is empty, whether it is a file in a cell, and
    what it would cost a sample. With `wanted` set this keeps the text of
    those items alone and stops at the last of them.

    With `keep` it measures and keeps every item as well, in `texts`. That is
    the worker's: a dry run reads every row, so it needs every string, held
    once each -- which the safety pass has already bounded, because the
    decoded-string budget is a sum over exactly these items.
    """

    def __init__(self, wanted: frozenset[int] | None = None, *, keep: bool = False) -> None:
        self.wanted = wanted
        self.keep = keep
        self.texts: list[str] = []
        self.last = max(wanted) if wanted else -1
        self.events = 0
        self.depth = 0
        self.open = False
        self.index = -1
        self.item = _Text()
        self.lengths = array("I")
        #: The real length of an item over `MAX_CELL`, for the refusal's sentence.
        self.oversize: dict[int, int] = {}
        self.found: dict[int, str] = {}

    def start(self, name: str, _attributes: dict[str, str]) -> None:
        self.events += 1
        self.depth += 1
        if self.open:
            self.item.start(self.depth, _local(name))
        elif name == _ITEM:
            self.open = True
            self.index += 1
            self.item.reset(self.depth)

    def text(self, data: str) -> None:
        self.events += 1
        if self.open and (self.wanted is None or self.index in self.wanted):
            self.item.text(data)

    def end(self, _name: str) -> None:
        self.events += 1
        if self.open:
            if self.depth == self.item.depth:
                self.open = False
                self._close()
            else:
                self.item.end(self.depth)
        self.depth -= 1

    def _close(self) -> None:
        if self.wanted is None:
            if self.item.count > MAX_CELL:
                # Its length before `x005F_` is removed, which is the one
                # place this can differ from the reader: a string over the
                # limit only until its escapes are taken out.
                self.lengths.append(MAX_CELL + 1)
                self.oversize[self.index] = self.item.count
                if self.keep:
                    # Never shown: `position` refuses a cell that names it.
                    self.texts.append("")
            else:
                text = _unescaped(self.item.content())
                self.lengths.append(len(text))
                if self.keep:
                    self.texts.append(text)
            return
        if self.index in self.wanted:
            self.found[self.index] = _unescaped(self.item.content())
        if self.index >= self.last:
            raise _Stop

    def position(self, reference: str) -> int:
        """The item a cell's value names, by the list rule the reader applied."""
        index = int(reference)
        if index < 0:
            index += len(self.lengths)
        if not 0 <= index < len(self.lengths):
            raise ReadRefused(_UNREADABLE)
        if index in self.oversize:
            raise cell_too_long(self.oversize[index])
        return index


def _unescaped(text: str) -> str:
    # `openpyxl.reader.strings.read_string_table`, for shared strings alone.
    return text.replace("x005F_", "") if "x005F_" in text else text


class _Styles:
    """Which cell formats are dates, and nothing else of the stylesheet.

    Two bits a format are kept, decided as each number format goes by, so a
    stylesheet of enormous format codes is not a dictionary of them.
    """

    def __init__(self) -> None:
        self.events = 0
        self.depth = 0
        self.formats = 0
        self.xfs = 0
        self.custom: dict[int, int] = {}
        self.styles: list[int] = []

    def start(self, name: str, attributes: dict[str, str]) -> None:
        self.events += 1
        self.depth += 1
        local = _local(name)
        if local == "numFmts":
            self.formats = self.depth
        elif local == "cellXfs":
            self.xfs = self.depth
        elif local == "numFmt" and self.formats and self.depth == self.formats + 1:
            if len(self.custom) >= MAX_STYLES:
                raise ReadRefused(_UNREADABLE)
            self.custom[int(attributes["numFmtId"])] = _kind(attributes.get("formatCode"))
        elif local == "xf" and self.xfs and self.depth == self.xfs + 1:
            if len(self.styles) >= MAX_STYLES:
                raise ReadRefused(_UNREADABLE)
            self.styles.append(int(attributes.get("numFmtId", 0)))

    def text(self, _data: str) -> None:
        self.events += 1

    def end(self, _name: str) -> None:
        self.events += 1
        if self.depth == self.formats:
            self.formats = 0
        elif self.depth == self.xfs:
            self.xfs = 0
        self.depth -= 1

    def kinds(self) -> dict[int, int]:
        """Cell format index to 1 for a date, 3 for a duration. Others absent."""
        from openpyxl.styles.numbers import BUILTIN_FORMATS

        found: dict[int, int] = {}
        for index, number in enumerate(self.styles):
            kind = self.custom[number] if number in self.custom else _kind(
                BUILTIN_FORMATS.get(number)
            )
            if kind:
                found[index] = kind
        return found


def _kind(code: str | None) -> int:
    from openpyxl.styles.numbers import is_date_format, is_timedelta_format

    if not is_date_format(code):
        return 0
    return 3 if is_timedelta_format(code) else 1


# ── XLSX: the sheet ──────────────────────────────────────────────────────────

#: A captured cell: its text, or the index of the shared string it names.
_Cell = str | int


class _Sheet:
    """The header, the sample and the count, from one walk of one worksheet.

    Rows are taken as the reader takes them: a row is its number, a gap before
    row one means the first row is empty, a row out of order is dropped, and a
    row's width is its last cell's column. Cells are converted only while a row
    could still join the header or the sample; after that a cell is asked
    whether it is empty and whether it is a file, and nothing of it is kept.
    """

    def __init__(
        self,
        strings: _Strings,
        dates: dict[int, int],
        epoch: Any,  # noqa: ANN401 - a `datetime`, as `openpyxl` names its epochs
        taking: _Budget,
        ceiling: int,
    ) -> None:
        self.strings = strings
        self.dates = dates
        self.epoch = epoch
        self.taking = taking
        self.ceiling = ceiling
        self.events = 0
        self.depth = 0
        # What the walk produces.
        self.header: list[_Cell] | None = None
        self.header_cost = 0
        self.rows: list[tuple[int, list[_Cell]]] = []
        self.seen = 0
        # The row being read. `named` is the parser's row number, `expected`
        # the next one the reader would accept.
        self.row = 0
        self.named = 0
        self.expected = 1
        self.capture = True
        self.cells: list[tuple[int, _Cell]] = []
        self.filled = 0
        self.column = 0
        # The cell being read.
        self.kind = "n"
        self.style = 0
        self.zone = 0
        self.has_value = False
        self.has_inline = False
        self.value: list[str] = []
        self.value_count = 0
        self.inline = _Text()

    # ── parser events ────────────────────────────────────────────────────

    def start(self, name: str, attributes: dict[str, str]) -> None:
        self.events += 1
        self.depth += 1
        if not self.row:
            if name == _ROW:
                self._begin_row(attributes.get("r"))
            return
        below = self.depth - self.row
        if below == 1:
            self._begin_cell(attributes)
        elif below == 2:
            if name == _VALUE and not self.has_value:
                self.has_value = True
                self.zone = 1
            elif name == _INLINE and not self.has_inline:
                self.has_inline = True
                self.zone = 2
                self.inline.reset(self.depth)
        elif self.zone == 2:
            self.inline.start(self.depth, _local(name))

    def text(self, data: str) -> None:
        self.events += 1
        if self.zone == 1 and self.depth == self.row + 2:
            self.value_count += len(data)
            if self.value_count <= MAX_CELL:
                self.value.append(data)
        elif self.zone == 2:
            self.inline.text(data)

    def end(self, _name: str) -> None:
        self.events += 1
        if self.row:
            below = self.depth - self.row
            if below == 0:
                self.row = 0
                self._end_row()
            elif below == 1:
                self._end_cell()
            elif below == 2:
                self.zone = 0
            elif self.zone == 2:
                self.inline.end(self.depth)
        self.depth -= 1

    # ── rows ─────────────────────────────────────────────────────────────

    def _begin_row(self, reference: str | None) -> None:
        self.row = self.depth
        if reference is None:
            self.named += 1
        else:
            try:
                self.named = int(reference)
            except ValueError:
                number = float(reference)
                if not number.is_integer():
                    raise
                self.named = int(number)
        self.capture = self.header is None or self.taking.open
        self.cells = []
        self.filled = 0
        self.column = 0

    def _end_row(self) -> None:
        number = self.named
        if number < self.expected:
            return
        self.expected = number + 1
        if self.header is None:
            # The reader's first row is row one. A sheet that starts lower
            # down has an empty one above it.
            cells = self._placed() if number == 1 else []
            if not cells:
                raise ReadRefused(_NO_COLUMNS)
            self.header = cells
            self.header_cost = sum(self._length(cell) for cell in cells) + 16 * len(cells)
            return
        cells = self._placed() if self.capture else []
        if not (cells or (not self.capture and 0 < self.filled <= self.column)):
            return
        self.seen += 1
        if self.seen > self.ceiling:
            raise _Stop
        if self.capture and self.taking.take(
            self.header_cost + sum(self._length(cell) for cell in cells)
        ):
            self.rows.append((number, cells))

    def _placed(self) -> list[_Cell]:
        """The row as the reader lays it out, with its trailing empties gone."""
        width = self.column
        if not self.cells or width < 1:
            return []
        if width > MAX_WIDTH:
            raise ReadRefused(_UNREADABLE)
        values: list[_Cell] = [""] * width
        for column, value in self.cells:
            if 1 <= column <= width:
                values[column - 1] = value
        while values and not self._length(values[-1]):
            values.pop()
        return values

    def _length(self, cell: _Cell) -> int:
        return len(cell) if isinstance(cell, str) else self.strings.lengths[cell]

    # ── cells ────────────────────────────────────────────────────────────

    def _begin_cell(self, attributes: dict[str, str]) -> None:
        named = _column(attributes.get("r", ""))
        self.column = named or self.column + 1
        self.kind = attributes.get("t", "n")
        self.style = int(attributes.get("s") or 0)
        self.zone = 0
        self.has_value = False
        self.has_inline = False
        self.value = []
        self.value_count = 0

    def _end_cell(self) -> None:
        self.zone = 0
        if self.capture:
            self.cells.append((self.column, self._converted()))
        elif self._has_text() and (not self.filled or self.column < self.filled):
            # The leftmost is all a blank-row check needs: the row has a value
            # if any filled cell is inside the width its last cell gives it.
            self.filled = self.column

    def _converted(self) -> _Cell:
        """A header or sample cell: `cell_text` of what `openpyxl` would give."""
        if self.kind == "inlineStr":
            if not self.has_inline:
                return ""
            if self.inline.count > MAX_CELL:
                raise cell_too_long(self.inline.count)
            return self.inline.content()
        if not self.value_count:
            return ""
        if self.kind == "s":
            return self.strings.position("".join(self.value))
        if self.value_count > MAX_CELL:
            if self.kind in ("n", "b", "d"):
                raise ReadRefused(_UNREADABLE)
            raise cell_too_long(self.value_count)
        text = "".join(self.value)
        if self.kind == "n":
            return cell_text(self._number(text))
        if self.kind == "b":
            return cell_text(bool(int(text)))
        if self.kind == "d":
            from openpyxl.utils.datetime import from_ISO8601

            return cell_text(from_ISO8601(text))  # type: ignore[no-untyped-call]
        # A cached formula string, an error, or a type nobody defined: text.
        return text

    def _number(self, text: str) -> Any:  # noqa: ANN401 - a number, or the date it stands for
        value: int | float = float(text) if "." in text or "E" in text or "e" in text else int(text)
        kind = self.dates.get(self.style, 0)
        if not kind:
            return value
        from openpyxl.utils.datetime import from_excel

        try:
            return from_excel(value, self.epoch, timedelta=kind == 3)
        except (OverflowError, ValueError):
            return "#VALUE!"

    def _has_text(self) -> bool:
        """A cell past the sample: is it empty, and is it a file in a cell."""
        if self.kind == "inlineStr":
            # Asked of this cell's own inline string, or of none: `inline` is
            # reused, so without the first test it would still hold the last
            # cell's text.
            if not self.has_inline:
                return False
            if self.inline.count > MAX_CELL:
                raise cell_too_long(self.inline.count)
            return self.inline.count > 0
        if not self.value_count:
            return False
        if self.kind == "s":
            return self.strings.lengths[self.strings.position("".join(self.value))] > 0
        if self.value_count > MAX_CELL and self.kind not in ("n", "b", "d"):
            raise cell_too_long(self.value_count)
        return True


# ── XLSX: the workbook ───────────────────────────────────────────────────────


def _epoch(archive: zipfile.ZipFile, workbook: str) -> Any:  # noqa: ANN401 - a `datetime`
    from openpyxl.utils.datetime import MAC_EPOCH, WINDOWS_EPOCH

    for properties in _attributes(archive, workbook, "workbookPr", 2):
        if properties.get("date1904", "0") not in ("", "0", "f", "false"):
            return MAC_EPOCH
    return WINDOWS_EPOCH


def _inspect_xlsx(
    raw: bytes,
    checked: Preflight,
    limits: SafetyLimits,
    *,
    sample: int,
    ceiling: int,
    budget: int,
) -> Inspection:
    # The parts, from the pass that scanned them. A package that gives the
    # reader no worksheet gives the inspection none either.
    part, title, strings_part = checked.sheet_part, checked.sheet_title, checked.strings_part
    if part is None or title is None or checked.workbook_part is None:
        raise ReadRefused(_UNREADABLE)
    archive = open_workbook(raw)
    with archive:
        identity = template_identity(archive)

        styles = _Styles()
        if _STYLES_PART in archive.namelist():
            _stream(archive, _STYLES_PART, styles)

        measured = _Strings()
        if strings_part is not None:
            _stream(archive, strings_part, measured)

        taking = _Budget(sample, budget)
        sheet = _Sheet(
            measured, styles.kinds(), _epoch(archive, checked.workbook_part), taking, ceiling
        )
        _stream(archive, part, sheet)
        if sheet.header is None:
            raise ReadRefused(_EMPTY)

        # Only now is it known which strings the page will show. They are a
        # second walk of the table, which stops at the last one wanted.
        wanted = frozenset(
            cell
            for cells in chain((sheet.header,), (cells for _, cells in sheet.rows))
            for cell in cells
            if isinstance(cell, int)
        )
        text: dict[int, str] = {}
        if wanted and strings_part is not None:
            resolved = _Strings(wanted)
            _stream(archive, strings_part, resolved)
            text = resolved.found

    def shown(cells: list[_Cell]) -> list[str]:
        return [cell if isinstance(cell, str) else text[cell] for cell in cells]

    header = header_from(shown(sheet.header))
    return Inspection(
        format=Format.XLSX,
        header=header,
        rows=tuple(row_from(number, shown(cells), header) for number, cells in sheet.rows),
        rows_seen=sheet.seen,
        delimiter=",",
        encoding="utf-8",
        replaced=False,
        sheet=title,
        identity=identity,
        sample_cut=taking.cut,
        preflight=checked,
        ceiling=ceiling,
    )


# ── the way in ───────────────────────────────────────────────────────────────


def inspect_source(
    raw: bytes,
    fmt: Format,
    limits: SafetyLimits = PROVISIONAL_LIMITS,
    *,
    sample: int,
    ceiling: int,
    sample_budget: int = MAX_SAMPLE_CHARACTERS,
) -> Inspection:
    """The header, up to `sample` rows, and a count that stops past `ceiling`.

    **The safety pass is inside this function**, ahead of everything else it
    does, so there is no way to inspect a source the envelope refuses. It
    reads the whole file, in bounded memory, and that is deliberate: a file
    over the row ceiling *and* outside the envelope is answered as outside
    the envelope, as it was before this module existed. What stops early is
    the inspection that follows it.

    `sample=0` asks for the header and the count alone, which is what a route
    that only checks a mapping needs.
    """
    if fmt not in (Format.CSV, Format.XLSX):
        raise ReadRefused(f"{fmt.value} files are not read in this release")
    checked = preflight(raw, fmt, limits)
    if fmt is Format.XLSX:
        return _inspect_xlsx(
            raw, checked, limits, sample=sample, ceiling=ceiling, budget=sample_budget
        )
    return _inspect_csv(raw, checked, sample=sample, ceiling=ceiling, budget=sample_budget)


__all__ = [
    "MAX_SAMPLE_CHARACTERS",
    "Inspection",
    "inspect_source",
]
