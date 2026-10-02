"""Every row of a file, one at a time: what a dry run and a commit read.

Until GR-352C the worker read a file the way `reading.py` and
`reading_xlsx.py` had always offered it: all of it, into a list, and then went
through the list. A CSV was the uploaded bytes, the whole file as one string,
that string again as a list of lines, and every row as a dictionary -- four
copies of one file. A workbook went through `openpyxl`, which GR-352C measured
building things nothing here asks for and nothing in the safety pass counts:
every merged range, hyperlink and data validation of the sheet, the whole
stylesheet as a tree, and a walk of every *other* sheet to its end to learn
its dimensions. A 0.8 MiB workbook of four million merged ranges, inside every
limit, took a worker to 2.6 GiB.

This module is the reader the worker uses instead. It yields `Row` after
`Row`, and what it holds is what the safety pass has already bounded.

**A CSV** is decoded 256 KiB at a time in the encoding the safety pass settled
on, split into lines on `str.splitlines` boundaries, and put through the same
`csv` wrapper, `header_from` and `row_from` as before. No string the size of
the file exists.

**A workbook** is read with `zipfile` and `expat`, by the machinery the
bounded inspection of GR-352B was built from and proved against `openpyxl` --
`inspection._Sheet`, with nothing held back for a sample. Three parts are
opened and no others: the string table and the sheet the safety pass scanned
and named, and the stylesheet, streamed for which formats are dates. A merged
range, a hyperlink, a validation, a second sheet, a theme, a defined name: none
is parsed into anything, because nothing here reads the element it is in.
`load_workbook` is not called. IMPORT-GAP-020 and IMPORT-GAP-015 are closed by
that, rather than by counting what `openpyxl` would have built.

**A shared string is held once and named by index** until a row is built from
it, and it is cleaned once, when the table is loaded, rather than once for
every cell that names it. That is IMPORT-DEF-016 in the reader: a string the
safety pass costed once is one string here however many cells point at it.

**The safety pass is inside `open_rows`**, ahead of everything else, by the
arrangement `read_workbook` and `inspect_source` already have. A caller chooses
the envelope and cannot choose to have none.

**It can be told to stop.** `watch` is called between chunks and every few
hundred rows; it raises, and the read ends there. That is what makes a time
limit on an import something more than a wish. See `budget.py`.

**Where this is deliberately not `read_workbook`.** `read_workbook` stays in
the package as the description of what a workbook's rows *are*, and
`test_streaming.py` holds this reader to it file by file. Three differences
are intended, each a malformed workbook and none a file a spreadsheet writes:
a part this reader never opens may be broken without the workbook being
refused; a shared string longer than a cell may be *only until* its escaped
underscores are removed is refused here; and a stylesheet declaring more
formats than a spreadsheet can have is refused rather than loaded.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from .inspection import (
    _EMPTY,
    _STYLES_PART,
    _Budget,
    _Cell,
    _epoch,
    _feed,
    _pieces,
    _Sheet,
    _Strings,
    _Styles,
)
from .reading import (
    FALLBACK_ENCODING,
    Header,
    ReadRefused,
    Row,
    _reader,
    clean_cell,
    header_from,
    row_from,
    row_of,
    sniff_delimiter,
)
from .reading_xlsx import inspect as open_workbook
from .reading_xlsx import template_identity
from .safety import (
    _UNREADABLE,
    PROVISIONAL_LIMITS,
    Preflight,
    SafetyLimits,
    _lines,
    preflight,
)
from .targets import Format

#: How many rows go by between two calls of `watch`. A chunk boundary calls it
#: as well; this is for the rows a single chunk can hold.
WATCH_EVERY = 256

#: No budget: the sheet walk built for a sample is asked for every row.
_ALL = 1 << 62

_Watch = Callable[[], None]


def _unwatched() -> None:
    return None


@dataclass
class RowStream:
    """A source's header, and its rows as they are read.

    Iterate it once. The rows are produced as the file is walked and are not
    kept: a caller that needs something of a row takes it while it has the row.
    """

    format: Format
    header: Header
    #: What the CSV was split on; `","` for a workbook, as the store records it.
    delimiter: str
    #: What the CSV decoded under; `"utf-8"` for a workbook.
    encoding: str
    #: True when no strict encoding fitted a CSV. `reading.Decoded.replaced`.
    replaced: bool
    #: The workbook sheet being read; None for a CSV.
    sheet: str | None
    #: The template identity a workbook carried; None for a CSV.
    identity: str | None
    #: What the safety pass counted before any of this ran.
    preflight: Preflight
    _rows: Iterator[Row] = field(repr=False)

    def __iter__(self) -> Iterator[Row]:
        return self._rows

    def close(self) -> None:
        """Stop reading, and let go of the file. Safe to call twice."""
        close = getattr(self._rows, "close", None)
        if close is not None:
            close()


# ── CSV ──────────────────────────────────────────────────────────────────────


def _csv_rows(
    raw: bytes, checked: Preflight, delimiter: str | None, limit: int, watch: _Watch
) -> Iterator[Header | str | Row]:
    """The delimiter, the header, then every row -- `read_header` and `read_rows`."""
    # The safety pass has already decided the encoding, by the reader's own
    # order and over the whole file: `decode` would choose the same one.
    encoding = checked.encoding or FALLBACK_ENCODING
    replaced = encoding == FALLBACK_ENCODING

    def pieces() -> Iterator[str]:
        for text in _pieces(raw, encoding, "replace" if replaced else "strict"):
            watch()
            yield text

    stream = pieces()
    first = next(stream, "")
    chosen = delimiter or sniff_delimiter(first)

    def rest() -> Iterator[str]:
        yield first
        yield from stream

    reader = _reader(_lines(rest()), delimiter=chosen)
    try:
        header = header_from(next(reader))
    except StopIteration:
        raise ReadRefused(_EMPTY) from None
    yield chosen
    yield header

    produced = 0
    for number, record in enumerate(reader, start=2):
        # `read_rows`: a blank line is not a record.
        if not any(cell.strip() for cell in record):
            continue
        yield row_from(number, record, header)
        produced += 1
        if produced >= limit:
            return
        if not produced % WATCH_EVERY:
            watch()


# ── XLSX ─────────────────────────────────────────────────────────────────────


def _workbook_rows(
    raw: bytes, checked: Preflight, limit: int, watch: _Watch
) -> Iterator[Header | str | None | Row]:
    """The identity, the header, then every row of the sheet the pass scanned."""
    part, title, strings_part = checked.sheet_part, checked.sheet_title, checked.strings_part
    if part is None or title is None or checked.workbook_part is None:
        # A package that gives the reader no worksheet gives this none either.
        raise ReadRefused(_UNREADABLE)
    archive = open_workbook(raw)
    with archive:
        identity = template_identity(archive)

        styles = _Styles()
        if _STYLES_PART in archive.namelist():
            for _ in _feed(archive, _STYLES_PART, styles):
                watch()

        # Every string, once each. The safety pass's decoded-string budget is
        # a sum over these items, so this is the table it already bounded.
        table = _Strings(keep=True)
        if strings_part is not None:
            for _ in _feed(archive, strings_part, table):
                watch()

        sheet = _Sheet(
            table,
            styles.kinds(),
            _epoch(archive, checked.workbook_part),
            _Budget(_ALL, _ALL),
            limit,
        )
        header: Header | None = None
        cleaned: list[str] = []

        def clean(cell: _Cell) -> str:
            # An index names a string cleaned once, below; text is a cell of
            # its own -- a number, an inline string -- and is cleaned here.
            return cleaned[cell] if isinstance(cell, int) else clean_cell(cell)

        produced = 0
        feed = _feed(archive, part, sheet)
        finished = False
        while not finished:
            # One chunk of the sheet, then whatever rows it completed. The
            # last turn is the parser's own end of document.
            finished = next(feed, _END) is _END
            watch()
            if header is None:
                if sheet.header is None:
                    continue
                # Column names are the cells as they were written, which is
                # what `header_from` was always given; only then is the table
                # cleaned, in place, so the strings are held once.
                header = header_from(
                    [cell if isinstance(cell, str) else table.texts[cell] for cell in sheet.header]
                )
                cleaned = [clean_cell(text) for text in table.texts]
                table.texts = cleaned
                yield identity
                yield header
            pending, sheet.rows = sheet.rows, []
            for number, cells in pending:
                yield row_of(number, cells, header, clean)
                produced += 1
                if not produced % WATCH_EVERY:
                    watch()
        if header is None:
            raise ReadRefused(_EMPTY)


_END = object()


# ── the way in ───────────────────────────────────────────────────────────────


def open_rows(
    raw: bytes,
    fmt: Format,
    limits: SafetyLimits = PROVISIONAL_LIMITS,
    *,
    limit: int,
    delimiter: str | None = None,
    watch: Callable[[], None] | None = None,
) -> RowStream:
    """The header now, and up to `limit` rows as they are asked for.

    **The safety pass is inside this function**, ahead of everything else it
    does, so there is no way to read a source the envelope refuses.

    `delimiter` is the one recorded on a CSV's run; without it the header is
    sniffed as the reader always sniffed it. `watch` is called as the file is
    walked and may raise to end the read -- `WorkBudget.check` is the one a
    worker passes.

    A refusal the old readers raised before the first row was returned -- a
    cell that is a file, a number that is not one -- is raised here when the
    walk reaches it, from the iteration. Nothing a caller did with the rows
    before it is undone by this module: a dry run has stored nothing by then,
    and a commit has not yet called its writer.
    """
    if fmt not in (Format.CSV, Format.XLSX):
        raise ReadRefused(f"{fmt.value} files are not read in this release")
    watching = watch or _unwatched
    # The pass is asked as well: it walks the whole file before the first row
    # is read, and for a workbook at the edge of the envelope that is seconds.
    checked = preflight(
        raw, fmt, limits, delimiter=delimiter if fmt is Format.CSV else None, watch=watch
    )
    watching()
    if fmt is Format.XLSX:
        book = _workbook_rows(raw, checked, limit, watching)
        identity = next(book)
        header = next(book)
        assert isinstance(header, Header)  # noqa: S101 - the generator's own order
        return RowStream(
            format=fmt,
            header=header,
            delimiter=",",
            encoding="utf-8",
            replaced=False,
            sheet=checked.sheet_title,
            identity=identity if isinstance(identity, str) else None,
            preflight=checked,
            _rows=book,  # type: ignore[arg-type]
        )
    records = _csv_rows(raw, checked, delimiter, limit, watching)
    chosen = next(records)
    header = next(records)
    assert isinstance(chosen, str) and isinstance(header, Header)  # noqa: S101
    encoding = checked.encoding or FALLBACK_ENCODING
    return RowStream(
        format=fmt,
        header=header,
        delimiter=chosen,
        encoding=encoding,
        replaced=encoding == FALLBACK_ENCODING,
        sheet=None,
        identity=None,
        preflight=checked,
        _rows=records,  # type: ignore[arg-type]
    )


__all__ = ["WATCH_EVERY", "RowStream", "open_rows"]
