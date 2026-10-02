# The bounded inspection

> **Status, 2026-10-01: GR-352B is built. GR-352 is open, and HIGH.** This
> document describes the second slice of a release gate, not its resolution.
> The limits it runs inside are the provisional ones of
> `preflight-safety-envelope.md`, the memory envelope has not been ratified by
> anybody, the worker is untouched, and the import framework is not claimed to
> be safe for production until every GR-352 acceptance criterion has passed.
>
> **GR-352C was built on 2026-10-02**, and "the worker is untouched" was true
> of this slice and is not true of the tree after it. The dry run and the
> commit no longer call the canonical readers: they read rows as a stream,
> built from the sheet walk this document describes and asked for every row.
> The statements below about what the worker does are marked where they
> stand. `worker-resource-envelope.md` here is the description of that slice.

## What GR-352B is

The analysis route shows somebody the first two hundred rows of their file and
offers a mapping. The mapping route checks a mapping against the file's
columns. Until 2026-10-01 both did it by handing the whole file to the readers
the dry run uses -- `read_workbook`, which has `openpyxl` build the workbook's
entire shared-string table, and `decode`, which makes one string of the whole
CSV -- inline, on the API's event loop, and then discarding everything past
row two hundred.

GR-352 measured what that cost before any limit existed: 989 MiB resident for
a workbook near the old limits, 37 seconds for fifty thousand rows, 126 for a
1,500-column workbook, during all of which the process answered nothing else.
GR-352A put a safety pass in front and so capped the worst of it. It did not
change the shape: a file that passed was still parsed whole to preview a head
of it.

GR-352B changes the shape. The two routes inspect the head of the file by
streaming it, and neither reader is called.

```
source bytes → safety pass → inspection → header, ≤200 rows, a capped count
               (GR-352A)     (GR-352B)
                   │
                   └─ refused; nothing was inspected

                                  the dry run and the commit are unchanged:
source bytes → safety pass → the canonical reader → every row
```

## Two paths, and which one is authoritative

| | The inspection | The canonical readers |
|-|----------------|-----------------------|
| Module | `koras_import/inspection.py` | `koras_import/reading.py`, `koras_import/reading_xlsx.py` |
| Reached by | `GET /imports/{id}/analysis`, `PUT /imports/{id}/mapping` | the worker's dry run and commit, through `_parse` |
| Reads | the header, the sample, a count | every row |
| Holds | the sample | the file |
| Decides | what the mapping page draws | what is validated and what is written |

**The readers are authoritative.** Nothing the inspection returns is validated
or written; a row is validated when the dry run reads it through the canonical
reader, and written when the commit reads it again. The inspection is built to
agree with them on the three things it answers, and `test_inspection.py`
checks that by handing both the same files and comparing the answers whole.

**Since GR-352C, 2026-10-02, there are three things here and not two.** The
dry run and the commit read through `koras_import/streaming.py`, which is
this module's sheet walk -- `_Sheet`, `_Strings`, `_Styles` -- with nothing
held back for a sample. `reading.py` and `reading_xlsx.py` still say what a
file's rows are, and both the inspection and the stream are held to them:
the inspection on a head by `test_inspection.py`, the stream on every row by
`test_streaming.py`. So a change to this module's walk is, since that day, a
change to what a commit writes.

## The result

`inspect_source` takes the bytes, the format, the envelope, a `sample` and a
`ceiling`, and returns an `Inspection`:

| Field | Meaning |
|-------|---------|
| `format` | What was handed in |
| `header` | The reader's own `Header`: columns, duplicated names, unnamed ones |
| `rows` | Up to `sample` rows, as the reader's own `Row`: number, cells, short, long |
| `rows_seen` | Data rows by the reader's rule, counted no further than one past `ceiling` |
| `over_ceiling` | `rows_seen` is past `ceiling` |
| `delimiter`, `encoding`, `replaced` | What the CSV was read as; fixed values for a workbook |
| `sheet`, `identity` | The workbook sheet read and the template identity it carried |
| `sample_cut` | The sample stopped short of rows that were there, at its budget |
| `preflight` | What the safety pass counted before any of this ran |

`core/imports.analyse` turns that into the `Analysis` the routes have always
answered, adding the suggested mapping and the template verdict, which are
functions of the header and the target and were never the expensive part.

## The safety pass is still first

`inspect_source` calls `preflight` itself, before anything else it does, by the
arrangement `read_workbook` already has: a caller chooses the envelope and
cannot choose to have none. Every limit of GR-352A applies unchanged -- source
bytes, uncompressed bytes, the decoded-string budget, cells, columns, archive
entries.

**The safety pass reads the whole file, and the inspection does not stop it
from doing so.** A file that is over its row ceiling *and* outside the
envelope is answered as outside the envelope, as it was before this slice. The
alternative -- stopping everything at the ceiling -- would make the refusal a
person is given depend on which limit the walk happened to meet first.

Rows are still not refused by the analysis. It answers `over_ceiling` in a
200, and the mapping route turns that into its 422, exactly as before.

## The sample

`PREVIEW` in `core/imports.py` is 200 and is unchanged. The analysis route asks
for 200 rows. The mapping route asks for none: it needs the columns and
whether the file is over its ceiling, and shows nobody a preview.

One quirk of the old path is reproduced deliberately. A CSV's preview was
never bounded by the target's row ceiling and a workbook's was -- the workbook
reader stops at the ceiling and the CSV reader was asked for 200 rows
regardless -- so a target taking fewer than 200 rows shows a longer preview
for a CSV than for a workbook. The inspection keeps both behaviours rather
than choosing one.

### The sample's budget

**The analysis returns up to 200 preview rows.** Two hundred is the most a
preview holds, not a number it always reaches. A provisional budget of 4 MiB
of preview characters can stop the sample earlier when a file's first rows are
unusually large. A shorter preview does not prevent validation or the commit,
and it changes nothing about how the worker reads the source: the dry run and
the commit read every row through the canonical readers whatever the preview
showed. The budget is a provisional safety guardrail, approved by the owner on
2026-10-01, pending GR-352C's measurements and OD-22/NFR ratification.

Two hundred rows is a contract about rows and says nothing about bytes. One
32,000-character string named by every cell of two hundred hundred-column
rows is a 78 KiB workbook, inside every limit of the safety envelope because
the string is in the file once. Measured on 2026-10-01 against `b24a72d`,
through the analysis and the response a route would then write:
**1,834 MiB of API memory, a 611 MiB response, and 46 seconds.**

`MAX_SAMPLE_CHARACTERS` bounds what the sample may carry: four mebibytes of
characters, counting each row's column names with its cells because the
response repeats both. A sample that would pass it stops at the row before,
and `sample_cut` says so. The rows it kept are still the head of the file, in
order; the count is unaffected. The same workbook after this slice: 10 MiB,
a 3 MiB response and half a second, for one row of preview -- each of its rows
is 3.2 million characters, and the second would pass the budget.

**This is the one place the preview can differ from before.** An ordinary
file's two hundred rows are a few hundred kibibytes and are untouched. A file
whose first two hundred rows carry more than four million characters -- about
twenty thousand a row -- gets a shorter preview than it did.

**What was decided, on 2026-10-01.** The budget stays, at this value, as a
provisional guardrail. An otherwise safe import is not refused to guarantee
exactly two hundred rows, and the budget is not raised to preserve them. The
final value waits on GR-352C's measurements and on OD-22/NFR ratification.
The response has no field for `sample_cut` and none was added -- no existing
field carries it, and a new one is a contract decision of its own -- so the
store logs a line with the counts. IMPORT-GAP-017.

## The CSV inspection

The file is decoded 256 KiB at a time, in the encoding the safety pass settled
on -- it is the pass that tried `utf-8-sig`, then `cp1252`, then `latin-1`,
strictly and over the whole file, so the inspection does not guess from a head
that happens to be valid UTF-8. No string the size of the file exists.

- **The delimiter** is sniffed from the first chunk by the reader's own
  function, which looks at the header line alone.
- **Lines** are split by the function the safety pass uses, extracted from it
  for the purpose, so both agree on where a line ends.
- **The header and the sample** come through the reader's own `csv` wrapper,
  `header_from` and `row_from`. The walk stops when the sample is settled.
- **The count is the safety pass's.** It counted every row of the file a
  moment earlier, through the same reader and by the same rule -- the header
  is not a row and a blank line is not one -- so `rows_seen` is that count
  held to one past the ceiling, with no second walk.

## The workbook inspection

`zipfile` and `expat`, as in the safety pass, and for the same reason: no tree
is built. `load_workbook` is not called.

1. **The sheet** is `Data`, or the first worksheet, from the workbook's own
   index -- the reader's rule.
2. **The stylesheet** is streamed for one thing: which cell formats are dates.
   Two bits a format are kept, decided as each number format goes by.
3. **The string table is streamed once for lengths.** Four bytes an item. A
   length is what the sheet pass needs of a string it will not show: whether
   the cell is empty, whether it is a file in a cell, what it would cost the
   sample.
4. **The sheet is streamed** for the header, the sample and the count. Rows are
   taken as the reader takes them -- a row is its number, a gap above row one
   means an empty first row, a row out of order is dropped, a row's width is
   its last cell's column. The walk stops one row past the ceiling.
5. **The string table is streamed a second time**, keeping only the items the
   header and the sample point at, and stopping at the last of them.

### Shared strings

This is the part GR-352 turned on, so it is stated exactly.

- The table is never held. Its lengths are -- four bytes a string, about four
  mebibytes for the million strings the decoded budget allows at most.
- The strings kept are the ones the header and the sample name, wherever in
  the table they are. **Nothing assumes the first rows use the first
  strings**: `test_inspection.py` has a workbook whose first rows name its
  last strings, and the Linux suite has one at the edge of the budget.
- A string named by many sample cells is kept once.
- The second walk ends at the highest index wanted, so a sample that does use
  the head of the table reads the head of the table.

No temporary file, no index on disk and no new parser architecture: two
streaming walks of a part the safety pass already walks once.

### What a cell becomes

The inspection returns text, as the readers do. For the header and the sample
a cell is `cell_text` applied to the value `openpyxl` would have produced, by
`openpyxl`'s own date functions -- `from_excel`, `is_date_format` and their
neighbours -- which are imported and called. One rule, rather than a second
implementation that could drift from the first.

| Cell | Text |
|------|------|
| Empty, or a formula with no cached value | empty |
| Shared string | its text: the plain run, then each rich-text run; phonetic runs left out |
| Inline string | the same joining rule |
| Number | `42` for an integral value, the shortest repeating form otherwise |
| Number in a date format | ISO date; a date-time at midnight is its date; a time of day keeps its time |
| Number in a duration format | Python's text for the duration, as the reader gives it |
| Boolean | `true` or `false` |
| ISO date cell | as a number in a date format |
| Cached formula string, error value | as it is |
| A date outside the calendar | `#VALUE!` |

Then the reader's `row_from`: controls removed, whitespace stripped.

**A cell past the sample is not converted.** It is asked two things: whether
it is empty, which decides whether its row counts, and whether it is longer
than a cell may be, which is the refusal the reader would have raised there.

### Where it is deliberately not the reader

Two places, each of them a malformed workbook and none a file a spreadsheet
writes. Each is asserted as what it is, in `test_inspection.py`, so neither can
be mistaken for agreement.

| Shape | The canonical reader | The inspection |
|-------|----------------------|----------------|
| A part the mapping page never needs is broken -- core properties, the theme | refuses the workbook | does not open the part; the dry run still refuses |
| A numeric cell past the sample is not a number | a refusal | not noticed; the dry run refuses it |

A third is narrower than either: a shared string longer than a cell may be
*only until* its escaped underscores are removed is a refusal here and is not
one there.

**There were four, for a day.** A cell naming a string the table lacks, and a
workbook with no sheet to read, were unhandled errors in the canonical reader
and refusals here; both are refusals in both since 2026-10-01, in the same
sentence. The fourth was not a difference in behaviour at all but a defect in
the safety pass, below.

### Which parts are read: IMPORT-DEF-017

Building this slice found that the safety pass and the reader did not agree
about which parts of a workbook are the string table and the sheet, and that
wherever they disagreed the pass scanned one part and the reader read another.
It was first seen as a renamed root element and turned out to be nine doors,
not one. `preflight-safety-envelope.md` here has the account.

For one day the inspection carried a rule of its own -- read only a part whose
root the pass would have recognised -- so that the two routes did not inherit
the hole. That rule is gone. The pass was corrected on 2026-10-01 to resolve
the package as `openpyxl` does; it reports the sheet part, the sheet's title
and the string-table part it scanned; and the inspection reads those and has
no resolution of its own. Three opinions about which part is the sheet was one
more than is safe.

The first row closes IMPORT-GAP-015 for the API: the parts `openpyxl` loads
eagerly that are neither strings nor sheets are not loaded by the routes at
all. It stays open for the worker, which still calls `load_workbook`.

## The event loop

`core/imports.analysed` is `analyse` on a worker thread, by
`asyncio.to_thread` -- what `core/knowledge.py` already does for its own
CPU-bound read. Both routes await it. No queue and no job: an analysis stores
nothing, and somebody is waiting for the answer.

**Bounded in memory is not bounded in time.** The inspection is Python
handling one parser event after another, and a workbook at the edge of the
envelope is several seconds of it. On a thread the loop keeps turning; the
interpreter lock is shared, so other requests are slower while it runs rather
than stopped.

`tests/unit/test_import_inspection.py` proves it without a clock: the
inspection is replaced with one that blocks until the test releases it, and
the test releases it only after another request has been answered by the same
application. Run inline, the other request cannot be answered, the block gives
up, and the test fails.

## What was measured

In `python:3.12-slim`, on 2026-10-01, through `core/imports.analyse` -- the
function both routes reach -- in a process of its own for each file, reading
the kernel's `VmHWM`. "Before" is this repository at `b24a72d`, which has the
GR-352A safety pass; "after" is this slice. `openpyxl` is imported before the
baseline is taken in both, because a module the API holds once is not what a
request costs. Every file is accepted by the safety envelope.

Memory is the largest figure across the runs taken -- four of `b24a72d`, seven of
this slice -- and time is their median. Sizes are in mebibytes.

**The files.** Decoded is the safety pass's own estimate, the figure its budget is
held against; every one of these is under 64.

| File | Source | Uncompressed | Decoded | Rows | Columns | Cells |
|------|-------:|-------------:|--------:|-----:|--------:|------:|
| Workbook, realistic: 50,000 rows by 8, 100,203 shared strings | 2.9 | 18.4 | 11.1 | 50,000 | 8 | 400,008 |
| Workbook, shared strings, ASCII, at the decoded budget | 0.9 | 60.5 | 61.2 | 20,000 | 3 | 60,003 |
| The same at a quarter of the size | 0.2 | 15.1 | 15.3 | 5,000 | 3 | 15,003 |
| Workbook, shared strings, each with one astral character | 0.6 | 17.8 | 61.2 | 20,000 | 3 | 60,003 |
| Workbook, the sample names the table's last strings | 0.9 | 60.5 | 61.2 | 20,000 | 3 | 60,003 |
| Workbook, inline strings, ASCII, at the decoded budget | 0.8 | 60.3 | 60.9 | 20,000 | 3 | 60,003 |
| Workbook, inline strings, each with one astral character | 0.4 | 17.6 | 60.9 | 20,000 | 3 | 60,003 |
| Workbook, 49,900 rows by 20 numbers: at the cell limit | 6.5 | 30.0 | 5.4 | 49,900 | 20 | 998,020 |
| Workbook, 3,900 rows by 256 numbers: at the column limit | 7.0 | 28.9 | 5.4 | 3,900 | 256 | 998,656 |
| CSV, realistic: 50,000 rows by 8 | 5.2 | n/a | 5.2 | 50,000 | 8 | 400,008 |
| CSV, 60 MiB of ASCII; the target takes 50,000 rows | 60.4 | n/a | 60.4 | 240,000 | 4 | 960,004 |
| The same; the target takes every row | 60.4 | n/a | 60.4 | 240,000 | 4 | 960,004 |
| The same at a quarter of the size | 15.1 | n/a | 15.1 | 60,000 | 4 | 240,004 |
| CSV, every field ends in an astral character | 16.5 | n/a | 63.2 | 60,000 | 4 | 240,004 |
| CSV, ASCII but for one astral character on line two | 15.8 | n/a | 63.2 | 60,000 | 4 | 240,004 |
| CSV, 3,900 rows by 256 three-character fields | 3.8 | n/a | 3.8 | 3,900 | 256 | 998,656 |

**Peak resident set.** Baseline is the process with its modules loaded and the
file already read into it. Net is how far the peak rose above that while the
analysis ran, which is what the analysis itself costs.

| File | Baseline | Peak before | Net before | Peak after | Net after |
|------|---------:|------------:|-----------:|-----------:|----------:|
| Workbook, realistic: 50,000 rows by 8, 100,203 shared strings | 58.0 | 81.9 | **18.2** | 61.2 | **2.8** |
| Workbook, shared strings, ASCII, at the decoded budget | 55.3 | 122.8 | **67.4** | 58.2 | **2.8** |
| The same at a quarter of the size | 54.7 | 71.7 | **16.9** | 56.9 | **2.1** |
| Workbook, shared strings, each with one astral character | 54.9 | 123.3 | **68.2** | 57.3 | **2.6** |
| Workbook, the sample names the table's last strings | 55.5 | 123.0 | **67.4** | 58.0 | **2.2** |
| Workbook, inline strings, ASCII, at the decoded budget | 55.1 | 59.5 | **4.4** | 58.4 | **2.9** |
| Workbook, inline strings, each with one astral character | 54.8 | 59.2 | **4.3** | 58.0 | **2.7** |
| Workbook, 49,900 rows by 20 numbers: at the cell limit | 60.9 | 67.1 | **6.0** | 63.5 | **2.2** |
| Workbook, 3,900 rows by 256 numbers: at the column limit | 61.2 | 66.2 | **4.8** | 66.6 | **5.2** |
| CSV, realistic: 50,000 rows by 8 | 59.6 | 73.2 | **13.5** | 61.9 | **1.8** |
| CSV, 60 MiB of ASCII; the target takes 50,000 rows | 114.9 | 251.4 | **136.5** | 117.0 | **1.8** |
| The same; the target takes every row | 114.9 | 251.4 | **136.5** | 116.8 | **1.8** |
| The same at a quarter of the size | 69.5 | 103.8 | **34.2** | 71.6 | **1.8** |
| CSV, every field ends in an astral character | 71.0 | 202.6 | **131.5** | 77.8 | **6.7** |
| CSV, ASCII but for one astral character on line two | 70.1 | 152.2 | **82.1** | 72.8 | **2.3** |
| CSV, 3,900 rows by 256 three-character fields | 58.3 | 69.6 | **11.4** | 62.4 | **4.0** |

**Wall-clock**, in seconds, for the whole of `analyse`: the safety pass and what
follows it.

| File | Before | After |
|------|-------:|------:|
| Workbook, realistic: 50,000 rows by 8, 100,203 shared strings | 10.74 | 5.50 |
| Workbook, shared strings, ASCII, at the decoded budget | 3.50 | 1.72 |
| The same at a quarter of the size | 0.75 | 0.42 |
| Workbook, shared strings, each with one astral character | 3.20 | 1.58 |
| Workbook, the sample names the table's last strings | 3.00 | 2.06 |
| Workbook, inline strings, ASCII, at the decoded budget | 3.09 | 1.35 |
| Workbook, inline strings, each with one astral character | 2.98 | 1.34 |
| Workbook, 49,900 rows by 20 numbers: at the cell limit | 18.87 | 9.51 |
| Workbook, 3,900 rows by 256 numbers: at the column limit | 20.87 | 9.21 |
| CSV, realistic: 50,000 rows by 8 | 0.33 | 0.18 |
| CSV, 60 MiB of ASCII; the target takes 50,000 rows | 1.44 | 1.18 |
| The same; the target takes every row | 2.57 | 1.22 |
| The same at a quarter of the size | 0.56 | 0.30 |
| CSV, every field ends in an astral character | 0.95 | 0.65 |
| CSV, ASCII but for one astral character on line two | 0.69 | 0.32 |
| CSV, 3,900 rows by 256 three-character fields | 0.25 | 0.15 |

**What the figures say.**

- The analysis costs **1.8 to 6.7 MiB** over the file it was handed. At
  `b24a72d` the same files cost 4.3 to 136.5.
- The worst peak of an analysing process is **117.0 MiB**, and 114.9 of that
  was there before the analysis began: the process, and the 60 MiB file it
  had been handed. At `b24a72d` it was 251.4.
- **It does not grow with what it does not show.** Four times the workbook is
  2.1 MiB and then 2.8; four times the CSV is 1.8 and then 1.8. At `b24a72d`
  they were 16.9 and then 67.4, and 34.2 and then 136.5 -- proportional.
- The sample naming the table's last strings costs what the sample naming its
  first does.
- One row did not improve and should not have: the workbook at the column
  limit, 4.8 MiB before and 5.2 after. That is the sample itself -- two
  hundred rows of 256 cells -- which both paths hold.
- The inline-string and numeric workbooks were never a memory problem, because
  `openpyxl` streams those. They were a time problem, on the event loop, and
  the time roughly halved: 18.9 seconds to 9.5 at the cell limit, 20.9 to 9.2
  at the column limit, 10.7 to 5.5 for the realistic workbook.

**What they do not say.** These "before" figures are far below GR-352's 989
MiB, and that is GR-352A's doing rather than this slice's: the files that
produced the large figures are refused by the safety pass on both sides of
this comparison. What GR-352B removed is the dependence -- the analysis no
longer costs in proportion to the file -- and the one case the envelope did
not cap, which is the sample's own amplification above.

**And a workbook at the edge of the envelope is still about nine seconds.** It
no longer holds the event loop, and it is still a request that takes nine
seconds, during which the interpreter lock is shared with every other. The
safety pass walks the sheet and the inspection walks it again. IMPORT-GAP-018.

## How it is proved

- **Agreement**, by comparison. Every file in `test_inspection.py` is handed to
  the canonical reader and to the inspection, in five combinations of sample
  and ceiling, and the answers compared whole; a refusal has to be the same
  sentence. Twenty-two CSVs, twelve workbooks `openpyxl` wrote, thirty-one
  written by hand for the shapes it does not write, and eighty from a seeded
  generator.
- **The routes**, by the same comparison one level up. The body `analyse` had
  at `b24a72d` is kept verbatim in `tests/unit/test_import_inspection.py` as the
  reference, for an accounts-shaped and a contacts-shaped target, and the
  response's fields are pinned as a set.
- **Neither reader is reached**, by replacement: `load_workbook`,
  `read_workbook` and the whole-file `decode` are swapped for something that
  fails the test, and both routes are called. A second test shows the
  replacement *is* reached by the old analysis.
- **The safety pass is first**, by replacement again: the inspection is swapped
  for a failure, an unsafe file is refused without reaching it, and a safe file
  reaches it.
- **Memory**, two ways. `tracemalloc` on every platform, while the string table
  is many times what may be kept. And
  `tests/unit/test_import_inspection_memory.py`, Linux only, which runs
  `analyse` in a process of its own on files at each edge of the envelope,
  asserts the peak rose less than 16 MiB, asserts four times the file is not
  four times the memory, and asserts the canonical reader on the same file
  costs many times more -- without which a small figure could be a harness that
  measures nothing.
- **Mutation.** Sixteen wrong edits were made to a generated product on
  2026-10-01, one at a time, and each turned the suite red: the thread wrapper
  run inline; the mapping route asking for a preview; the analysis calling the
  workbook reader again; the sample's strings taken from the head of the
  table; the safety pass surveying without refusing; the sample's budget
  removed; the sheet walk carrying on past the ceiling; the string table's
  text kept while it is measured; the CSV decoded whole; phonetic runs joined
  in; a date left as a number; a blank row counted; the CSV count taken from
  the sample; a row out of order kept. And two that only the kernel's figure
  can see, in the container: the readers called again from the analysis, and
  the string table held.

**What that is not.** It is not the GR-352 acceptance measurement. The worker
still reads every accepted file through the canonical readers, and nothing
about its memory has changed.

## What this slice leaves, by name

| Left | Where it is tracked |
|------|---------------------|
| The NFR decision: headroom, concurrency, the ratified numbers | IMPORT-DEF-013; F31 |
| The worker reads every accepted file whole, twice, with no bound on how many at once | **Closed 2026-10-02** by GR-352C: a stream, and one import to a process. It is read twice as it was -- once to check, once to commit. IMPORT-DEF-013 for the decision |
| `clean_cell` and the many-column cost in the dry run and the commit | IMPORT-DEF-015, closed 2026-10-02 |
| `source_bytes` awaits a synchronous `S3ObjectStore.get` | IMPORT-DEF-014 |
| A string the pass costs once is copied for every cell that names it, in the worker | IMPORT-DEF-016, closed 2026-10-02 |
| What the reader builds from a sheet that is neither a string nor a cell: merged ranges, links, validations | IMPORT-GAP-020, measured and closed 2026-10-02 |
| The sample's character budget is the implementer's number | IMPORT-GAP-017 |
| A workbook is walked twice by the routes: once by the safety pass, once by the inspection | IMPORT-GAP-018; the worker's as well since 2026-10-02 |
| Nothing bounds how many analyses run at once, each holding its source | IMPORT-GAP-019, closed 2026-10-02 with a provisional number: two |
| The workbook parts `openpyxl` loads eagerly, in the worker | IMPORT-GAP-015, closed 2026-10-02 |
| The AI knowledge reader opens workbooks with no safety pass | IMPORT-GAP-016 |

## Generated products

A generated product has no upstream. The factory pushes to nothing.

- **A product generated after this change** with `data_import` gets all of it.
- **A product generated before it** gets none of it until somebody carries it
  by hand. The files are `koras_import/inspection.py`,
  `koras_import/__init__.py`, `koras_import/safety.py`,
  `koras_import/reading_xlsx.py`, `core/imports.py`, `routers/imports.py`, and
  the tests `test_inspection.py`, `tests/unit/test_import_inspection.py`,
  `tests/unit/test_import_inspection_memory.py` and the changed
  `tests/unit/test_import_preflight.py`. No migration, no setting, no
  environment variable and no page.
- **A product without `data_import`** is unaffected: every file above is inside
  the capability's gate.
- **`docoris`** has changed nothing for this, and its GR-352 stays open until
  the starter's does.
