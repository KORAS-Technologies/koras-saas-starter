"""The worker's reader: that it reads what the readers read, and holds less.

GR-352C. `open_rows` replaced `read_workbook` and the whole-file `decode` in
the dry run and the commit, so three kinds of assertion are owed and none is
worth much alone.

**It answers what the readers answered.** `read_workbook`, and `decode` with
the three CSV functions, stay in the package as the description of what a
file's rows are, and every file `test_inspection.py` holds the bounded
inspection to is handed to both here and compared whole: the header, every
row with its number and its flags, the sheet, the identity, the delimiter, the
encoding. A refusal has to be the same sentence and the same type. Eighty more
come from a seeded generator.

**It holds less, and the measurement can tell.** A string named by every cell
is one object in every row. A sheet's merged ranges, links and validations
are built into nothing, where `read_workbook` on the same file builds tens of
mebibytes. A CSV is never one string. Each is measured with `tracemalloc`
beside the old reader on the same input, because a small figure with nothing
to compare it to could be a harness that measures nothing.

**It can be stopped.** `watch` is called as the file is walked and ends the
read when it raises.

The places this reader is deliberately *not* `read_workbook` are asserted as
what they are, at the end, so none can be mistaken for agreement.

`tests/unit/test_import_worker_memory.py` asks the kernel on Linux, through
the store's own functions.
"""

from __future__ import annotations

import random
import time
import tracemalloc
from collections.abc import Callable
from typing import Any

import pytest
from koras_import import (
    MAX_CELL,
    PROVISIONAL_LIMITS,
    BudgetExceeded,
    Format,
    ReadRefused,
    SafetyLimits,
    WorkBudget,
    decode,
    inspection,
    open_rows,
    read_workbook,
    streaming,
)
from test_inspection import (
    CSV_FILES,
    EMOJI,
    HAND,
    MAIN,
    WIDE_OPEN,
    WRITTEN,
    _value,
    book,
    grid,
    inline,
    letters,
    number,
    one,
    plain,
    reader_view,
    row,
    shared,
    sst,
    styles,
    worksheet,
)

pytestmark = pytest.mark.filterwarnings("ignore:Workbook contains no default style")

MEBIBYTE = 1024 * 1024

# ── the two answers, side by side ────────────────────────────────────────────


def read_view(raw: bytes, fmt: Format, limit: int, limits: SafetyLimits) -> tuple[Any, ...]:
    """What the dry run read until GR-352C: the readers, asked for `limit` rows."""
    header, rows, _seen, sheet, identity, delimiter, encoding = reader_view(
        raw, fmt, limit, limit, limits
    )
    return (header, rows, sheet, identity, delimiter, encoding)


def streamed_view(raw: bytes, fmt: Format, limit: int, limits: SafetyLimits) -> tuple[Any, ...]:
    stream = open_rows(raw, fmt, limits, limit=limit)
    rows = tuple(stream)
    return (stream.header, rows, stream.sheet, stream.identity, stream.delimiter, stream.encoding)


#: Every row, a file cut short, and a file cut to one row.
LIMITS = (1000, 2, 1)


def agree(
    raw: bytes,
    fmt: Format,
    *,
    limits: SafetyLimits = PROVISIONAL_LIMITS,
    row_limits: tuple[int, ...] = LIMITS,
) -> None:
    """Both answers are the same answer, or the same refusal, at every limit."""
    for limit in row_limits:
        try:
            expected = read_view(raw, fmt, limit, limits)
        except ReadRefused as refused:
            with pytest.raises(ReadRefused) as caught:
                streamed_view(raw, fmt, limit, limits)
            assert str(caught.value) == str(refused), limit
            assert type(caught.value) is type(refused), limit
            continue
        assert streamed_view(raw, fmt, limit, limits) == expected, limit


@pytest.mark.parametrize("name", sorted(CSV_FILES))
def test_a_csv_is_streamed_as_the_reader_read_it(name: str) -> None:
    agree(CSV_FILES[name], Format.CSV)
    try:
        stream = open_rows(CSV_FILES[name], Format.CSV, limit=10)
    except ReadRefused:
        return
    assert stream.replaced is decode(CSV_FILES[name]).replaced
    stream.close()


def test_a_csv_is_read_with_the_delimiter_its_run_recorded() -> None:
    # The worker passes the delimiter the mapping was made with rather than
    # sniffing again, as `_parse` always did.
    raw = b"Name;Title,Email\nAda;Countess,a@x.io\n"
    assert open_rows(raw, Format.CSV, limit=5).header.columns == ("Name;Title", "Email")
    stream = open_rows(raw, Format.CSV, limit=5, delimiter=";")
    assert stream.header.columns == ("Name", "Title,Email")
    assert [found.cells for found in stream] == [{"Name": "Ada", "Title,Email": "Countess,a@x.io"}]


@pytest.mark.parametrize("name", sorted(WRITTEN))
def test_a_workbook_openpyxl_wrote_is_streamed_as_the_reader_read_it(name: str) -> None:
    agree(WRITTEN[name], Format.XLSX)


@pytest.mark.parametrize("name", sorted(HAND))
def test_a_workbook_written_by_hand_is_streamed_as_the_reader_read_it(name: str) -> None:
    # A cell that is a file is refused where the walk meets it, so those are
    # compared at the limit that reaches their third row.
    agree(HAND[name], Format.XLSX, row_limits=(1000,) if "is-a-file" in name else LIMITS)


@pytest.mark.parametrize("seed", range(40))
def test_generated_workbooks_are_streamed_as_the_reader_read_them(seed: int) -> None:
    rng = random.Random(5000 + seed)  # noqa: S311 - a reproducible workbook, not a secret
    width = rng.randrange(1, 9)
    header = [rng.choice(["Name", "Email", "Qty", None, "Name", f"c{n}"]) for n in range(width)]
    header[0] = header[0] or "First"
    rows = [
        [_value(rng) for _ in range(rng.randrange(0, width + 3))]
        for _ in range(rng.randrange(0, 40))
    ]
    agree(one([header, *rows]), Format.XLSX, row_limits=(1000, rng.randrange(1, 12)))


@pytest.mark.parametrize("seed", range(40))
def test_generated_hand_written_sheets_are_streamed_as_the_reader_read_them(seed: int) -> None:
    rng = random.Random(6000 + seed)  # noqa: S311 - a reproducible workbook, not a secret
    table = [
        plain(rng.choice(["", "x", "Name", " ", "ż", "a" * 40, " pad ", "a_x0007_b"]))
        for _ in range(12)
    ]
    width = rng.randrange(1, 7)

    def cell() -> str:
        kind = rng.randrange(8)
        if kind < 2:
            return ""
        if kind < 5:
            return shared(rng.randrange(len(table)))
        if kind == 5:
            return inline(rng.choice(["", "in", " ", "Name", " x "]))
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
    agree(raw, Format.XLSX, row_limits=(1000, rng.randrange(1, 12)))


@pytest.mark.parametrize("fmt", [Format.CSV, Format.XLSX])
def test_chunk_boundaries_change_nothing(monkeypatch: pytest.MonkeyPatch, fmt: Format) -> None:
    # A row, a quoted field, a string and a `\r\n` each end up split across two
    # chunks at some size here.
    raw = (
        CSV_FILES["quoted"] + b"x,\"y\r\nz\",3\r\n" * 40
        if fmt is Format.CSV
        else WRITTEN["typed"]
    )
    expected = streamed_view(raw, fmt, 1000, PROVISIONAL_LIMITS)
    for size in (1, 2, 3, 7, 64, 257):
        # The reader's chunk is the inspection's and the safety pass's own.
        monkeypatch.setattr(inspection, "_CHUNK", size)
        assert streamed_view(raw, fmt, 1000, PROVISIONAL_LIMITS) == expected, size


def test_the_rows_are_produced_as_they_are_asked_for() -> None:
    # Opening reads the header and no further: a caller that stops early has
    # not paid for the rest of the sheet.
    raw = one([["N", "S"], *[[n, f"row {n}"] for n in range(5000)]])
    fed: list[str] = []
    real = inspection._feed

    def counted(archive: Any, name: str, handler: Any) -> Any:  # noqa: ANN401
        for step in real(archive, name, handler):
            fed.append(name)
            yield step

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(inspection, "_CHUNK", 4096)
        patch.setattr(streaming, "_feed", counted)
        stream = open_rows(raw, Format.XLSX, limit=10_000)
        sheet = "xl/worksheets/sheet1.xml"
        opened = fed.count(sheet)
        first = next(iter(stream))
        assert first.number == 2 and first.cells == {"N": "0", "S": "row 0"}
        assert opened <= 2, "the sheet was walked before a row was asked for"
        rest = sum(1 for _ in stream)
        assert rest == 4999
        assert fed.count(sheet) > opened + 5


# ── bounded: which parts are opened ──────────────────────────────────────────


def _after(rows: str, after: str) -> str:
    return f'<worksheet xmlns="{MAIN}"><sheetData>{rows}</sheetData>{after}</worksheet>'


def _furnished(count: int) -> bytes:
    """A small sheet carrying `count` each of merged ranges, links and validations."""
    merged = "".join(f'<mergeCell ref="K{n}:L{n}"/>' for n in range(1, count + 1))
    links = "".join(
        f'<hyperlink ref="M{n}" location="Sheet1!A1" display="go"/>' for n in range(1, count + 1)
    )
    checks = "".join(
        f'<dataValidation type="list" sqref="N{n}"><formula1>"a,b"</formula1></dataValidation>'
        for n in range(1, count + 1)
    )
    after = (
        f"<mergeCells>{merged}</mergeCells><dataValidations>{checks}</dataValidations>"
        f"<hyperlinks>{links}</hyperlinks>"
    )
    return book(_after(grid([[inline("Name")], [inline("Ada")], [inline("Grace")]]), after))


def _peak(work: Callable[[], Any]) -> int:
    tracemalloc.start()
    try:
        work()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def _drain(raw: bytes, fmt: Format, limits: SafetyLimits = PROVISIONAL_LIMITS) -> int:
    count = 0
    for _ in open_rows(raw, fmt, limits, limit=1_000_000):
        count += 1
    return count


def test_merged_ranges_links_and_validations_are_built_into_nothing() -> None:
    """IMPORT-GAP-020. None of these is a cell, so the safety pass counts none.

    `openpyxl` builds an object for each when the walk reaches the end of the
    sheet, and a tree of elements under each list first: GR-352C measured a
    million validations at 1.4 GiB in a worker. This reader has no handler for
    the elements they are in.
    """
    raw = _furnished(20_000)
    streamed = _peak(lambda: _drain(raw, Format.XLSX))
    assert _drain(raw, Format.XLSX) == 2
    assert streamed < 3 * MEBIBYTE, streamed
    # And the measurement can tell: the reader this replaced, on the same file.
    built = _peak(lambda: read_workbook(raw, limit=10, ceiling=10))
    assert built > 8 * streamed, (built, streamed)


def test_only_the_parts_the_safety_pass_named_are_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three parts, and no other sheet. IMPORT-GAP-015, for the worker.

    `openpyxl` walks every worksheet of a workbook to its end when it is
    loaded, to learn dimensions the sheet did not declare, and parses the
    stylesheet, the workbook part and the document properties into trees.
    """
    heavy = worksheet(grid([[inline("x" * 20_000)] for _ in range(50)]))
    raw = book(
        "",
        sst([plain("Name"), plain("Ada")]),
        sheets={
            "Lookup": heavy,
            "Data": worksheet(grid([[shared(0)], [shared(1)]])),
            "More": heavy,
        },
        stylesheet=styles({}, [0]),
    )
    opened: list[str] = []
    real = inspection._feed

    def recorded(archive: Any, name: str, handler: Any) -> Any:  # noqa: ANN401
        opened.append(name)
        return real(archive, name, handler)

    monkeypatch.setattr(streaming, "_feed", recorded)
    stream = open_rows(raw, Format.XLSX, limit=10)
    assert [found.cells for found in stream] == [{"Name": "Ada"}]
    assert stream.sheet == "Data"
    assert opened == ["xl/styles.xml", "xl/sharedStrings.xml", "xl/worksheets/sheet2.xml"]


def test_the_old_readers_are_not_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    import openpyxl
    from koras_import import reading, reading_xlsx

    def reached(*_: object, **__: object) -> None:
        raise AssertionError("the streaming reader reached a whole-file reader")

    monkeypatch.setattr(openpyxl, "load_workbook", reached)
    monkeypatch.setattr(reading_xlsx, "read_workbook", reached)
    monkeypatch.setattr(reading, "decode", reached)
    assert _drain(WRITTEN["many-rows"], Format.XLSX) == 1500
    assert _drain(CSV_FILES["many-rows"], Format.CSV) == 1500


def test_an_unsafe_source_is_refused_before_any_of_it_is_streamed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reached(*_: object, **__: object) -> None:
        raise AssertionError("the file was streamed before the safety pass refused")

    monkeypatch.setattr(streaming, "_csv_rows", reached)
    monkeypatch.setattr(streaming, "_workbook_rows", reached)
    tight = SafetyLimits(max_cells=3)
    for raw, fmt in ((WRITTEN["many-rows"], Format.XLSX), (CSV_FILES["many-rows"], Format.CSV)):
        with pytest.raises(ReadRefused, match="more than the 3 cells"):
            open_rows(raw, fmt, tight, limit=10)
    with pytest.raises(ReadRefused, match="json files are not read"):
        open_rows(b"{}", Format.JSON, limit=10)


# ── bounded: a string is held once ───────────────────────────────────────────


def _one_string(text: str, rows: int, columns: int) -> bytes:
    """A workbook whose every data cell names one shared string."""
    head = [shared(1 + column) for column in range(columns)]
    body = [[shared(0)] * columns for _ in range(rows)]
    table = [plain(text), *[plain(f"c{column}") for column in range(columns)]]
    return book(worksheet(grid([head, *body])), sst(table))


@pytest.mark.parametrize(
    "text",
    ["b" * 30_000, "b" * 29_999 + " ", "\tb" + "b" * 29_000 + EMOJI + "\n", " " + EMOJI * 8000],
    ids=["clean", "trailing-space", "padded-and-astral", "astral"],
)
def test_a_string_named_by_every_cell_is_one_string(text: str) -> None:
    """IMPORT-DEF-016, in the reader.

    The safety pass costs a shared string once, because the file holds it
    once. `row_from` cleaned a cell at a time, and cleaning a string that
    needs it makes a new one -- so a string with one trailing space, named by
    every cell, was a copy a cell, and a workbook of a few hundred kibibytes
    was gibibytes of one string. Here the table is cleaned once and a cell is
    the cleaned string itself.
    """
    from koras_import import clean_cell

    raw = _one_string(text, rows=400, columns=6)
    expected = clean_cell(text)
    first: str | None = None
    count = 0
    for found in open_rows(raw, Format.XLSX, limit=1000):
        for value in found.cells.values():
            assert value is (first := first if first is not None else value)
            count += 1
    assert first == expected and count == 2400
    # 2,400 cells of a 30,000-character string would be 72 MiB or more if each
    # cell were its own; what is held is the table.
    cost = len(expected.encode("utf-32-le")) if not expected.isascii() else len(expected)
    assert _peak(lambda: _drain(raw, Format.XLSX)) < 3 * cost + MEBIBYTE


def test_the_header_is_named_before_the_table_is_cleaned() -> None:
    # `header_from` was always given the cell as it stood, and the table is
    # cleaned in place only after it has been: the same string is a column
    # name in row one and a value in row two, and both are what they were.
    raw = book(
        worksheet(grid([[shared(0), shared(1)], [shared(0), shared(1)]])),
        sst([plain(" Name\n"), plain("  Ada  ")]),
    )
    agree(raw, Format.XLSX)
    stream = open_rows(raw, Format.XLSX, limit=5)
    assert stream.header.columns == ("Name", "Ada")
    assert [found.cells for found in stream] == [{"Name": "Name", "Ada": "Ada"}]


def test_a_csv_is_never_one_string() -> None:
    lines = b"".join(b"%07d,%s\n" % (n, b"x" * 120) for n in range(60_000))
    raw = b"Id,Text\n" + lines
    assert len(raw) > 7 * MEBIBYTE
    streamed = _peak(lambda: _drain(raw, Format.CSV))
    assert _drain(raw, Format.CSV) == 60_000
    assert streamed < 2 * MEBIBYTE, streamed

    def as_before() -> int:
        return len(decode(raw).text.splitlines(keepends=True))

    assert _peak(as_before) > 8 * streamed


# ── it can be stopped ────────────────────────────────────────────────────────


def test_a_budget_is_a_deadline_and_a_stop_flag() -> None:
    now = [100.0]
    budget = WorkBudget(5.0, clock=lambda: now[0])
    budget.check()
    now[0] = 104.9
    budget.check()
    now[0] = 105.1
    with pytest.raises(BudgetExceeded, match="took longer than one run is allowed"):
        budget.check()

    stopped = WorkBudget(5.0, clock=lambda: 0.0)
    assert stopped.cancelled is False
    stopped.cancel()
    assert stopped.cancelled is True
    with pytest.raises(BudgetExceeded, match="was stopped"):
        stopped.check()
    # A refusal like any other: every caller that records one records this.
    assert issubclass(BudgetExceeded, ReadRefused)
    with pytest.raises(ValueError, match="positive"):
        WorkBudget(0)


@pytest.mark.parametrize("fmt", [Format.CSV, Format.XLSX])
def test_the_read_ends_where_the_watch_says(fmt: Format) -> None:
    raw = WRITTEN["many-rows"] if fmt is Format.XLSX else CSV_FILES["many-rows"]
    calls = 0
    reading = False

    def watch() -> None:
        nonlocal calls
        # The safety pass asks as well, before the first row; this is about
        # the rows, so the questions are counted from where they begin.
        calls += reading
        if calls > 4:
            raise BudgetExceeded("enough")

    stream = open_rows(raw, fmt, limit=10_000, watch=watch)
    reading = True
    taken = 0
    with pytest.raises(BudgetExceeded, match="enough"):
        for _ in stream:
            taken += 1
    # It was asked between rows, not only between chunks: both files are a
    # single chunk, and the read still ended before the file did.
    assert 0 < taken < 1500
    assert list(stream) == []


@pytest.mark.parametrize("fmt", [Format.CSV, Format.XLSX])
@pytest.mark.parametrize("ask", [1, 2, 3])
def test_the_safety_pass_is_asked_too_and_does_not_call_it_the_file_s_fault(
    monkeypatch: pytest.MonkeyPatch, fmt: Format, ask: int
) -> None:
    """The pass walks the whole file before the first row is read.

    For a workbook at the edge of the envelope that is seconds, and a budget
    that could not reach into it measured at 7.5 seconds to honour a
    two-second timeout. It is asked once a chunk -- and what it raises comes
    out as itself, not as "the file could not be read", which is what every
    other `ValueError` inside a part becomes.
    """

    def reached(*_: object, **__: object) -> None:
        raise AssertionError("the reader was reached after the budget was spent")

    monkeypatch.setattr(streaming, "_csv_rows", reached)
    monkeypatch.setattr(streaming, "_workbook_rows", reached)
    raw = WRITTEN["many-rows"] if fmt is Format.XLSX else CSV_FILES["many-rows"]
    calls = 0

    def watch() -> None:
        nonlocal calls
        calls += 1
        if calls >= ask:
            raise BudgetExceeded("enough")

    if fmt is Format.CSV and ask > 1:
        # One chunk, so one question: the file is smaller than a chunk.
        monkeypatch.setattr(inspection, "_CHUNK", 4096)
        from koras_import import safety

        monkeypatch.setattr(safety, "_CHUNK", 4096)
    with pytest.raises(BudgetExceeded, match="enough") as caught:
        open_rows(raw, fmt, limit=10_000, watch=watch)
    assert type(caught.value) is BudgetExceeded
    assert calls == ask


def test_a_spent_budget_ends_a_long_read_promptly() -> None:
    raw = one([["N", "S"], *[[n, f"row {n}"] for n in range(20_000)]])
    budget = WorkBudget(0.05)
    started = time.monotonic()
    with pytest.raises(BudgetExceeded):
        for _ in open_rows(raw, Format.XLSX, limit=100_000, watch=budget.check):
            time.sleep(0.001)
    # Twenty thousand rows at a millisecond each is twenty seconds.
    assert time.monotonic() - started < 5


# ── where this is deliberately not `read_workbook` ───────────────────────────


_GOOD = worksheet(grid([[inline("Name")], [inline("Ada")]]))

BROKEN_ELSEWHERE: dict[str, bytes] = {
    # `openpyxl` parses the document properties and refuses the workbook for them.
    "document-properties": book(_GOOD, extra={"docProps/core.xml": "<not closed"}),
    # And walks every worksheet when the workbook is loaded, to learn the
    # dimensions it did not declare -- so a sheet nobody asked for, cut short,
    # refuses the one that was.
    "another-sheet-cut-short": book(
        "", sheets={"Data": _GOOD, "Other": "<worksheet><sheetData><row>"}
    ),
    "another-sheet-that-is-not-xml": book("", sheets={"Data": _GOOD, "Other": "\x00\x01 no"}),
}


@pytest.mark.parametrize("name", sorted(BROKEN_ELSEWHERE))
def test_a_part_this_reader_never_opens_may_be_broken(name: str) -> None:
    raw = BROKEN_ELSEWHERE[name]
    with pytest.raises(ReadRefused, match="could not be read as a workbook"):
        read_workbook(raw, limit=5, ceiling=5)
    assert [found.cells for found in open_rows(raw, Format.XLSX, limit=5)] == [{"Name": "Ada"}]


def test_a_string_over_the_limit_until_its_escapes_are_removed_is_refused() -> None:
    # 33,600 characters as written and 30,000 once `x005F_` is taken out.
    # `openpyxl` measures the second; this measures the first, as the bounded
    # inspection does, and for its reason: the text is counted as it arrives.
    text = "a" * 30_000 + "x005F_" * 600
    assert len(text) > MAX_CELL
    raw = book(worksheet(grid([[inline("Name")], [shared(0)]])), sst([plain(text)]))
    assert read_workbook(raw, limit=5, ceiling=5).rows[0].cells == {"Name": "a" * 30_000}
    with pytest.raises(ReadRefused, match="this is a file in a cell"):
        list(open_rows(raw, Format.XLSX, limit=5))


def test_a_stylesheet_that_is_not_one_is_refused_rather_than_loaded() -> None:
    crowded = styles({}, [0] * (inspection.MAX_STYLES + 1))
    raw = book(worksheet(grid([[inline("N")], [number("1")]])), stylesheet=crowded)
    assert read_workbook(raw, limit=5, ceiling=5, limits=WIDE_OPEN).rows_seen == 1
    with pytest.raises(ReadRefused, match="could not be read as a workbook"):
        open_rows(raw, Format.XLSX, WIDE_OPEN, limit=5)


def test_a_refusal_inside_the_file_arrives_from_the_iteration() -> None:
    # The old readers raised before they returned a row. This one has returned
    # the rows above the bad one by then; a caller has written nothing with
    # them, which is the store's and the worker's to keep.
    good = [[number(str(n))] for n in range(1, 400)]
    raw = book(worksheet(grid([[inline("N")], *good, [number("not a number")]])))
    with pytest.raises(ReadRefused, match="could not be read as a workbook"):
        read_workbook(raw, limit=1000, ceiling=1000)
    with pytest.MonkeyPatch.context() as patch:
        # Small chunks, so the bad cell is not in the chunk the header is in.
        patch.setattr(inspection, "_CHUNK", 512)
        stream = open_rows(raw, Format.XLSX, limit=1000)
        seen: list[str] = []
        with pytest.raises(ReadRefused, match="could not be read as a workbook"):
            for found in stream:
                seen.append(found.cells["N"])
    assert 0 < len(seen) < 399 and seen == [str(n) for n in range(1, len(seen) + 1)]
