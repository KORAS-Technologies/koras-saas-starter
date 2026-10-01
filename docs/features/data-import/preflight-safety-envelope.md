# The import safety pass

> **Status, 2026-10-01: GR-352A is built. GR-352 is open, and HIGH.** This
> document describes one slice of a release gate, not its resolution. The
> limits below are provisional, the memory envelope they protect has not been
> ratified by anybody, and the import framework is not claimed to be safe for
> production until every GR-352 acceptance criterion has passed.

## What GR-352 is

GR-352 was raised in the `docoris` gap register on 2026-10-01, from the final
acceptance of that product's move onto this framework, and escalated here as
finding S7-1 because the parser and its limits are the starter's. It says: the
canonical import framework accepts files that can exceed the memory of the
machines it runs on. The API and the worker are each deployed with 512 MB,
which is what both `fly.toml` templates in `profiles/_shared/` declare.

It was then measured in a Linux container, against this repository at
`b953c35`, with the starter's own functions and the kernel's own resident-set
figures. Four results decide everything below.

| What was fed in | Inside every limit of 2026-09-29? | Worker peak |
|-----------------|-----------------------------------|-------------|
| A workbook, 0.3 MiB compressed, 234 MiB of ASCII strings | yes | 406 MiB |
| The same workbook with one emoji in each string | yes | 1,458 MiB |
| A CSV, 63 MiB of ASCII | yes | 305 MiB |
| The same CSV with **one** emoji in the whole file | yes | 494 MiB |
| A CSV, 61 MiB, sixteen million three-character fields | yes | 1,468 MiB |

**Compressed size predicts nothing.** The 1,458 MiB workbook is a 0.3 MiB
upload.

**Uncompressed size is not enough.** The first two rows are the same number of
bytes on disk. CPython stores a string at the width of its *widest* character
-- one byte a character, two, or four -- so a single astral character makes
every other character in that string four bytes wide.

**Cells are a dimension of their own.** The last row is a small file by every
measure of text and the largest of the five in memory.

**The checks came after the cost.** `openpyxl` builds a workbook's whole
shared-string table when it is loaded, before a row is asked for. The CSV path
decoded the whole file into one string before splitting a line. Every limit
this framework had was consulted, where it was consulted at all, after the
thing it was meant to prevent.

## What GR-352A adds

One function, `koras_import.preflight`, called before either reader on every
path that parses a source. It streams the file, counts what memory actually
depends on, and stops at the first limit crossed.

```
source bytes  →  safety pass  →  PASS  →  the reader that was always there
                      │
                      └─ refused, with a code and a sentence; nothing was loaded
```

It decides nothing about the data. No value is converted, trimmed or
reinterpreted; the answer is only whether the existing reader may be called.

### The result

`survey` returns a `Preflight` and never raises a refusal; `preflight` is the
same call, raising `PreflightRefused` when the source is not safe. One shape
for both formats:

| Field | Meaning |
|-------|---------|
| `format`, `source_bytes` | What was handed in |
| `uncompressed_bytes` | The zip directory's declared total; `None` for a CSV |
| `decoded_string_bytes` | Estimated string storage, by the formula below |
| `widest_character` | 1, 2 or 4: bytes a character of the widest text seen |
| `cells`, `columns` | Counted from the file, never from a declaration in it |
| `rows` | Data rows by the reader's own rule: not the header, not a blank row |
| `encoding` | What the CSV decoded under; `None` for a workbook |
| `refusal` | A code, a sentence, the limit and how far the count had got |

When `refusal` is set the counts are lower bounds: the scan stops at the first
limit crossed rather than measuring how far past it the file goes.

### What a string costs

```
decoded_cost(characters, width) = 64 + characters × width
width = 1   every character below U+0100   (ASCII, Latin-1)
        2   any character below U+10000    (the rest of the BMP, CJK)
        4   any character at or above it   (astral: emoji and beyond)
```

The width is the string's, not the character's. `"a" * 1000 + "😀"` is costed
at four bytes for each of its 1,001 characters, because that is how it is
stored. The 64 covers the object's header and terminator on CPython 3.12 and
later. This is an estimate of string storage and deliberately not of process
memory: for files that are mostly text GR-352 measured resident memory at
between about 1.5 and 4 times this figure, depending on the reader and the
shape, and for files that are mostly cells the figure says almost nothing --
which is why cells are counted separately. Turning any of these into resident
memory is the NFR decision, not arithmetic for this module. The tests compare the formula
against `sys.getsizeof` rather than against itself.

**What counts as one string differs by format, because the readers differ.**

- *A workbook.* Each shared-string item and each inline string is a string of
  its own; a rich-text item is one logical string across its runs, at the
  width of its widest run. The sum is over all of them.
- *A CSV.* The whole file is one string, at the width of the widest character
  anywhere in it, because that is what the reader this guards will build. A
  63 MiB ASCII file with a single emoji is costed at 252 MiB. That is
  pessimistic about the file and accurate about the reader; when the reader
  stops decoding the file whole -- GR-352B -- this term should become a sum
  over lines.

### The workbook pass

`zipfile` and `expat`, and not `openpyxl`. No tree is built, so memory does not
grow with the workbook's text.

1. **Entries are counted in the raw bytes** before the archive is opened.
   `zipfile` builds an object for every directory entry, and trusts the
   directory's size rather than its count field, so 400,000 empty entries -- a
   33 MiB file -- cost about 180 MiB and seventeen seconds before any other
   check can run. Measured while building this slice.
2. **The directory checks that were already there**: a workbook part must
   exist, a macro project is refused, the declared uncompressed total is
   summed and refused past its ceiling.
3. **Every part is recognised by its root element, not its name.** A string
   table is a part whose root is `sst`, wherever the workbook keeps it. A scan
   that trusted `xl/sharedStrings.xml` would be walked around by renaming one
   file.
4. **String tables are streamed**, costing each item as its text arrives -- so
   one enormous string is refused partway through it -- and keeping one byte
   per item, recording only whether it is empty. Nothing else is retained.
5. **The sheet the reader will read is streamed**: `Data`, or the first
   worksheet, resolved from the workbook's own index. Cells are counted as they
   are met. The column is taken from each cell's reference -- a single cell at
   `ZZ1` is 702 columns wide whatever `<dimension>` claims -- and by position
   where a writer omitted references. Inline strings, cached formula strings
   and the text of formulas are costed like shared ones.
6. **A part that declares a document type refuses the workbook.** No workbook
   part has one, and one that does could declare entities.
7. **A token that never ends is refused.** `expat` hands text over as it
   arrives but holds an attribute value or a comment until it closes; more than
   a megabyte of input producing no parser event is that, and it is refused
   before it becomes a string.

Only the sheet that will be read is counted, so a workbook is not refused for a
lookup sheet nobody opens. If the workbook's index cannot be followed, every
worksheet is counted, which can only refuse more.

### The CSV pass

The file is decoded 256 KiB at a time with an incremental decoder, in the
reader's own encoding order: `utf-8-sig` strictly, then `cp1252` strictly, then
`latin-1`. No string the size of the file exists during the pass. Lines are
split on the same boundaries `str.splitlines` gives the reader and fed to the
same `csv` reader, so fields, columns and rows are counted by the rules the
import itself uses.

A refusal met under a strict encoding is only believed once the rest of the
file is known to be valid in that encoding. Otherwise four bytes that happen to
form an emoji in UTF-8, in a file the reader will read as `cp1252`, would be
costed as an astral character that never exists.

### Rows

`max_rows` is optional in the envelope, and the two callers differ on purpose.

- **The dry run and the commit ask for it.** Before 2026-10-01 they read
  `max_rows` rows of a longer file and said nothing about the rest; they now
  refuse it.
- **The analysis does not.** It has its own answer -- `over_ceiling` in a 200,
  which the mapping route turns into a refusal -- and a route that answered 200
  for a file that threatens nothing should not start answering 422.

A row is what the reader says it is: the header is not one, a blank row is not
one, and a workbook cell pointing at an empty shared string is empty. The count
agrees with the reader's own on every file in the suite. It can differ in one
direction only, toward counting more, and only for shapes the scan cannot
decide -- two string tables in one workbook, a cell whose index is not a
number.

## The limits

`koras_import.SafetyLimits`, constructed once in `core/imports.py` as
`SAFETY_LIMITS` and used by the routes and the worker alike.

| Limit | Default | Standing |
|-------|---------|----------|
| `max_source_bytes` | 64 MiB | **Existing.** IMP-02, 2026-09-19. Unchanged |
| `max_uncompressed_bytes` | 256 MiB | **Existing.** ADR 0012 D12. Unchanged |
| `max_rows` | the target's `max_rows` | **Existing.** Unchanged in meaning |
| `max_decoded_string_bytes` | 64 MiB | **Provisional**, GR-352 |
| `max_cells` | 1,000,000 | **Provisional**, GR-352 |
| `max_columns` | 256 | **Provisional**, GR-352 |
| `max_archive_entries` | 4,096 | **Provisional**, GR-352 |

**The four provisional numbers are safety guardrails, not the supported
import envelope.** They were proposed by the implementer and approved by the
owner on 2026-10-01 for this slice, to keep known unsafe workloads from
reaching the canonical parsers. They are not NFR-ratified. The final limits
need the GR-352B and GR-352C measurements and approval by the NFR owner --
OD-22 in `docoris`'s terms. How each was reached:

- *Decoded strings, 64 MiB.* Set equal to the source ceiling on purpose, so no
  one-byte-wide CSV that was accepted before is refused by it. What it newly
  refuses is amplification: a workbook whose strings decompress past it, and
  text made two or four bytes wide by its widest character.
- *Cells, 1,000,000.* GR-352 measured about 100 bytes of worker memory a cell.
  **This intentionally refuses some files the starter accepted before.** At
  the default 50,000 rows it is twenty populated cells a row: a 50,000-row
  file with more than that was accepted on 2026-09-29 and is refused as of
  2026-10-01. It is a deliberate safety restriction pending NFR ratification,
  approved as such, and not a side effect.
- *Columns, 256.* Far above any declared target and the width of a pre-2007
  spreadsheet. GR-352's many-column cases were also its slowest.
- *Entries, 4,096.* A workbook has tens.

**What they do not establish.** Of the inputs GR-352 measured, the largest
these defaults still accept is the 63 MiB ASCII CSV, at 305 MiB in a worker --
inside 512 MB with little to spare and no stated headroom. Nothing at the new
cell limit has been measured at all. Whether that is acceptable, what the
headroom must be, and what the concurrency assumption is are the **NFR
decision GR-352 is waiting on**. It belongs to Platform/NFR architecture, not
to whoever writes the parser. When it is taken, these four defaults are
replaced by its numbers and the measurement is repeated against them.

A product that has measured its own envelope replaces `SAFETY_LIMITS` in its
own `core/imports.py`. There is no environment variable and no setting: a
safety limit an operator can raise in a dashboard is not one.

## Refusal

`PreflightRefused` is a `ReadRefused`. Every caller that already answered one
answers this without changing: the routes with a 4xx and the worker with a
failed run carrying the sentence. Nothing a person reads names a parser, a
library or an exception.

| Engine code | API answer |
|-------------|-----------|
| `import.preflight.source_too_large` | 413 `import_file_too_large` |
| `import.preflight.uncompressed_too_large` | 413 `import_file_too_large` |
| `import.preflight.decoded_too_large` | 413 `import_file_too_large` |
| `import.preflight.too_many_cells` | 413 `import_file_too_large` |
| `import.preflight.too_many_columns` | 413 `import_file_too_large` |
| `import.preflight.too_many_entries` | 413 `import_file_too_large` |
| `import.preflight.too_many_rows` | 422 `import_too_many_rows` |
| `import.preflight.line_too_long` | 422 `import_file_unreadable` |
| `import.preflight.macros` | 422 `import_file_unreadable` |
| `import.preflight.malformed` | 422 `import_file_unreadable` |

The API codes are ones it already had, so no page and no translation changed.
The engine's code is narrower than the API's and is not surfaced to the browser
as of 2026-10-01: a sentence per dimension in three languages is the page's
work and belongs to a later slice.

## Where it is wired

Four functions in `core/imports.py` take a customer's bytes, and all four go
through it.

| Function | Reached by | How |
|----------|-----------|-----|
| `analyse` | `GET /imports/{id}/analysis`, `PUT /imports/{id}/mapping` | CSV: `preflight` before `decode`. XLSX: inside `read_workbook` |
| `check` | the dry run | through `_parse` |
| `examine` | the worker's `validate_run` | through `_parse` |
| `prepare` | the worker's `commit_run` | through `_parse` |

For a workbook the pass is **inside** `read_workbook` rather than asked of its
callers, so there is no way to reach `openpyxl` through the engine without it.
The worker has no reader of its own: it reaches a source only through the
store. One operation runs the pass once.

## How it is proved

- **The order**, by replacement. `openpyxl.load_workbook` and the whole-file
  `decode` are swapped for something that fails the test when reached, and
  every one of the four functions is handed an unsafe file in each format. A
  second test shows the same replacements *are* reached by a file that passes,
  so the guard cannot be vacuous.
- **Mutation.** Six changes were made to a generated product on 2026-10-01 --
  the workbook pass moved after `openpyxl`, the CSV pass removed from the
  analysis, the CSV pass moved after `decode`, width ignored, inline strings
  uncosted, a whole-file decode put back inside the pass -- and each turned the
  suite red.
- **The pass's own memory**, two ways. `tracemalloc`, on every platform, while
  the pass reads several times more text than it may keep. And
  `test_preflight_memory.py`, Linux only, which runs the pass in a process of
  its own on generated inputs that decode to as much as 256 MiB and reads the
  kernel's peak resident set: the eleven cases rose between 0.6 and 4.1 MiB in
  `python:3.12-slim` on 2026-10-01, against a ceiling of 16.

**What that is not.** It is not the GR-352 acceptance measurement. That is the
*reader's* memory under the worst *accepted* input, in the API and in the
worker, against a ratified headroom -- and none of it has been repeated since
this slice changed what is accepted.

## What this slice leaves, by name

| Left | Where it is tracked |
|------|---------------------|
| The NFR decision: headroom, concurrency, the ratified numbers | IMPORT-DEF-013; F31 |
| The API still parses a whole safe file to show 200 rows of it | GR-352B; IMPORT-DEF-013 |
| Worker concurrency, queue topology, an import semaphore, machine size | GR-352C; IMPORT-DEF-013 |
| Re-measuring the readers against the new envelope, on Linux | IMPORT-DEF-013 |
| `source_bytes` awaits a synchronous `S3ObjectStore.get` | IMPORT-DEF-014 |
| Pathological CPU in the synchronous analysis and in `clean_cell` | IMPORT-DEF-015 |
| Workbook parts `openpyxl` loads eagerly that are neither strings nor sheets | IMPORT-GAP-015 |
| The AI knowledge reader opens workbooks with no safety pass | IMPORT-GAP-016 |

The CPU findings are not closed by this. The cell and column limits reduce how
bad the worst case is; they do not make the analysis asynchronous or
`clean_cell` linear, and a file inside the envelope can still hold a request
for tens of seconds.

**The pass has a cost of its own, and it is paid on the same thread.** It is
Python handling one parser event at a time: a 600,000-cell sheet took about
three seconds and a 32 MiB CSV about two, in `python:3.12-slim` on 2026-10-01.
For a workbook that is an extra pass before `openpyxl` makes its own. It is
cheap against what it prevents and it is still synchronous inside an async
route, which is IMPORT-DEF-015's subject and one more reason for GR-352B.

## Generated products

A generated product has no upstream. The factory pushes to nothing.

- **A product generated after this change** with `data_import` gets all of it:
  the module, the wiring, the three suites.
- **A product generated before it** gets none of it until somebody carries it
  by hand. The files are `koras_import/safety.py`, `koras_import/__init__.py`,
  `koras_import/reading_xlsx.py`, `core/imports.py`, `routers/imports.py`, and
  the tests `test_preflight.py`, `test_preflight_memory.py` and
  `tests/unit/test_import_preflight.py`. No migration, no setting, no
  environment variable and no page.
- **`docoris`** carries the framework by its own ADR 0017 and has changed
  nothing for this. Its alignment is its own later work, in its own repository,
  and its GR-352 stays open until the starter's does.
- **`lexveria`** has no `koras-import` package -- checked 2026-10-01 -- so
  there is nothing in it to carry this into.
