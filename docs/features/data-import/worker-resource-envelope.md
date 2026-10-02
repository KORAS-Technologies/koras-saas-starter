# The worker's resource envelope

> **Status, 2026-10-02: GR-352 is CLOSED, verified, and its NFRs are
> ratified.** The owner ratified the resource contract on 2026-10-02, after
> GR-352E merged as `3e73190` and CI, Security and Generator Integration
> passed on that commit. "The ratified resource contract" below is the
> contract; the rest of this document is the account of the slices and the
> measurements it was taken from, left as written. Where a passage below
> calls a number provisional, says the gate is shut or says a row is resolved
> locally, it describes the day it was written and the contract section is
> the correction.
>
> **Closing GR-352 does not make imports ready to switch on.** IMPORT-DEF-014
> is open as of 2026-10-02: a deployed product cannot read an import's source
> from a real bucket, and no product may activate canonical imports against
> real object storage until it is fixed and verified.

## The slices

| | What it bounds | Where |
|-|----------------|-------|
| GR-352A | What a file may be before any reader is handed it | `koras_import/safety.py`; `preflight-safety-envelope.md` |
| GR-352B | What the two API routes cost to show a mapping page | `koras_import/inspection.py`; `bounded-inspection.md` |
| GR-352C | What a dry run and a commit cost the worker, in memory, time and number | `koras_import/streaming.py`, `koras_import/budget.py`, `core/imports.py`, `tasks/imports.py`; this document |
| GR-352E | What may be heavy in a worker at the same time as an import, and how large a scheduled report may be | `koras_worker/heavy.py`, the four tasks that hold it, `core/rebind.py`; this document |

There is no GR-352D in the code: it was the measurement, on 2026-10-02, that
GR-352E answers.

What was left after all four was one decision that was not this repository's:
the limits a product is told it supports. The owner took it on 2026-10-02,
and the next section is what was ratified.

## The ratified resource contract

Ratified by the owner on 2026-10-02. GR-352A, GR-352B, GR-352C and GR-352E
together establish it; no value below was changed by the ratification, and
each is the number the slices were measured against.

**The operational requirement.** "The supported Starter workloads defined by
the import/resource envelope must complete within the configured 512 MiB
process allocation without OOM or swap, while preserving bounded concurrency
through the declared resource gates."

There is no percentage-headroom requirement. The headroom figures in this
document are measured evidence and not a term of the contract.

### Runtime and concurrency

| Term | Ratified value | Where it is declared |
|------|----------------|----------------------|
| Worker memory | 512 MiB | the worker's `fly.toml` template, `memory_mb = 512` |
| API memory | 512 MiB | the API's `fly.toml` template, `memory_mb = 512` |
| Heavy-resource slots | 1 per worker process | `HEAVY_SLOTS`, `koras_worker/heavy.py` |
| Import concurrency | one heavy import per worker process | `IMPORT_SLOTS`, `tasks/imports.py` |
| General worker jobs | `max_jobs = 10` | `WorkerSettings` |
| API analysis slots | 2 per API process | `ANALYSIS_SLOTS`, `core/imports.py` |

The heavy gate covers the canonical import, the cross-provider backup, the
restore and the scheduled CSV, XLSX and PDF delivery. A lightweight job may
run beside a heavy one: the gate is not a job slot.

A request acquires an analysis slot **before** it fetches or retains its
import source, so a request that is waiting holds nothing.

### Time budgets

| Term | Value | Standing |
|------|-------|----------|
| Streaming import work budget | 600 seconds, `WORK_BUDGET_SECONDS` | Ratified 2026-10-02 |
| Import job timeout | 900 seconds, in `koras_import/jobs.py` | Existing arq semantics, recorded and not redefined |
| Ordinary worker job timeout | 300 seconds, `job_timeout` | Existing arq semantics, recorded and not redefined |

Waiting for the heavy gate consumes the queue's timeout for the job that
waits -- 900 seconds for an import, 300 for a cron job. That is
IMPORT-GAP-021, which is open as of 2026-10-02.

### Preview and import limits

| Limit | Ratified value |
|-------|----------------|
| Retained preview or sample characters | 4 MiB of characters, `MAX_SAMPLE_CHARACTERS` |
| Source | 64 MiB |
| XLSX declared uncompressed | 256 MiB |
| Decoded strings | 64 MiB |
| Cells | 1,000,000 |
| Columns | 256 |
| Archive entries | 4,096 |
| Target rows | Product-defined; the Starter default is 50,000 |

### Scheduled reporting

A scheduled delivery carries at most 10,000 rows, as CSV, XLSX or PDF:
`SCHEDULED_DELIVERY_ROW_LIMIT`.

**`EXPORT_ROW_LIMIT = 10,000` is not a universal export maximum.** For an
interactive export through the API it is the threshold at which the
foreground export hands over to the background one, and an export past it
still happens.

### The names in the code

The declarations still say `PROVISIONAL` in their comments, and the default
limits are still exported as `PROVISIONAL_LIMITS`, as of 2026-10-02. The
closure was a documentation change and touched no runtime or template file,
so the wording in the code is one day behind the decision. This section is
the authority on the standing of each number; renaming is a separate change.

That is behavior-neutral naming and documentation debt. It does not reopen
GR-352 and it changes no limit: the ratification stands and this document
is the canonical contract. It is to be cleaned up before the next
canonical-import activation or release work, so that the code's terminology
agrees with the ratified contract. F31 in `docs/FOLLOW_UPS.md` carries the
box.

### Worker evidence

GR-352E, in the product's own worker image, under a 512 MiB limit with no
swap. Two local runs of each pair; the table further down has every figure.

| Scenario | cgroup peak, MiB, run 1 / run 2 |
|----------|--------------------------------:|
| Import and backup | 301 / 303 |
| Import and restore | 302 / 303 |
| Import and scheduled XLSX | 286 / 287 |
| Import and scheduled PDF | 286 / 287 |

Nothing was killed, no swap was used, and a job enqueued after each run was
answered by a healthy worker.

**Before GR-352E, import and backup together peaked at 512 and 499 MiB** --
the limit itself on one run. That is why unrestricted overlap of heavy jobs
was rejected and the gate exists.

The capped memory measurement is local. Remote CI verifies that heavy jobs
exclude one another and does not repeat the measurement under a memory limit.

### API evidence

The canonical GR-352 measurement of the API, recorded here on 2026-10-02
because the final review found it absent from committed documentation.

**What was measured, and where the evidence is.** The repository and
runtime under measurement was Starter commit
`cf17a6e593bf37018cc48ad110215e414d9b1c52`: the API was generated from that
commit and run. The measurement harness and its raw output were session
scratch evidence and are not committed repository artifacts, so the figures
below are the record. The measurement was taken locally and by hand; no CI
run on that commit produced it.

A real generated API process, in a 512 MiB cgroup with no swap, given two
near-limit analyses at once and then a third.

| Measured | Value |
|----------|------:|
| Idle resident set | about 140 to 142 MiB |
| Peak resident set, two analyses | about 254.3 MiB |
| cgroup peak | about 250.8 MiB |
| cgroup headroom left | about 261.2 MiB, 51% |

- The CSV analysis and the XLSX analysis both completed, and their protected
  sections overlapped.
- A third request waited while both slots were held, and its source was
  fetched only after a slot became available.
- No OOM and no swap. The event loop stayed responsive, health was good
  after the run, and the slots returned to 2.

**Supplementary, and not contract evidence.** A second measurement with a
boto3-shaped source peaked at about 280.5 MiB for two analyses and about
296.1 MiB with the third queued. It is recorded for whoever fixes
IMPORT-DEF-014 and does not replace the figures above.

### What the closure does not authorise

GR-352 closing does not enable imports in `docoris` or anywhere else. The
order, as of 2026-10-02:

1. Close the GR-352 resource envelope. Done, 2026-10-02.
2. Fix IMPORT-DEF-014.
3. Repeat the capped source-fetch measurement, because that fix changes how
   a source is fetched.
4. Align and verify `docoris` against the updated Starter framework.
5. Resume OD-12 scanner work, once its own prerequisites are met.

Steps 2 to 5 are not started.

### What stays open

| Row | Standing, 2026-10-02 |
|-----|----------------------|
| IMPORT-DEF-014 | Open. An activation constraint: no product may activate canonical imports against real object storage until it is fixed and verified, and its fix repeats the 512 MiB capped measurement |
| IMPORT-GAP-016 | Open, outside the canonical import envelope. AI knowledge workbook ingestion is a separate resource risk |
| IMPORT-GAP-017 | Open. The 4 MiB budget is ratified; a shortened preview is still not indicated in the response or on the page |
| IMPORT-GAP-018 | Open. The double workbook walk is a latency optimisation |
| IMPORT-GAP-021 | Open. Waiting for the heavy gate consumes the existing arq timeout; no queue or topology change is authorised |
| IMPORT-GAP-022 | Open, product-specific. The envelope excludes the cost of a product's validator, matcher and writer; `docoris` measures its own before its envelope is ratified |
| IMPORT-GAP-024 | Open. The CSV widest-character costing stays conservative on purpose |
| IMPORT-GAP-026 | Open, outside GR-352. The API's background export is unbounded and unmeasured |

### A difference in test counts, explained

The generator suite reported 2,384 tests locally and 2,376 remotely on the
closing verification. The eight are four gitignored `__pycache__/*.pyc`
files under the shared template on the local machine:
`shared-template-parity.test.ts` makes two tests for every file it
discovers. It is a difference in what each environment has on disk, and no
tracked file is missing remote coverage. No test was changed for it;
excluding ignored and bytecode files from parity discovery is a possible
hygiene change for later.

## What GR-352C found

Measured first and changed second. Every figure below is the kernel's peak
resident set (`VmHWM`) for a process of its own, in `python:3.12-slim`, on
2026-10-01 and 2026-10-02, against this repository at `1fefbc3` -- which has
the safety pass of GR-352A in front of everything. Each file is generated;
none is committed. The process imports what a worker imports before the
baseline is read, which was 73 MiB.

Every file in this section is **accepted by the safety pass** unless the table
says otherwise. That is the point of them.

### 1. A file was held three and four times over

The store's `_parse` returned every row of the file in a list, and its callers
went through that list two or three times.

- *A CSV*: the uploaded bytes; the whole file decoded into one string; that
  string again as a list of lines; and every row as a dictionary of cells.
- *A workbook*: the bytes; `openpyxl`'s string table; every row as a
  dictionary.
- *A commit*: the rows, then a normalised dictionary for every row beside
  them, then a **copy** of every one of those dictionaries for the writer --
  three structures a row, resident together.

| File | Size | Dry run before | Commit before |
|------|-----:|---------------:|--------------:|
| CSV, 50,000 rows by 4, 290-character cells | 57 MiB | 331 | 330 |
| CSV, 50,000 rows, a 1,190-character unique key | 57 MiB | 323 | 323 |
| CSV, 2,000 rows of one 31,900-character cell | 61 MiB | 317 | 317 |
| CSV, every field ending in an astral character | 15 MiB | 298 | 298 |
| CSV, ASCII but for one astral character | 15 MiB | 207 | 207 |
| CSV, 49,900 rows by 20: a million cells | 7.9 MiB | 181 | 190 |
| Workbook, 49,900 rows by 20 numbers: a million cells | 4.4 MiB | 162 | 177 |
| Workbook, 60,000 unique strings at the decoded budget | 0.9 MiB | 166 | 165 |

### 2. IMPORT-DEF-016: where a string named many times is copied

GR-352B found that a shared string the safety pass costs once could be
materialised for every cell naming it, and left the worker unmeasured. It is
two defects in the worker, in two different places, and `openpyxl` is neither.

**In the reader.** `openpyxl` hands every cell naming a shared string the
same string object. `row_from` then cleaned each cell, and cleaning a string
that needs it -- a trailing space is enough -- makes a new string. One
32,000-character string with a trailing space:

| Workbook | Size | Cells | Read | Result |
|----------|-----:|------:|-----:|--------|
| 2,000 rows by 20 | 0.12 MiB | 40,020 | 1,236 MiB | 99 seconds |
| 4,000 rows by 20 | 0.23 MiB | 80,020 | 2,400 MiB | 252 seconds |
| 49,900 rows by 20 | 3.1 MiB | 998,020 | -- | killed by the kernel at an 8 GiB limit |

A *clean* string named by a million cells did not grow at all -- cleaning it
returns the string itself -- and took more than 1,500 seconds instead, which
is finding 4.

**In the duplicate index.** `match_key` lower-cases each part of a row's key,
and `str.lower` always answers a new string. A two-part key whose second part
is one long string every row carries:

| Workbook | Size | Read | Validate | 
|----------|-----:|-----:|---------:|
| 4,000 rows | 0.07 MiB | 76 MiB | 198 MiB |
| 50,000 rows | 0.86 MiB | 97 MiB | 1,628 MiB |

The reader is innocent in that one: 97 MiB after the read, 1,628 after
validation. The copies were in `validate`'s own dictionary of keys seen, and
would have been made a third time by `keys_of` had the first two fitted.

Matching and the writer added nothing in either case. The prediction costs a
set of the matcher's answer; `rows_from` copied dictionaries, whose values are
shared.

### 3. IMPORT-GAP-020 and IMPORT-GAP-015: what `openpyxl` builds beside the rows

The safety pass counts strings and cells. `openpyxl`, asked for a sheet's
rows, also builds everything else in the sheet as it reaches the end of it,
and everything else in the workbook when it is loaded. None of it is a cell.
Each of these is a small data sheet of 1,000 rows with something beside it.

| What is beside the rows | Size | Worker before | Each one costs |
|-------------------------|-----:|--------------:|---------------:|
| 100,000 merged ranges | 0.05 MiB | 138 MiB | |
| 1,000,000 merged ranges | 0.22 MiB | 710 MiB | about 640 bytes |
| 4,000,000 merged ranges | 0.80 MiB | 2,620 MiB | |
| 1,000,000 hyperlinks | 0.34 MiB | 757 MiB | about 680 bytes |
| 1,000,000 data validations | 0.60 MiB | 1,419 MiB | about 1,350 bytes |
| 1,000,000 conditional formats | 0.78 MiB | 1,365 MiB | about 1,290 bytes |
| 1,000,000 column definitions | 0.22 MiB | 158 MiB | about 85 bytes |
| 10,000,000 rows with no cell in them | 0.28 MiB | 937 MiB | about 86 bytes, and 136 seconds |
| A stylesheet of 1,000,000 cell formats | 0.38 MiB | 837 MiB | about 760 bytes |
| 1,000,000 defined names | 2.6 MiB | 845 MiB | about 770 bytes |
| A 200 MiB theme part | 0.90 MiB | 476 MiB | twice its size |
| Another sheet holding one 240 MiB cell | 1.1 MiB | 319 MiB | its size |
| Ten other sheets of 160,000 cells each | 7.0 MiB | 83 MiB | nothing held, 15 seconds |
| 2,000 other sheets of one cell | 0.56 MiB | 79 MiB | nothing |

The last four are the dimension scan: a worksheet that declares no
`<dimension>` is walked to the end of its data when the workbook is loaded,
every sheet and not only the one being read. It holds one cell at a time, so
many sheets cost time and one enormous cell in a sheet nobody asked for costs
its size.

**The only thing bounding any of this was the 256 MiB uncompressed ceiling**,
which is why none of them is larger than it is. Text in the data sheet that
is not in a cell -- a 200 MiB header -- is refused by the safety pass, which
costs it as text wherever it stands.

### 4. IMPORT-DEF-015: where the time went

Two places, and neither was the parser.

**`clean_cell`.** It asked `char in _CONTROLS` of every character from a
generator: a Python-level step a character. 1.7 milliseconds for one
32,000-character cell; a million cells naming such a string is half an hour,
measured as a job still running at 1,500 seconds.

**A lookup for every cell.** `ResolvedMapping.fields` builds a dictionary
every time it is read and `ImportTarget.spec` walks the field list. Validation
read the first once a row and the second once a cell, the match key read both
again, and normalising read both a third time: work that grows with the
square of the column count. A CSV of 3,900 rows by 256 mapped columns took
7.2 seconds to validate and 12.9 to prepare, against 1.0 to read.

### 5. The queue's timeout did not stop anything

`VALIDATE_RUN` and `COMMIT_RUN` declare 900 seconds, and the queue enforces
it the only way it can: by cancelling the coroutine. `store.examine` and
`store.prepare` were called inline, in the coroutine, with no `await` in
them. Measured by doing to the handler's read exactly what the queue does,
with a **two-second** timeout:

| File | Timeout reported after | The read ended after | Longest stall of the event loop |
|------|-----------------------:|---------------------:|--------------------------------:|
| Workbook, a million numeric cells | never: the job finished, at 40.9 s | 40.9 s | 41.0 s |
| CSV, a million cells in 60 MiB | never: the job finished, at 14.9 s | 14.9 s | 15.0 s |

The timeout was not late. It did not happen: the coroutine never reached a
point where a cancellation could be delivered, so the job ran to its end and
reported success. And for the whole of it the worker's event loop was held --
no other job, no heartbeat, and not the sweep that sends owed notifications
every minute.

### 6. Nothing bounded how many imports ran at once

`WorkerSettings.max_jobs` is 10 and nothing else was said. An import was
never singled out. Because the read held the event loop, two imports could
not *parse* at the same moment -- an accident, and the only limit there was.
Their memory still overlapped: the first job kept its rows while it awaited
the database, and the second read its file beside them.

## What GR-352C changed

```
before:  bytes → safety pass → the reader → every row, in a list → validate → match → write
                                             (on the event loop, to the end, however long)

after:   bytes → safety pass → a stream of rows → validate, and keep of a row what is needed
                 └────────── on a thread, asked as it goes whether to stop ───────────┘
                 one import to a process; every other job runs beside it
```

### The reader: `koras_import.open_rows`

`streaming.py`. It yields `Row` after `Row` and holds what the safety pass
already bounds.

- **A CSV** is decoded 256 KiB at a time in the encoding the safety pass
  settled on, split on `str.splitlines` boundaries, and put through the same
  `csv` wrapper, `header_from` and `row_from`. No string the size of the file
  exists.
- **A workbook** is read with `zipfile` and `expat`, by the sheet walk the
  bounded inspection of GR-352B was built from and proved against `openpyxl`,
  asked for every row instead of a sample. Three parts are opened: the string
  table and the sheet the safety pass scanned and named, and the stylesheet,
  streamed for which formats are dates. `load_workbook` is not called.
- **A shared string is held once**, named by index until a row is built, and
  cleaned once when the table is loaded rather than once a cell.
- **The safety pass is inside it**, by the arrangement `read_workbook` and
  `inspect_source` already have.

`read_workbook` and `decode` stay in the package as the description of what a
file's rows are. Nothing in the store calls either.

### One pass: `validate` reads a stream

`validate` always took an iterable and read it once. What made the list
necessary was everything after it: the matcher's keys and the prediction read
every row a second and third time, and the commit normalised every row from
the list. Each now takes what it needs **while the row is there**, through
`validate`'s `each`:

- **A dry run** keeps, of each row the validator passed, its match key, its
  row number and the one cell a rejection quotes -- `matching.Candidates`.
  The key is the same tuple the duplicate index holds, so it is kept once.
  `request_from` and `predict_from` answer from that what `request_for` and
  `predict` answered from the rows.
- **A commit** builds the writer's dictionary from each row as it passes.

### The duplicate index: long key parts are held once

`validate` interns a key part longer than 64 characters, so a part every row
carries is one string. Short parts are left alone. No hash stands in for a
key, and the matcher is handed exactly what it was handed before: every
distinct key, canonical and case-folded, in file order.

### The writer: one dictionary a row

The writer's contract is unchanged -- every row of the run, at once, in file
order, inside the caller's transaction -- so every row's dictionary is
resident when the writer is called. That is the commit's own cost and it
stays. What went is the two structures that used to be resident beside it.
`rows_from` gained `owned`: the worker built these dictionaries for this one
request and reads none of them again, so they are handed over rather than
copied.

### `clean_cell`, and a mapping looked up once

`clean_cell` answers what it always answered -- `test_equivalence.py` holds
it to the implementation it replaced over every awkward character and over
generated text -- by asking `str.isprintable` first and a compiled pattern
second. A mapping and a target's specifications are looked up once for a
file, in `mapping._plan`, and not once a cell.

### Off the event loop, under a budget that can stop it

`tasks/imports.py` runs `store.examine` and `store.prepare` on a thread. The
loop keeps turning.

A thread cannot be cancelled, so the read is given a `koras_import.WorkBudget`
and asks it: the safety pass once a chunk, the reader once a chunk and every
256 rows. It raises when the time is spent, or when the handler has been
cancelled and has told it so.

- `WORK_BUDGET_SECONDS` is 600, below the queue's 900 on purpose: this is the
  limit that can end the work and say why. A run past it fails with a
  sentence, through the path every other refusal takes.
- When the queue's timeout or a shutdown cancels the job, `_off_loop` cancels
  the budget, waits for the thread to have stopped, and the run is recorded as
  failed by `_abandon` -- before this it stayed `validating` or `committing`
  for ever.
- `store.abandon` names the status it expects in its `where`. A job cancelled
  while its one transaction was on its way to the database does not know
  whether it landed, and an unguarded update would say `failed` over an
  import that happened.

The same two-second timeout, after:

| File | Timeout reported after | The read ended after | Longest stall of the event loop |
|------|-----------------------:|---------------------:|--------------------------------:|
| Workbook, a million numeric cells | 2.04 s | 2.04 s | 0.06 s |
| CSV, a million cells in 60 MiB | 2.04 s | 2.04 s | 0.07 s |

**What the budget does not interrupt** is one call into the standard library:
a 256 KiB chunk through the XML parser, one record through `csv`. And it does
not reach the product's own code -- a target's `validator`, its `matcher`, its
`writer`. The matcher and the writer are coroutines on the database and the
queue's timeout does reach those.

**Three clocks, and they are not one another.**

| Clock | Value | What it covers | What happens when it runs out |
|-------|-------|----------------|-------------------------------|
| The queue's timeout for the job | 900 s, declared in `koras_import/jobs.py` | The whole job, from the moment the worker takes it: waiting for the slot, reading, the database, the product's own code | The queue cancels the coroutine. The read is told to stop, and the run is recorded as failed by `_abandon` |
| The work budget | `WORK_BUDGET_SECONDS`, 600 s | The engine's own reading and checking of the file -- the safety pass and the stream -- and nothing else. It starts when the job holds the slot | The run fails with the budget's sentence, through the ordinary refusal path |
| The wait for the slot | no limit of its own | An import behind another, holding nothing | Nothing; it is inside the first clock, which is IMPORT-GAP-021 |

**The 600 seconds do not bound a product's code.** A target's `validator` is
called from inside the read, between two questions, and is not itself asked;
its `matcher` and its `writer` run after the read has ended, when the budget
is no longer being asked at all. What bounds those is the queue's timeout and
nothing narrower, which is IMPORT-GAP-022 and is open as of 2026-10-02.

### One import to a process

`IMPORT_SLOTS` is 1, and it is how many imports hold the worker's heavy gate
at once. The gate is held by `validate_run` and `commit_run` from their first
statement to their last -- taken **before** the source is fetched, so an
import that is waiting holds no file. The worker's ten job slots are
unchanged. A second import waits; it is not refused.

As GR-352C built it this was a semaphore of the import's own and every other
job ran beside an import. Since GR-352E it is a limit inside the gate the
worker's other heavy jobs share, which is its own section below.

It is per process, which is the scope the memory has. No queue was added and
no topology changed.

**It is not a limit on the estate.** Two worker machines read two imports at
once, one each; ten machines read ten. Nothing here says how many imports a
product runs, only how many one process holds in memory, which is the
question a 512 MiB machine asks. As GR-352C left it, it covered imports
alone, and what the other nine job slots were doing beside one was
IMPORT-GAP-023 -- which GR-352E measured and resolved on 2026-10-02, and
which closed that day once the merge commit had passed remotely.

### Memory handed back

When an import ends its strings are freed to the allocator, which keeps the
pages. `give_back`, in `koras_worker/heavy.py`, calls the C library's
`malloc_trim` before the gate is let go -- for every job that holds it, since
GR-352E, and not for an import alone. Without it the capped worker's resident
memory stayed where its largest import had left it.

**It is a courtesy to the machine and not a step of the job.** `malloc_trim`
is glibc's. Where the library is not there under that name -- Windows, macOS,
an image built on another C library -- or is there without the call, it does
nothing, and an import is as correct as it was and holds more than it needs
afterwards. No allocator was added as a dependency.
`tests/unit/test_import_worker_envelope.py` runs both jobs to their end with
the library made unavailable, and `tests/unit/test_worker_heavy_gate.py` asks
the call itself.

### The API: how many sources at once

IMPORT-GAP-019. An analysis costs under 7 MiB over its file, and the file is
fetched whole -- up to 64 MiB -- before the inspection starts. Nothing bounded
how many requests did that together. `core/imports.analysis_slot` is a
semaphore of `ANALYSIS_SLOTS`, which is 2, held by both routes from before
the fetch until the bytes are let go. A request past it waits holding
nothing.

Two is 128 MiB of sources at the worst, in a 512 MB process. Per process; a
second API machine has two of its own. Nothing distributed was built, and
this is not a limit on how many analyses a product runs at once: it is how
many sources one API process has in hand.

## What it costs now

The same files, the same harness, this slice.

### A dry run and a commit, in a process of their own

| File | Size | Cells | Dry run before | after | Commit before | after |
|------|-----:|------:|---------------:|------:|--------------:|------:|
| Workbook, realistic: 50,000 rows by 8 | 2.9 | 400,008 | 127 | 100 | 133 | 119 |
| Workbook, 49,900 rows by 20 numbers | 4.4 | 998,020 | 162 | 92 | 177 | 157 |
| Workbook, 60,000 unique strings, ASCII | 0.9 | 60,003 | 166 | 163 | 165 | 163 |
| Workbook, 60,000 unique strings, astral | 0.6 | 60,003 | 168 | 166 | 167 | 166 |
| Workbook, 60,000 inline strings, ASCII | 0.9 | 60,003 | 166 | 102 | 165 | 162 |
| Workbook, 3,900 rows by 256 numbers | 4.8 | 998,656 | 151 | 82 | 177 | 152 |
| Workbook, 49,900 rows by 20 formulas | 8.0 | 998,020 | 173 | 97 | 186 | 168 |
| CSV, realistic: 50,000 rows by 8 | 5.4 | 400,008 | 135 | 96 | 139 | 127 |
| CSV, 50,000 rows by 4, long cells | 57.0 | 200,004 | 331 | 168 | 330 | 234 |
| CSV, a 1,190-character unique key | 57.2 | 100,002 | 323 | 209 | 323 | 268 |
| CSV, 2,000 rows of one long cell | 60.9 | 2,001 | 317 | 198 | 317 | 260 |
| CSV, every field ending in an astral character | 15.4 | 200,004 | 298 | 140 | 298 | 201 |
| CSV, ASCII but for one astral character | 15.1 | 200,004 | 207 | 113 | 207 | 139 |
| CSV, 49,900 rows by 20 | 7.9 | 998,020 | 181 | 95 | 190 | 166 |
| CSV, 3,900 rows by 256 | 3.8 | 998,656 | 156 | 80 | 175 | 151 |
| CSV, fifty thousand rows of one key | 44.7 | 200,004 | 280 | 125 | 280 | 189 |

Sizes and peaks in mebibytes; the baseline is 73. Stage by stage, for the dry
run before: the safety pass added 1 to 6 MiB; the **read** was nearly all of
the rest; validation added the duplicate index -- 20 MiB for 60,000 long
unique keys, 5 for fifty thousand short ones, and all of it for the two-part
key; matching added at most 1. After, reading and validating are one stage
and matching adds nothing to it. For the commit: preparing was the peak
before and after, and building the request and calling the writer added
between nothing and 3 MiB in both.

**What a dry run holds now** is the file, a workbook's string table, and the
index -- about 265 bytes for each row the validator passed. **What a commit
holds** is those and one dictionary a row: 79 to 129 bytes a cell for short
values.

**What did not improve, and should not have:** a workbook of unique strings
at the decoded budget. The string table is the file's text, held once, before
and after.

### The files that were not safe

| File | Size | Before | After |
|------|-----:|-------:|------:|
| One long string with a trailing space, 40,020 cells | 0.12 | 1,237 | 76 |
| The same, 80,020 cells | 0.23 | 2,400 | 76 |
| The same, 998,020 cells | 3.1 | killed at 8 GiB | 91 dry, 112 commit |
| One clean long string, 998,020 cells | 3.1 | over 1,500 seconds | 92, in 21 seconds |
| A two-part key with a long part, 4,000 rows | 0.07 | 198 | 76 |
| The same, 50,000 rows | 0.86 | 1,631 | 91 dry, 99 commit |
| 1,000,000 merged ranges | 0.22 | 710 | 76 |
| 4,000,000 merged ranges | 0.80 | 2,620 | 76 |
| 1,000,000 hyperlinks | 0.34 | 757 | 76 |
| 1,000,000 data validations | 0.60 | 1,419 | 76 |
| 1,000,000 conditional formats | 0.78 | 1,365 | 76 |
| 1,000,000 column definitions | 0.22 | 158 | 75 |
| 10,000,000 rows with no cell | 0.28 | 937 | 76 |
| 1,000,000 defined names | 2.6 | 845 | 78 |
| A 200 MiB theme part | 0.90 | 476 | 75 |
| Another sheet holding one 240 MiB cell | 1.1 | 319 | 75 |
| A stylesheet of 1,000,000 cell formats | 0.38 | 837 | refused, with a sentence |

### Time

| File | Dry run before | after | Commit before | after |
|------|---------------:|------:|--------------:|------:|
| CSV, 3,900 rows by 256 | 9 s | 2 s | 13 s | 3 s |
| Workbook, 3,900 rows by 256 numbers | 38 s | 23 s | 49 s | 25 s |
| Workbook, 3,900 rows by 256 short strings | 54 s | 25 s | 47 s | 29 s |
| Workbook, a million numeric cells | 29 s | 22 s | 28 s | 27 s |
| Workbook, one clean long string in a million cells | over 1,500 s | 21 s | over 1,500 s | 23 s |
| Workbook, 10,000,000 rows with no cell | 136 s | 75 s | 145 s | 80 s |

On an eight-core development machine, each including the safety pass. A
workbook at the cell limit is still twenty seconds and more of one core: the
safety pass walks the sheet and the reader walks it again. That is what the
budget is for, and it is IMPORT-GAP-018's subject for the worker as it
already was for the routes.

## Under a 512 MiB limit

Both `fly.toml` templates in `profiles/_shared/` declare `memory_mb = 512`,
for the API and for the worker; that was read from the files on 2026-10-02
and not from a deployed machine.

The figures above are a process that does nothing else. This is the product's
own worker: `koras_worker.worker.WorkerSettings` unchanged, run by `arq`
against a real Redis and a real PostgreSQL with row-level security on, every
cron job registered, ten job slots, in a container limited to 512 MiB of
memory **and 512 MiB of memory plus swap** -- so no swap at all -- and one
CPU. Two things were supplied because a generated product has neither: an
object store that reads the fixture from disk, since IMPORT-DEF-014 keeps a
real bucket unreachable and was not touched, and targets with a writer that
inserts a row for every row and a matcher. Jobs were enqueued through
`koras_queue` from a second container. The worker sampled its own cgroup and
`/proc` five times a second.

Each file was dry-run and then committed. Idle, the worker was 66 MiB
resident.

| File | Size | Dry run, peak RSS | Commit, peak RSS | Rows written |
|------|-----:|------------------:|-----------------:|-------------:|
| CSV, a 1,190-character unique key | 57.2 | 275 | **335** | 50,000 |
| CSV, a million cells in 60 MiB: both edges at once | 60.1 | 221 | 309 | 49,999 |
| CSV, 50,000 rows by 4, long cells | 57.0 | 206 | 261 | 50,000 |
| Workbook, 60,000 unique strings that do not compress | 33.9 | 264 | 264 | 20,000 |
| CSV, every field ending in an astral character | 15.4 | 175 | 245 | 50,000 |
| Workbook, 60,000 unique strings, astral | 0.6 | 243 | 239 | 20,000 |
| Workbook, 49,900 rows by 20 formulas | 8.0 | 164 | 220 | 49,900 |
| CSV, 49,900 rows by 20 | 7.9 | 178 | 208 | 49,900 |
| Workbook, 3,900 rows by 256 numbers | 4.8 | 166 | 207 | 3,900 |
| Workbook, 49,900 rows by 20 numbers | 4.4 | 178 | 199 | 49,900 |
| Workbook, one long string with a trailing space, a million cells | 3.1 | 158 | 165 | 49,900 |
| Workbook, a two-part key with a long part, 50,000 rows | 0.9 | 163 | 160 | 50,000 |
| Workbook, 4,000,000 merged ranges | 0.8 | 158 | 158 | 1,000 |
| Workbook, 1,000,000 data validations | 0.6 | 156 | 156 | 1,000 |
| Workbook, 10,000,000 rows with no cell | 0.3 | 175 | 159 | 1,000 |
| Workbook, realistic: 50,000 rows by 8 | 2.9 | 121 | 151 | 50,000 |

Twenty-one files in all, every one of them completed, every commit wrote
every row.

| | With memory handed back | Without |
|-|------------------------:|--------:|
| The worker's peak resident set, over the whole run | **340 MiB** | 400 MiB |
| The cgroup's own maximum | 320 MiB | 379 MiB |
| Memory plus swap, maximum | 320 MiB | 379 MiB |
| Swap used | none | none |
| Out-of-memory kills | 0 | 0 |
| Resident when the run ended, with nothing in hand | 166 MiB | 340 MiB |
| A job enqueued and answered afterwards | yes | yes |

"Without" is this slice before memory was handed back, which is how that
came to be added: the worker's resident memory stayed where its largest
import had left it.

**Two imports enqueued together** -- the 60 MiB CSV twice -- finished one
after the other, at 5.0 and 7.5 seconds, with a peak of 216 MiB: one import's
worth. A trivial job enqueued while both were in the worker's hands was
answered in 1.0 second. That the two were never read at the same moment is
asserted by `tests/unit/test_import_worker_envelope.py`, which counts, rather
than inferred from these timings.

**A stylesheet of a million cell formats** failed its run with "the file
could not be read as a workbook", and the worker went on to the next job.

### The same limit, the code before this slice

`1fefbc3`, the same container, the same harness.

| File | Size | What happened |
|------|-----:|---------------|
| CSV, 50,000 rows by 4, long cells | 57.0 | Completed, at 364 MiB |
| CSV, a million cells in 60 MiB | 60.1 | Completed, at 424 MiB |
| The 57 MiB CSV, twice at once | | Completed, with the cgroup **at its 512 MiB limit** |
| CSV, a 1,190-character unique key | 57.2 | Completed, at 437 MiB |
| Workbook, 1,000,000 data validations | 0.6 | **The worker was killed by the kernel.** Exit 137, `OOMKilled` true. The run stayed `validating`, and the job enqueued after it was never taken |

### What one import costs, and what that leaves

The model the slot makes true is

```
the worker, idle        +  1  ×  the largest accepted import  +  whatever else is running
66 MiB, to 166 after work      about 170 to 270 MiB over that         not measured by GR-352C
```

and the largest it was observed to reach is 340 MiB, which leaves 172 MiB of
a 512 MiB machine. Without the slot the second term is multiplied by however
many imports the queue hands over, up to ten.

**That is a measurement and not a headroom.** It is one machine, one run of
each file, a writer that batches a thousand rows and holds nothing else, and
no other job doing anything. Whether 172 MiB is enough, and what the limits
should be so that it is, is the decision this document is evidence for.

**And it was a measurement of the source tree.** The harness mounted the
repository into the container. The third term, and the product's own image,
are the next section.

**340 MiB is not the final figure.** It is GR-352C's, from the source tree
and with a defect inflating it. The evidence the contract was ratified on is
GR-352E's, from the product's own image: 286 to 303 MiB.

## GR-352E: what else is in the worker

IMPORT-GAP-023 said that one import had been measured fitting a 512 MiB
worker and that nothing else the worker does had been. On 2026-10-02 it was
measured, at `cf17a6e`, and this time in **the product's own images** -- the
worker and the API built from the generated Dockerfiles, with nothing
mounted over them -- under 512 MiB of memory, 512 MiB of memory plus swap and
one CPU. The cron jobs were the real ones, triggered by enqueueing them; two
MinIO servers stood as the source and as a destination at another provider;
the destination answered no digest, as the code's own comment records of
Supabase, so every copy was read back.

| The worker, at `cf17a6e` | cgroup maximum, MiB |
|--------------------------|--------------------:|
| Idle | 74 to 75 |
| The worst accepted import alone -- the 57.2 MiB CSV, 50,000 rows by 2, a long unique key | 357 to 371 |
| A cross-provider backup alone, 64 MiB objects | 268, which is 193 over idle and not the 128 that had been modelled |
| That import and that backup together | **512 on one run, 499 on the other** |
| That import and a restore | 413 to 416 |
| That import and scheduled reports of 10,000 rows | 323 to 328 |

Nothing was killed and both jobs were correct. At the limit with no swap,
that is the last thing that can be said for it: the next allocation is the
kernel's to refuse.

So an import does not fit beside the worker's other heavy work, and three
things followed. All three are in this slice.

### One gate for everything that holds a payload

`services/worker/koras_worker/heavy.py`. An import, a backup's copy, a restore
and a scheduled report each hold the section of the job in which a payload is
in hand inside one gate, and `HEAVY_SLOTS`, which is 1, is how many sections a
process is inside at once.

| Job | Where the gate is taken | Where it is let go |
|-----|-------------------------|--------------------|
| Import, dry run and commit | First statement of the job, before the source is fetched | Last statement of the job |
| Backup | Once an object, before the first byte is read | Once the copy's verdict is in hand, after the read-back |
| Restore | Once a request, **before the request is claimed** | Once the object is written; the two rows that record it are outside |
| Scheduled report | Once a schedule, before the query that answers it | After the last mail that carries it; the audit row is outside |

**It is not a queue, not a lock another process can see, and not a job
slot.** `max_jobs` is still ten. A job that holds no payload -- the outbox
sweep that runs every minute, the retention sweeps, a product's own tasks --
never asks for the gate and is never held up by it, and the same is true of
the parts of a heavy job that hold nothing: a backup's query for what is due,
its catalogue rows, the copies it dates and retires, and an object past the
64 MiB stream ceiling, which is skipped unread. A second worker machine has a
gate of its own, which is the scope the memory has.

**One primitive, taken once.** A job never holds two gates, so there is no
order between two to get wrong. The import's own limit did not become a
second semaphore taken before or after this one: `IMPORT_SLOTS` is passed to
the same acquisition as the number of imports that may be inside, and it is
what still holds imports to one if the gate is ever widened. While the gate
is one wide the two say the same thing.

**First come, first served.** A backup lets go once an object and asks again
in the same turn of the loop. Whoever was already waiting goes in first, so
an import a person is watching goes in between two objects rather than after
the night's run.

**A restore that is waiting has not been claimed.** The gate is taken before
the claim. A sweep that the queue cancels while it waits -- a cron job has
300 seconds and an import may hold the gate for longer -- leaves its request
`approved`, which is where the next pass looks, rather than `restoring`,
which nothing picks up.

**A section that fails lets go of what it held.** An exception carries its
traceback, a traceback its frames and a frame its locals, so a failed job's
payload outlives the gate by as long as the queue takes to record the
failure. The gate clears those frames before it lets go. This is measured
and it corrects a figure above: at `cf17a6e` every dry run in the image
ended in an exception (IMPORT-DEF-020, below), and the commit that followed
began with 166 MiB resident where it now begins with 97. The 69 MiB between
them was the dry run's working set, and it is inside every import peak that
measurement reported. The same image in this slice's harness gave 359 MiB;
this slice's gives 286 to 301.

### A scheduled delivery carries at most 10,000 rows

The delivery path had no bound. `EXPORT_ROW_LIMIT`, which is 10,000, was
read by the export route and by nothing in the worker, so a schedule over a
report that had grown was resolved, rendered whole and attached to a mail for
every recipient.

It has one now: `SCHEDULED_DELIVERY_ROW_LIMIT`, in `tasks/reporting.py`,
which is `EXPORT_ROW_LIMIT` under a name of its own -- derived from the
framework's number, not a second number. A report past it is refused:
nothing is rendered, nobody is sent anything, the schedule's `last_error`
says how many rows there were, what the most is and what to do, and its next
time is set so that it is not asked again every hour. In every format -- CSV,
XLSX and PDF: what is held is the rows.

**Two names, because the number means two things.** The owner's decision of
2026-10-02:

- *An interactive export through the API.* `EXPORT_ROW_LIMIT` is the handoff
  between the inline export and the background one. It is not a maximum: an
  export past it still happens, as a file in the tenant's bucket written
  after the response. GR-352E does not change that route and does not cap
  it.
- *A scheduled delivery.* 10,000 rows is the most that is supported. It is
  deliberately stricter: a delivery is unattended, it runs inside the
  worker's shared resource envelope, and its only output is an attachment
  built whole in the worker, with no bucket to fall back to.

**The rows are in hand when they are counted.** A resolver answers whole and
its count is not known until it has. What the bound prevents is the file and
the mails; the query's own result is bounded by the report's declared
filters and its 366-day range and by nothing in the framework, which is
IMPORT-GAP-026 and is open as of 2026-10-02. It is why the count happens
inside the gate.

### IMPORT-DEF-020: the image was missing a module, and every suite was green

Running the image rather than the tree found something that has nothing to
do with memory. The worker reaches a handful of API modules by name, and the
Dockerfile copies them a line at a time. The audit sink -- which an import
uses to witness a dry run and a commit -- called `rebind_tenant` after it
committed, and imported it from `core/database.py` inside that function.
`core/database.py` is the request's sessions: it imports FastAPI and builds
the API's `Settings()`. The image never carried it and could not have.

So in a deployed worker a dry run did this: recorded its verdict, wrote its
audit row, **committed both**, and then raised `ModuleNotFoundError`. The
queue recorded a failed job. The run said `validated`. Every commit logged
that it finished and could not be witnessed, after the row that witnessed it
had been written.

**The run was right and the job was wrong.** The verdict was committed
before the error and it was true; what was false was the failure. Two things
were changed and neither is the state machine:

- `rebind_tenant` is a module of its own, `core/rebind.py`, which imports
  nothing of the API. The sink imports it at the top of the file and the
  image copies it. `core/database.py` still names it, so every caller in the
  API finds it where it was.
- A job that raises says so on its run. The handlers recorded a cancellation
  and not an error, so an exception before the verdict was committed left a
  run `validating` for ever. They record both now, through the same guarded
  update: a run that is no longer unfinished -- a verdict or a commit that
  did land -- is left exactly as it is.

**Why nothing saw it.** Every suite in this repository runs where the whole
source tree is on the path, and the harness GR-352C was measured with
bind-mounted the tree. The generator's own test asserted the lazy import by
its exact text, as the thing that kept the API's settings out of the worker
-- which it did, by moving the failure from import time to the first flush.
An assertion about what a line says, and nothing asking what it does:
FW-HARDEN-001's shape, again.

What holds it now is two tests that ask what it does.
`tests/unit/test_worker_image_contents.py` walks every import of every
module the worker names -- at the top of a file or inside a function -- and
fails on one the Dockerfile does not copy; removing any one copy line fails
it. `tests/integration/test_worker_image.py` builds nothing itself and
mounts nothing: given the image, it starts a worker from it by its own
command and feeds `worker_image_probe.py` to a second container on standard
input, which loads every module the worker names and takes a dry run and a
commit from first line to last against a real PostgreSQL. Run against an
image with the defect put back, it fails on exactly the two symptoms above.

### Under the same 512 MiB limit, after

The same harness, the same fixtures, the same two object stores; the image
built from a product generated from this slice. Two runs of each case, a
fresh worker for each. Idle was 73 to 75 MiB.

| Case | Peak resident (`VmHWM`) | cgroup maximum | Left of 512 MiB | Waited for the gate |
|------|------------------------:|---------------:|----------------:|--------------------:|
| The worst accepted import alone | 289, 302 | 286, 301 | 226, 211 (44.0%, 41.3%) | -- |
| Cross-provider backup alone, twelve 64 MiB objects | 266 | 264 | 248 (48.5%) | -- |
| Restore alone, twelve 64 MiB objects | 208 | 210 | 302 (59.0%) | -- |
| Twenty scheduled workbooks of 10,000 rows, ten recipients each, alone | 137 | 141 | 371 (72.4%) | -- |
| Twelve scheduled PDFs of 10,000 rows, alone | 140 | 145 | 367 (71.7%) | -- |
| **That import and that backup** | 304, 303 | **301, 303** | 211, 209 (41.2%, 40.9%) | the backup, 3.9 s and 5.7 s |
| **That import and that restore** | 303, 303 | **302, 303** | 210, 209 (41.1%, 40.9%) | the restore, 4.1 s and 6.8 s |
| **That import and the workbooks** | 289, 288 | **286, 287** | 226, 225 (44.1%, 44.0%) | the report, 4.2 s and 4.0 s |
| **That import and the PDFs** | 289, 289 | **286, 287** | 226, 225 (44.2%, 43.9%) | the report, 4.6 s and 3.7 s |

In every case both jobs finished and were correct: 50,000 rows written;
twelve copies `verified` with matching digests; twelve objects restored at
67,108,864 bytes with the digest their backup recorded; twenty workbooks and
twelve PDFs delivered to ten recipients each. No swap was used, nothing was
killed, the cgroup's failure count was zero, a small job enqueued afterwards
was answered in 0.5 to 3.7 seconds against a five-second poll, and no run,
restore, backup or schedule was left unfinished.

**The peak of two jobs is the peak of the larger one.** The gate's own log
lines -- a section entering, a section leaving -- were read for every run:
across 51 sections in the busiest of them, the most that were ever inside at
once was one.

**That is a measurement and not a headroom**, for the reasons the first
capped run gives and one more: these figures are lower than the ones the
decision was last shown, by the 69 MiB a defect had added to them.

### What GR-352E leaves

- **A heavy job that is waiting is a job the queue is timing.** A cron job
  has 300 seconds. A backup, a restore or a delivery that waits that long
  behind an import is cancelled having taken nothing, and its work is where
  its next run looks: a schedule still due, an object still without a copy,
  a request still `approved`. IMPORT-GAP-021 is the same fact about a second
  import. Open as of 2026-10-02.
- **A backup's copy holds the event loop**, as it did: it is synchronous
  calls with no `await` between them. Nothing else in the worker runs while
  one object is copied. Not changed by this slice and not measured as time.
- **The export route's own background export is not behind any of this.** It
  runs in the API process, after the response, with no row ceiling and no
  gate, and its resource envelope has not been measured. IMPORT-GAP-026,
  open as of 2026-10-02.
- **What the API process keeps resident after an analysis has ended** was
  noticed during the GR-352 measurements and not characterised. The worker
  hands freed memory back before it lets go of the gate; nothing in the API
  does the same. An observation to follow up, recorded on 2026-10-02 with no
  figure, and not a finding against any limit.
- **`HEAVY_SLOTS` was the implementer's number and is ratified**, by the
  owner on 2026-10-02, at 1. Its declaration still carries the word
  provisional as of 2026-10-02, for the reason "The names in the code" gives.

**Status of this slice, 2026-10-02: closed and remotely verified.** GR-352E
merged as `3e73190`, and CI `37044176366`, Security `37044176279` and
Generator Integration `37044176367` passed on that commit at the first
attempt.

| Row | Status | Remote evidence |
|-----|--------|-----------------|
| IMPORT-DEF-020 | Closed, remotely verified | The worker-image tests ran against the real generated image on the merge commit |
| IMPORT-GAP-023 | Closed, remotely verified | The heavy-resource gate's exclusion suites; the capped memory evidence is local |
| IMPORT-GAP-025 | Closed, remotely verified | The 10,000 and 10,001 row boundaries in CSV, XLSX and PDF |

This paragraph said "resolved locally, in an uncommitted tree" until the
closure, which was true when GR-352E was returned for review.

**The closure itself is documentation-only, 2026-10-02.** It changes no
runtime or template file. Generator Integration is path-filtered, so the
closure commit is not expected to trigger it, and that is acceptable:
Generator Integration is inherited implementation evidence from the
validated runtime baseline, `3e731901332a6986df1b37ae91504d21e699edc2`,
where the three runs above succeeded at the first attempt; a docs-only
closure does not retrigger the path-filtered workflow.


## IMPORT-GAP-020, part by part

For each thing `openpyxl` built that the safety pass does not count: whether
an existing budget bounds it, whether it needs one of its own, whether the
reader now removes it, or whether it never mattered.

| Structure | Measured before | Disposition | Why |
|-----------|-----------------|-------------|-----|
| Merged ranges | 640 bytes each; 2.6 GiB from a 0.8 MiB file | **Removed by the reader** | Nothing reads the element; no object is built |
| Hyperlinks | 680 bytes each | **Removed by the reader** | The same |
| Data validations | 1,350 bytes each | **Removed by the reader** | The same |
| Conditional formats | 1,290 bytes each | **Removed by the reader** | The same |
| Column definitions, sheet views and other sheet attributes | 85 bytes each | **Removed by the reader** | The same |
| Rows with no cell | 86 bytes each, and time | **Removed by the reader** for memory; time bounded by the uncompressed ceiling and the work budget | A row with no cell is an event and nothing kept |
| Other worksheets | time, and the largest single cell in any of them | **Removed by the reader** | Only the sheet the safety pass named is opened |
| The stylesheet | 760 bytes a format | **Removed by the reader**; more than 65,536 formats is refused | Streamed for date formats, two bits a format |
| Defined names, the workbook part | 770 bytes a name | **Removed by the reader** | Streamed for one attribute |
| Theme, document properties | twice the part's size | **Removed by the reader** | Never opened |
| Dimensions | none of its own | **Negligible**, with evidence | The reader has never trusted `<dimension>`; columns come from cell references |
| Text in the data sheet outside any cell | refused | **Already bounded** by the decoded-string budget | The safety pass costs it |

**No new preflight budget was added and none is asked for.** A count of
merged ranges would have been a limit chosen to fit one library's object
size. Not building the object needs no number.

## Atomicity

Nothing about the commit's three transactions changed, and the order is still
the design: the claim, committed; the writer's work and the run's own
`committed` row together, once; a failure in a second transaction after the
first has rolled back.

What changed is that the reader hands rows over as it goes, so a refusal that
the old readers raised before they returned anything can arrive after
hundreds of rows have been read. That is safe for one reason, and it is a
line of code rather than an intention: **`prepare` returns before the writer
is called.** Every row is read, checked and turned into its dictionary first;
a file that fails anywhere fails there; the writer is called with all of the
rows or is not called.

`tests/integration/test_import_commit_atomic.py` counts rows on a second
connection after the job has returned, against a real PostgreSQL with
row-level security on and a role that cannot bypass it:

| Case | Rows left | Run |
|------|----------:|-----|
| A commit that succeeds, 600 rows, CSV and workbook | 600 | `committed`, with its counts |
| The writer raises on row 500 of 600 | 0 | `failed` |
| A row near the end does not validate | 0, and the writer is never called | `failed` |
| A key near the end repeats an earlier one | 0, and the writer is never called | `failed` |
| A required cell near the end is empty | 0, and the writer is never called | `failed` |
| A workbook cell on row 550 cannot be read | 0, and the writer is never called | `failed` |
| The time budget is spent | 0 | `failed`, with the budget's sentence |
| The queue cancels the job while the writer is half way | 0 | `failed`, interrupted |
| A cancellation arrives after the commit landed | 600 | `committed`; `abandon` matches nothing |
| Another organisation looks | 0 visible, and the run is not visible | -- |
| The writer writes a row for another organisation | 0 | `failed` |

## Functional compatibility

**What a dry run and a commit answer is unchanged**, and that is asserted
rather than intended.

- *The rows.* `test_streaming.py` hands the stream and the readers it
  replaced the same files -- 22 CSVs, 12 workbooks `openpyxl` wrote, 31
  written by hand for the shapes it does not write, 80 from a seeded
  generator -- at three row limits, and compares the header, every row with
  its number and flags, the sheet, the identity, the delimiter and the
  encoding. A refusal has to be the same sentence and the same type.
- *The verdict, the keys, the writer's rows.* `test_equivalence.py` keeps
  `validate`, `validate_row`, `match_key` and `normalise_row` as they stood at
  `1fefbc3`, verbatim, and compares them with what replaced them over
  generated rows that are wrong in every way a row can be.
- *The prediction.* `predict_from` against `predict`, and `request_from`
  against `request_for`, under every operation and four sets of existing
  records.
- *Cleaning.* `clean_cell` against its old body over every C0 and C1
  character, every space the standard library strips, and generated text.

**Three intended differences**, each a malformed workbook and none a file a
spreadsheet writes, each asserted as what it is in `test_streaming.py`:

| Shape | Before | Now |
|-------|--------|-----|
| A part the reader never opens is broken -- the document properties, another sheet | the dry run refused the workbook | the workbook is read |
| A shared string longer than a cell may be *only until* its escaped underscores are removed | read | refused, as a file in a cell |
| A stylesheet declaring more than 65,536 cell formats | read, at 760 bytes a format | refused |

**And one in timing.** A refusal inside a file -- a number that is not one, on
row 40,000 -- is raised when the walk reaches it and not before the first row
is returned. A caller that has kept something of the rows above it keeps
nothing afterwards: the store's functions raise, and the worker records the
failure exactly as it did.

**One in behaviour, for a product's own code.** A target's `validator` is
called on the worker's reading thread and not on its event loop. It is a
synchronous function of one row's values and was never anything else.

## The limits

Ratified on 2026-10-02 at the values below; none was changed. This section
was headed "The provisional limits" until then.

| Limit | Value | What GR-352C measured against it |
|-------|-------|----------------------------------|
| Source | 64 MiB | The largest term of every large peak: the bytes are held for the whole read |
| Workbook uncompressed | 256 MiB | Bounds the time of both walks; no memory depends on it after this slice |
| Decoded strings | 64 MiB | A workbook's string table is held once and costs what this says |
| Cells | 1,000,000 | 79 to 129 bytes each in a commit, about nothing in a dry run |
| Columns | 256 | Time, and no longer the square of it |
| Archive entries | 4,096 | Not exercised by this slice |
| API preview characters | 4 MiB | Not exercised by this slice |
| Rows | the target's | About 265 bytes each in a dry run's index |

Four things that were put to whoever ratified them. The ratification of
2026-10-02 kept every number and acted on none of the four:

- **The CSV text budget is pessimistic now.** The safety pass costs a CSV as
  one string at the width of its widest character, because that is what the
  old reader built. Nothing builds that string any more: a cell is its own
  string at its own width. One emoji still quarters the largest CSV that is
  accepted. `preflight-safety-envelope.md` said this term should become a sum
  over lines when the worker's reader streams. It can; changing it accepts
  files that are refused as of 2026-10-02, which is a decision. The decision
  of 2026-10-02 was to keep it conservative: IMPORT-GAP-024.
- **Three numbers were added by the implementer, and all are ratified.**
  `IMPORT_SLOTS` (1), `WORK_BUDGET_SECONDS` (600) and `ANALYSIS_SLOTS` (2).
  GR-352E added a fourth, `HEAVY_SLOTS` (1), and changed none of the three;
  it is ratified with them.
- **One number was reused and not added.** A scheduled delivery is bounded
  by `SCHEDULED_DELIVERY_ROW_LIMIT`, which is derived from `EXPORT_ROW_LIMIT`
  (10,000). For a delivery it is a maximum; for the export route the same
  number is the inline-to-background handoff and no maximum at all.
- **The source ceiling is what the worst peak is made of.** See below.

## Where this stands, 2026-10-02

- **GR-352 is closed, verified, and its NFRs are ratified**, on 2026-10-02.
  "The ratified resource contract" above is the contract.
- **The measurements are the evidence and the contract is the section that
  cites them.** The supported limits are the ones that section lists.
- **512 MiB is the memory that was tested and the memory that is ratified**,
  for the worker and for the API, because it is what both `fly.toml`
  templates declare. Nothing was tested at another size.
- **The worker's 340 MiB is GR-352C's figure and not the final one.** In the
  product's own image, with the defect that inflated it removed, the worst
  accepted import peaks at 286 to 301 MiB of the cgroup's 512, and no pair of
  heavy jobs was observed above 303.
- **The seven limits and four controls are ratified at the values they were
  built with**: the limits of GR-352A, the 4 MiB sample budget, one heavy
  section and one import to a worker process, 600 seconds of reading, and
  two sources in hand in an API process.
- **Of the four gaps GR-352C opened, three are open as of 2026-10-02**:
  IMPORT-GAP-021, IMPORT-GAP-022 and IMPORT-GAP-024. IMPORT-GAP-023 is
  closed and remotely verified. GR-352E opened IMPORT-GAP-026, which is open
  and outside GR-352. IMPORT-GAP-018 is open as it was.
- **IMPORT-DEF-014 is open and is an activation constraint.** A deployed
  product cannot read an import's source from a real bucket as of
  2026-10-02. It is a defect in reading storage and not a reason to hold the
  finished resource envelope open; no product may activate canonical imports
  against real object storage until it is fixed and verified, and its fix
  repeats the capped measurement.
- **`docoris` is not aligned with any of it** as of 2026-10-02. It carries
  the framework by hand and has received none of the slices. The Starter's
  closure does not enable its imports and does not unblock its OD-12: the
  order is in "What the closure does not authorise".

## How it is proved

- **The rows**, by comparison: `test_streaming.py`, 145 files at three row
  limits against the readers the stream replaced.
- **The answers**, by comparison: `test_equivalence.py`, the old bodies kept
  verbatim beside the new ones.
- **Neither old reader is reached**, by replacement, from any of the store's
  four ways in: `tests/unit/test_import_preflight.py`, with a second test
  showing the replacement does fail when it is reached.
- **Memory**, as the kernel measures it: `tests/unit/test_import_worker_memory.py`,
  Linux only, through `examine` and `prepare` in a process of their own. Each
  shape above in a size small enough for every push, each under a bound, and
  the old path on the same file required to be many times over it.
- **One import at a time, the loop free, the read stopped, the budget kept**:
  `tests/unit/test_import_worker_envelope.py`, against the product's own task.
  Each of the four has a second test in which the guard is removed and the
  first assertion fails.
- **All or nothing**: `tests/integration/test_import_commit_atomic.py`,
  against a real PostgreSQL, counting rows.
- **Two sources at once in the API**: `tests/unit/test_import_inspection.py`.
- **Mutation.** Eighteen wrong edits were made to a generated product on
  2026-10-02, one at a time, and each turned a suite red: the string table
  cleaned once a cell; long key parts not interned; a sheet's rows drained at
  its end; the budget not asked between rows; the old workbook reader called
  again; a dry run keeping its rows; two import slots; the commit outside the
  slot; the read inline on the loop; the cancellation not passed on; a
  cancelled run not marked; the budget not handed to the read; the writer's
  rows copied; `abandon` without its status guard; no analysis slot;
  `clean_cell` keeping a control character; a prediction's counts swapped;
  candidates kept for rows that failed. The twelfth hung the suite rather
  than failing it the first time -- a read that is never told to stop never
  ends -- and the test's own read gives up after twenty seconds now, so it
  fails.
- **Generator Integration** runs the memory suites and the envelope suite by
  name and fails if any test in them skips, and on the row that has a
  database runs the two commit suites the same way.
- **One heavy section at a time** (GR-352E):
  `tests/unit/test_worker_heavy_sections.py` runs the product's own jobs in
  pairs -- import with import, backup, restore, a scheduled workbook and a
  scheduled PDF; backup with restore and with each report -- and counts how
  many hold a payload at once. Every pair has a second test with the gate
  widened, in which the count must rise.
  `tests/unit/test_worker_heavy_gate.py` asks the gate itself: let go on a
  return, an exception and a cancellation, inside or waiting; first come,
  first served; and a job that never asks is never held up.
- **A scheduled report's bound**:
  `tests/unit/test_reporting_delivery_bound.py`, with real tables of 10,000
  and 10,001 rows in each format.
- **The image**: `tests/unit/test_worker_image_contents.py` and
  `tests/integration/test_worker_image.py`, as the section above describes.
- **Mutation, GR-352E.** Six wrong edits on 2026-10-02, one at a time, each
  turning a suite red: the gate removed from the import, from the backup,
  from the restore and from the delivery; the audit sink's import put back
  inside its function, which the walk of imports caught; and an image built
  with that import put back and the copy of `core/rebind.py` removed,
  against which the container test failed on the two symptoms the defect
  had. The walk has a test of its own that removes each copy line in turn.
- **Generator Integration, GR-352E** names the four unit suites on the row
  that has every heavy job and fails if any test in them skips, and on the
  row that has a database builds the worker image and runs the container
  test the same way.

## What this slice leaves, by name

| Left | Where it is tracked |
|------|---------------------|
| The NFR decision | **Taken 2026-10-02.** The limits were ratified as they stood, so the measurement already taken is the one against the ratified values. IMPORT-DEF-013, closed |
| `source_bytes` awaits a synchronous `S3ObjectStore.get`, and is what keeps all of this unreachable in a deployed product | IMPORT-DEF-014. Open as of 2026-10-02, and the activation constraint |
| A waiting import's time counts against its queue timeout; imports have no queue of their own | IMPORT-GAP-021 |
| A product's validator, matcher and writer are outside the budget and outside the measurement | IMPORT-GAP-022 |
| What else the worker holds while an import runs | IMPORT-GAP-023. Closed 2026-10-02 by GR-352E, remotely verified |
| A heavy job that waits for the gate is timed by the queue while it waits | IMPORT-GAP-021, widened 2026-10-02 |
| The rows of a report are in hand before they can be counted; the API's background export has no row maximum, no gate and no measured envelope | IMPORT-GAP-026 |
| A backup's copy holds the worker's event loop for as long as one object takes | This document, "What GR-352E leaves". Not changed, 2026-10-02 |
| What the API process keeps resident after an analysis | This document, "What GR-352E leaves". An observation, 2026-10-02 |
| The CSV text budget costs a string nothing builds; the source is held whole | IMPORT-GAP-024 |
| A workbook is walked twice, by the safety pass and then the reader | IMPORT-GAP-018 |
| `read_workbook` is still exported and still builds everything measured here; the AI knowledge reader calls `openpyxl` with no safety pass | IMPORT-GAP-016 |
| The three numbers this slice added, and the one GR-352E added, were the implementer's | Ratified 2026-10-02. The word provisional in their declarations is a later, separate change |
| No live run: nothing has imported a file through a deployed worker | F31 |

## Generated products

A generated product has no upstream. The factory pushes to nothing.

- **A product generated after this change** with `data_import` gets all of it.
- **A product generated before it** gets none of it until somebody carries it
  by hand, and the three slices are carried together: `koras_import/safety.py`
  imports `koras_import/budget.py` since this one. The files are, in
  `koras_import`: `budget.py`, `streaming.py`, `__init__.py`, `inspection.py`,
  `jobs.py`, `mapping.py`, `matching.py`, `reading.py`, `reading_xlsx.py`,
  `safety.py` and `writing.py`; `core/imports.py`, `routers/imports.py` and
  the worker's `tasks/imports.py`; and the tests `test_streaming.py`,
  `test_equivalence.py`, `tests/unit/test_import_worker_envelope.py`,
  `tests/unit/test_import_worker_memory.py`,
  `tests/integration/test_import_commit_atomic.py` and the changed
  `test_preflight.py`, `tests/unit/test_import_preflight.py` and
  `tests/unit/test_import_inspection.py`. No migration, no setting, no
  environment variable, no route and no page.
- **GR-352E is carried with them or after them, and whole.** The worker's
  `heavy.py` and its four tasks -- `tasks/imports.py`,
  `tasks/storage_backup.py`, `tasks/storage_restore.py`, `tasks/reporting.py`
  -- with `worker.py`'s comment; the API's `core/rebind.py`, `core/audit.py`
  and `core/database.py`; the worker's Dockerfile; `koras_reporting`'s
  `export.py`, for a comment; and the tests `test_worker_heavy_gate.py`,
  `test_worker_heavy_sections.py`, `test_worker_image_contents.py`,
  `test_reporting_delivery_bound.py`, the changed
  `test_import_worker_envelope.py`, and `tests/integration/`'s
  `test_worker_image.py` with `worker_image_probe.py`. No migration, no
  setting, no environment variable, no route and no page. The gate is
  generated with the worker rather than with `data_import`: a product that
  has backups and scheduled reports and no imports has it too.
- **A product's own writer is unchanged.** It is handed what it was handed.
  A product whose writer kept a reference to the rows and expected a private
  copy of each has one fewer copy than it had.
- **A product without `data_import`** is unaffected: every file above is
  inside the capability's gate.
- **`docoris`** has changed nothing for this as of 2026-10-02. The Starter's
  GR-352 closed that day; `docoris`'s own row is its own repository's to
  change, after IMPORT-DEF-014 and its alignment.

