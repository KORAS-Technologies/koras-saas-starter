# Data import, as built

Phases 1 and 2. Phase 1 landed 2026-09-19 **as amended by the review the same
day**; Phase 2 — the commit — landed 2026-09-20 and has its own section below.
`review.md`
here is what it found and this file describes the result. Read `README.md`
first for what is and is not in it, and
`docs/platform/execution/CAT-02-data-import.md` for the plan this was built
against.

## The shape

```
python-packages/koras-import/          the engine. No database, no bucket, no product
  targets.py     Operation, Format, FieldKind, FieldSpec, ImportTarget, TargetRegistry
  reading.py     encodings, delimiter sniffing, the header, bounded row reads
  mapping.py     resolve (the allowlist), suggest, validate (every problem, one pass)
  writing.py     the Writer seam: WriteRequest, Written, check_total. Knows no table
  states.py      RunState and the only edges that exist
  jobs.py        VALIDATE_RUN and COMMIT_RUN, declared where the API can enqueue them

services/api/koras_api/
  imports/targets.py     the product's own list. Empty in a generated product
  imports/__init__.py    the registry, built at import
  core/imports.py        the run store: two tables, every move through the machine
  routers/imports.py     nine routes, all behind imports.manage

  core/import_notify.py  the completion notice: its kind, its audience, its words

services/worker/koras_worker/tasks/imports.py   validate_run, commit_run

supabase/migrations/00036_imports.sql       import_runs, import_row_errors
supabase/tests/320_imports_isolation.sql    the isolation suite

apps/web/src/app/dashboard/imports/         the page, its actions and its labels
e2e/imports.spec.ts                          four browser checks
```

## The five properties worth keeping

**A dry run writes nothing of a target table.** The state machine has no edge
out of `validating` that writes, and the run store's every statement names
`import_runs` or `import_row_errors` — asserted structurally in
`generators/create-koras-app/tests/product-import.test.ts` by scanning the
store for `insert into public.X` and requiring X to be one of the two. A commit
route added later without its own confirmation would otherwise sail past every
other test in this repository.

**The mapping is an allowlist.** A mapping arrives from a browser and names
target fields. `resolve` refuses a field the target never declared rather than
dropping it, because dropping it is how an import writes a column it was never
meant to reach. The refusal is a 422 naming the field, so a caller who mistyped
is told rather than answered 200 by a request that changed nothing.

**The source is bounded by a number.** `MAX_SOURCE_BYTES` is 64 MiB, checked
against the size the index recorded before the object is fetched, and again
at `POST /imports`. This was the upload ceiling and nothing else — whose
default is five thousand megabytes — and `source_bytes` selected `size_bytes`
without ever reading it. IMP-02.

**A file nobody has scanned is not parsed.** `UNPARSEABLE_SCANS` is
`{pending, skipped, infected}` — **narrower than a download**. `core/file_scan.py`
withholds `infected` alone, deliberately, so that a product with no scanner is
not broken: a person opening a file they uploaded is making their own judgement.
An import is not that. The product reads the bytes itself and writes rows from
them, unattended, and "nobody has looked at this yet" is not a state to do that
in. The consequence is stated rather than hidden: with no scanner configured
every file is `pending`, so a product without one cannot import at all.

**A queue that is not configured is a refusal, not a 202.** `Enqueued.simulated`
is what `RecordingJobQueue` answers, and the validate route reads it *before*
moving the run and answers 503. A 202 in that case would promise work nothing
will do and leave somebody watching a spinner forever.

## Retention reaches an import source

`source_file_id` is nullable, `on delete set null`. It was `on delete
restrict`, and that was the worst defect this feature shipped with: it was
the only foreign key onto `public.files` in the schema, the object-retention
sweep had never met a refusal and did not handle one, and the result was that
the sweep deleted a customer's bytes, then aborted on the row delete, and
aborted again on the same row every night after. No customer file was ever
purged again, silently. IMP-01, and ADR 0009's Amendment 1.

A run outlives its source. What the run remembers about the import — the
columns, the mapping, the counts, the operation, who asked — is on its own
row; the bytes were never the provenance. A run whose source has been purged
answers `import.source.missing`, which was already a path and already
translated.

`storage_lifecycle._forget` is the other half: a row the sweep cannot delete
is counted as stranded and the sweep goes on, so the next foreign key onto
`files` cannot recreate the class.

## The state machine

```
created ──▶ mapped ──▶ validating ──▶ validated
   │           │  ▲          │     └─▶ validation_failed
   │           │  └──────────┘              │
   │           │   (re-map and try again)   │
   │           ▼                            ▼
   └───────▶ cancelled            commit_requested ──▶ committing ──▶ committed
                                                             └──────▶ failed
```

`validated` and `validation_failed` both wrote nothing. `committed`, `failed`
and `cancelled` are terminal. Four of the ten states are only reachable in
Phase 2 and are translated already, because a run that somehow arrives in one
should not render a bare identifier.

`require_move` is consulted *before* the `UPDATE`, so a refusal names both
states while the caller is still on the stack — rather than an
`UPDATE ... WHERE status = ?` that matches nothing and reads as "the run
disappeared".

## The source file is an ordinary upload

The file goes through `/files/uploads` with `category: imports`, so it inherits
retention, legal hold, reconciliation, virus scanning and the storage quota
without any of that being restated. The category is decided by the server
action and never accepted from the browser: a caller cannot ask for a document
ticket and then feed the file to a run, nor the other way about.

Two of the three file settings are now enforced at the ticket rather than
declared and ignored — `files.maxUploadSizeMb` and `files.allowedExtensions`,
both resolved through `core/storage.py:upload_limits` and answered as
`upload_refused_by_policy`. The hardcoded 5 GiB ceiling stays as the outer
bound; the settings narrow it.

### A new upload is a wait, not a refusal

In a product with `secure_files` a new upload is withheld from every consumer for the
upload window (`FINALIZE_DELAY_SECONDS`, about nineteen minutes) and then until the scanner
has written a clean verdict. That window is unchanged and no import code touches it. What
changed is what an import says about it: `check_source` used to fold a `pending` scan into
`import.source.unscanned`, which the router answers as `file_quarantined`, so a perfectly
good file chosen a moment earlier read as "This file is not available."

Now `pending` (an unfinished upload, or a ready file whose scan is still pending) is
`import.source.pending`, answered `409 file_scan_pending`. `skipped`, `infected` and any scan
value the code does not know stay `import.source.unscanned`; a file that is quarantined,
archived or deleted stays `import.source.not_ready`. Every one of them still withholds the
file, because the release rule is untouched.

The page does not start a run right after `/complete`. It asks the read-only
`GET /imports/sources/{file_id}` (same `imports.manage` permission and activation gate as
every other import route), which answers one closed word, `checking`, `ready`, `held`,
`rejected` or `missing`, and `ready` only where `releasable()` would release the file and it is
within the import ceiling. The page starts the run on `ready`, waits on `checking` (every 10
seconds, doubling to 60, for up to 45 minutes, then a "Check again"), and ends the wait with
a sentence of its own on the rest. A wait is remembered in the browser per organisation and
person so that leaving the page does not lose it, and a remembered wait never starts a run
by itself: it offers "Continue".

## The permission

`imports.manage`, on **every** route including the reads. A run names a
customer's own records and its mapping shows their column headings, so the
history is not less sensitive than the act. The permission is administrative,
held by owners and administrators alone, so an ordinary member does not see the
module at all — hidden rather than locked, since there is nothing to upsell.

A target may also declare its own `permission`, and `_require_target` enforces
it on top, on **every** route that resolves a target. Both are required: a
target cannot widen access by declaring a permission everybody holds. That check
was added when writing this document found the field declared and enforced
nowhere, which is precisely the state its own comment says is worse than having
no field — and the review then found it on one route of three, which is a rule
nobody can reason about. IMP-06.

**No entitlement.** A customer who cannot get their data in has not bought a
product, and selling the way in separately sells it to somebody who has not
started using the product yet. The same position Restore takes, from a
different direction.

## Where this departs from the plan

Three Phase 1 items in `CAT-02-data-import.md` are not built, and saying so
here is cheaper than rediscovering it.

| Plan item | State | Why |
|---|---|---|
| `files.maxFilesPerUpload` enforced (part of IMPORT-DEF-001) | **Not enforced.** Marked `surfaced=False` in the catalogue instead | The presign route issues one ticket per call and has no notion of a batch. A setting drawn on a page and honoured by nothing is worse than one not offered, so it is hidden until the route can count |
| An upload primitive extracted into `packages/ui` (IMPORT-GAP-007) | **Not extracted.** The import page has its own file input | The Files page's uploader carries progress, digesting and a confirmation dance that the import flow needs in a different order. Extracting it to serve both would have been a refactor of a working page inside a feature branch; the duplication is two dozen lines and is recorded here rather than hidden |
| The preview drawn through the shared data table (IMPORT-GAP-006) | **Not used.** A plain table in the panel | The stated reason was wrong and is corrected here rather than quietly edited: the shared table takes `columns` as a prop, so a column set built per file was never the obstacle. The real one is that it paginates on the client, which bounded the preview rather than blocking it. The table gained a server-paging seam on 2026-09-19; moving the preview onto it is Phase 2 work and the obstacle is now gone |

None of the three affects the safety properties above. All three are Phase 2
candidates.

## What the review changed

Six findings, all fixed on 2026-09-19. Four are described above and in
`review.md`; the two not mentioned elsewhere in this file are:

- **An ambiguous decimal is refused rather than guessed.** `1,234` and
  `1.234` each have two readings that differ by a factor of a thousand, and
  `float(value.replace(",", "."))` silently picked one. Where both
  separators appear the last is the decimal point; where one appears followed
  by exactly three digits the value is refused with
  `import.error.ambiguous_decimal`. The same rule the module already applied
  to `%m/%d/%Y`.
- **`decode()` can report a fallback.** `latin-1` maps all 256 byte values, so
  with it inside `ENCODINGS` the loop always returned before its own
  fallback: `Decoded.replaced` was structurally always `False` and the page's
  banner could never appear in any of three languages. It is the fallback
  now, not a member of the strict list.

Three low findings are carried, in `review.md` under IMP-07.

## Phase 2: the commit

2026-09-20. Phase 1 stopped at `validated`, which was a terminal state that
wrote nothing. Phase 2 is the other half, and its acceptance criterion is one
sentence: **a commit that raises on row 900 of 1000 leaves zero rows.**

### The product writes; the engine orchestrates

`koras_import.writing` is the seam. A target declares a `Writer` — an async
callable taking the caller's open session and one `WriteRequest` — and the
engine calls it. That is the only way a row of a product table is written, and
it is what keeps the rule CAT-02 states first: no product table name, no
Docoris concept and no shop concept reaches the engine. Reading a file,
matching columns and checking values are things this package can do for
anybody. Writing is not.

A target with no writer is **not committable**: it can be uploaded, mapped and
checked and never written. That is a legitimate state — it is what every target
was before this — and it is absent rather than disabled all the way down. The
API answers `committable: false`, the page renders no confirm control at all,
the route answers `import_not_committable`, and the worker checks again for a
target that lost its writer between the request and the job.

### Where the atomicity actually lives

Four transactions, in this order, and the order is the design:

1. **The claim.** `begin_commit` moves the run from `commit_requested` to
   `committing`, and commits. It does two jobs: it gives `record_commit` below
   a state it may legally leave, and it puts the run into a state the page
   polls on, so somebody can watch the write happen.
2. **The writing one.** The product's writer and `record_commit` share it, and
   it commits once. Both halves matter: a run marked committed whose rows
   rolled back claims an import that did not happen, and rows that landed under
   a run still `committing` can be committed again and go in twice.
3. **The failure one**, opened after the second has rolled back. This is the
   only arrangement where a failure is both recorded and leaves nothing behind
   — a failure written inside the transaction that failed rolls back with it,
   and the run sits in `committing` forever, indistinguishable from a worker
   that died.
4. **The notice.** Last, and it swallows everything (below).

**Step 1 was missing from the day Phase 2 shipped until 2026-09-22**, and this
section described three transactions because of it. The consequence was not
subtle: `record_commit` asks for `committing → committed`, the machine has no
such edge from `commit_requested`, so every commit of every product raised,
rolled the writer's rows back and then failed again trying to record the
failure. Phase 2 had never worked. IMP2-01 in `phase-2-review.md`.

None of that is visible to a test that reads template text, so what
`product-import.test.ts` asserts is the shape that makes it true: three
`session.commit()` calls on the commit path, two sessions, a rollback before
every recorded failure, `begin_commit` before the write, the write before
`record_commit`, and `record_commit` before `fail`. Each is a thing somebody
could undo in one plausible edit.

**And the shape is not the property.** Every one of those assertions was green
over a commit path that could not succeed once, because each asks what the code
*says* rather than what it *does*. What catches this class is in
`koras-import/tests/test_import.py`: a test that walks the state machine along
the exact path the worker takes, and goes red if any step of it is refused.

### The commit checks the file again

`core/imports.prepare` parses and re-validates, rather than the commit trusting
the verdict the dry run stored. It costs one pass over a file already bounded by
the target's ceiling, and it closes the gap between "somebody checked this" and
"this is what goes in": between the two, a deploy may have changed the target's
own field specifications, and the run's stored counts would still say it was
clean. A disagreement **refuses the whole run** rather than writing the rows
that still pass — writing only the good ones is the partial commit the
requirements forbid.

`_parse` is shared by both passes for the same reason: a commit that parsed
differently from the validation that approved it would write rows nobody
checked, and both would look like they had run.

### The rows are read again, not carried

The validation stored counts and errors, not rows. Carrying a file's worth of
parsed records between two jobs would mean either a queue payload the size of
the upload or a second copy of the data in the database. Reading it again costs
one fetch, and the file cannot have changed underneath: an object under a run
is immutable and the scan gate has already passed.

### Two locks against writing twice

The state machine refuses a second `commit_requested`, and the enqueue carries
`idempotency_key=f"commit:{run.id}"`. They protect against different failures —
a double-click and a redelivered job — and the cost of being wrong is a
customer's records imported twice, which is worth two.

The run is moved to `commit_requested` and **committed** before the enqueue.
The other order has a window in which a worker reads a run still `validated`
and refuses its own job.

### `check_total`

A writer must account for every row it was given: created, updated or skipped.
Cheap, and it catches what a writer is most likely to get wrong — a filter or an
early `continue` that skips rows without counting them. Without it the run
reports a clean import of fewer records than the file held, and nobody can say
which are missing: the partial commit again, wearing a success message.

### The completion notice, and what it cannot do

`core/import_notify.py` declares `imports.finished` and produces the notice
through the same dispatch point the assistant uses — the outbox's second
producer, and IMPORT-US-018. One kind for both outcomes rather than two:
whether it worked is the body and the severity, not a different subscription,
and two kinds would let somebody switch off failures and keep successes.

**It is in-app only, and that is stated rather than hidden.** The audience is
two subjects — who started the run and who confirmed it — and a subject carries
no address in this product's own tables. The one place addresses live is the
platform's member list, which needs a caller's token, and a worker has no
token: nobody is signed in when a background job finishes. So the template
returns `html=None` and the mail half skips, which is the mechanism a template
with no mail form has always used.

`data_import` therefore **requires** `notifications`, refused rather than
degraded: a commit is minutes of work in a worker and the person who confirmed
it has closed the page, so an import framework whose completion notice silently
does nothing is one whose runs appear to hang.

Reaching the dispatch point from the worker cost one change elsewhere.
`core/recipients` imported `core/platform`, which builds the API's `Settings()`
at import, so anything importing recipients needed the API's whole environment.
That import is now made at the point of use — on the branch that resolves an
audience by permission in a request carrying a token, which a background send
never reaches. A worker that had to satisfy the API's configuration surface to
announce a finished import is a worker with the API's configuration surface.

### The error report downloads

`allErrors` pages the report to exhaustion and the panel writes a CSV. A person
fixing a file works in a spreadsheet, not in a table on a web page, and the
criterion for a failed run is that they can get **every** bad row out;
`listErrors` answers a page. Every cell is quoted and every quote doubled: a
cell holding a comma, a newline or a quote is exactly the kind of cell an
import rejects, so the error report is the file in this product most likely to
contain all three.

### What Phase 2 does not do

- **No rollback of a committed run.** The records are the product's, written
  through the product's own writer, and undoing them means knowing what they
  replaced. `attributes_to_run` is the groundwork — a product that stores the
  run beside each record can find them again — and nothing is built on it.
- **No progress while it runs.** A run in `committing` says so and nothing
  more. A row counter would need the worker to write outside its one
  transaction, which is the property the phase exists to protect.
- **No `create`-only or `update`-only enforcement beyond the target's own
  declaration.** The engine passes `operation` and the product honours it; only
  the product knows how to look a record up.
- The three Phase 1 items named above are still not built.

## Templates and formats

2026-09-29. `templates-and-formats-analysis.md` here is the analysis this was
built from and `docs/adr/0012-import-template-versioning.md` is the decision
record, including the resolution of the twelve questions the analysis put to
the owner. What follows is what was built.

### The workflow is one workflow

Download Template, in Excel or CSV, then Upload, Validate, Preview, Confirm,
Background Processing, Results. A CSV and an XLSX go through the same ticket,
the same run, the same mapping and the same dry run. The format is decided
once, at `POST /imports`, from the file row the run is started against -- its
name's extension first, its content type second -- refused with
`import_format_refused` when the target does not accept it, and stored on the
run, which until this day always said `csv` because the insert never named the
column.

### The template is the declaration, written out

`koras_import.templates.render` takes an `ImportTarget` and a `Format` and
returns bytes. No session, no tenant, no locale: a test renders every target
without a database, and a template can never carry a customer's row because
it never sees one. There is no second description of the schema.

`FieldSpec` gained `example` and `help`, both optional, both plain text in one
language. An example is synthesised from the kind when the declaration has
none, deterministically, so a target declared before templates existed renders
a complete template. The help text cannot be localised because the product's
label keys resolve in the web application's catalogue and nowhere in Python;
ADR 0012 D8 records the limitation and its trigger.

**The XLSX** has a `Data` sheet -- the field names in row 1, bold, required
ones filled, each with a comment carrying the help and the format guidance;
data validation on enumerated, date, integer and decimal columns over ten
thousand rows or the target's ceiling, whichever is smaller -- and an
`Instructions` sheet naming the target, its version, its fingerprint, the row
ceiling, and one row per field: required or optional, type, format, allowed
values, example, help. The identity is also a custom document property.
**The CSV** is the header row alone, UTF-8 with a byte-order mark, comma, CRLF.
Neither carries an example row: a row of synthetic values on the sheet a
customer fills in is a record that gets imported by whoever forgets to delete
it, and no header-parsing reader can tell it from data.

Every string the renderer writes passes the same formula guard the reporting
writer applies. Every string is the product engineer's, and the guard is three
lines.

### The identity, and what is judged from it

`ImportTarget.version` is the product's, default 1, bumped when a field's
meaning changes. The engine computes a fingerprint over the declared shape --
name, kind, required, options -- and a template's identity is
`key/vN/fingerprint`. XLSX carries it as a document property; CSV carries
nothing, by decision. `koras_import.compatibility.compare` judges every file
from its header, by the same normalised name match the mapping suggestion
uses: `compatible`, `unknown_columns` or `incompatible`, with the missing
required fields and the unknown columns named. A file whose property names an
older version or a different shape is reported `stale` and is still usable if
its header fits. The mapping is the gate, exactly as before; the verdict tells
a person why before they reach it.

### A workbook reads by the CSV reader's rules

`koras_import.reading_xlsx` reuses `header_from` and `row_from`, factored out
of the CSV reader for this purpose, so a spreadsheet saved as CSV and the same
spreadsheet saved as XLSX name their columns identically and produce the same
cells. Bounded three ways before a sheet is opened: the zip directory's
uncompressed sizes are summed and refused past 256 MiB (ADR 0012 D12), a
workbook carrying a macro project is refused, and one with no workbook part is
not a workbook. Cells are read with cached values, so a formula never runs.
The `Data` sheet is preferred and the first sheet is the fallback.

**The three typed-value findings the Phase 2 review carried closed with it.**
IMP2-19: `mapping.canonical` writes every accepted spelling in one shape -- a
date as ISO, a decimal with a point and no thousands separator, a boolean as
`true` or `false`, an option as declared -- and `prepare` hands the writer
those rather than the stripped cell. IMP2-18: `float()` accepting `nan`, `inf`
and `1e400` is refused with `import.error.decimal`. IMP2-21: a C0 control
character is removed at the reader for every format. And IMP2-20 with them:
an operation that recognises rows now refuses a mapping that omits a match
key, at the store and at the mapping route.

### The safety pass, before either reader

Added 2026-10-01 as GR-352A. "Bounded three ways before a sheet is opened",
two paragraphs up, was true and was not enough: GR-352 measured a workbook
inside all three bounds taking a worker to 1,458 MiB, because `openpyxl` builds
the whole shared-string table on load and CPython stores a string at the width
of its widest character. The CSV path had the same shape -- the whole file
decoded into one string before a line was split.

`koras_import.preflight` now runs first on every path that parses a source:
inside `read_workbook` for a workbook, and ahead of `decode` in `analyse` and
`_parse` for a CSV. It streams the file, counts decoded text at its real width,
cells and columns, and refuses with a `PreflightRefused` -- a `ReadRefused`, so
every existing handler already answers it. It reinterprets no value.

**The numbers in it were provisional and GR-352 was open, on 2026-10-01.**
The envelope had not been ratified, the readers had not been re-measured
against it, and the API parsed a whole safe file to preview 200 rows of it.
`preflight-safety-envelope.md` here is the description, including what the
slice deliberately left. The numbers were ratified unchanged and GR-352 was
closed on 2026-10-02.

### The inspection: a head of the file, for the two routes that draw one

Added 2026-10-01 as GR-352B, and the last clause of the paragraph above
stopped being true the same day. `analyse` no longer calls `read_workbook` or
`decode`: it calls `koras_import.inspect_source`, which runs the safety pass
and then streams the header, up to two hundred rows and a count that stops one
past the target's ceiling. A workbook's shared strings are resolved
selectively -- the table is walked for lengths, then again for the strings the
sample names, wherever in it they are -- and no string the size of a CSV is
made. Both routes await `analysed`, which runs it on a thread, so a file that
takes seconds to walk no longer holds every other request for those seconds.
The mapping route asks for no rows at all.

**The canonical readers are untouched and stay authoritative.** The dry run
and the commit read every row through `_parse` exactly as before; the
inspection answers what the mapping page draws and nothing that is validated
or written. `bounded-inspection.md` here is the description, with what was
measured and the three places the inspection is deliberately not the reader.

### The stream: every row, for the dry run and the commit

Added 2026-10-02 as GR-352C, and the paragraph above stopped being true that
day in one respect: the dry run and the commit still read every row through
`_parse`, and `_parse` no longer calls `read_workbook` or `decode`. It opens
`koras_import.open_rows`, which runs the safety pass and then yields rows as
the file is walked -- a CSV decoded a chunk at a time, a workbook read with
`expat` by the sheet walk the inspection was built from, asked for every row.
`read_workbook` and `decode` stay in the package as the description of what a
file's rows are, and the stream is held to them file by file.

Three things follow from the rows not being a list, and each is a paragraph
of `worker-resource-envelope.md` here.

**`validate` takes what is needed of a row while the row is there.** It
always read its rows once; what needed a list was everything after it. A dry
run keeps a key, a row number and one cell for each row the validator passed,
and the prediction is counted from those. A commit builds the writer's
dictionary from each row as it passes, and hands those over uncopied.

**"The rows are read again, not carried", above, still holds**, and "the
commit checks the file again" with it. What changed is how the file is read
on each of the two occasions, not that there are two.

**The atomicity is where it was, and one line now carries it.** A refusal
from inside a file used to be raised before a reader returned its first row.
From a stream it arrives when the walk reaches it. `prepare` returns before
the writer is called, so it still arrives before anything is written.

**The job itself changed.** It holds a slot -- one import to a worker process,
and since GR-352E the same gate a backup's copy, a restore and a scheduled
report hold, so none of the four is heavy beside another -- from before the
source is fetched; the read runs on a thread, so the
worker's event loop is free; and the read is given a time budget it asks as
it goes, because the queue's timeout cancels a coroutine and a parse has no
`await` for that to land on. Before this a job past its timeout read on to
the end of the file.

### The matcher: what an import would do, before it does it

`ImportTarget.matcher` is optional: an async callable taking the caller's
tenant-bound session and a `MatchRequest` -- every distinct canonical match
key among the rows the validator passed -- and answering which exist. The
worker asks it once per run, inside a savepoint, and `koras_import.matching`
counts by the operation's table: with `create` an existing record is a
rejection and a row error (`import.error.already_exists`), with `update` an
absent one is a skip, with `upsert` an existing one is an update, with
`skip_duplicate` a skip. The prediction lands on the run as three nullable
columns; a target with no matcher records null and the page says the figures
are unknown rather than drawing zeros. The commit trusts none of it: the
writer decides again with the rows in front of it. ADR 0012 D9.

### What the run knows since 00038

Nine nullable columns, by `00038_import_counts.sql`: the template version the
file carried, the job id of the last enqueue, the in-file duplicate count, the
three predicted figures and the three written figures. `record_commit` keeps
created, updated and skipped apart as well as summed, and the page draws the
five-row table -- total, created, updated, skipped, failed -- where failed is
zero for every committed run because a commit is atomic (ADR 0012 D1). A run
from before the migration renders the sentence it rendered before.

### The page

One `Download Template` control, a disclosure over one plain anchor per format
the target accepts, from a new `DownloadMenu` primitive in `packages/ui` that
combines the shell's profile-menu pattern with the export menu's anchors:
Enter opens and focuses the first item, Escape closes and returns focus, no
menu role, no prefetch. The anchors point at
`apps/web/src/app/api/imports/[key]/template/route.ts`, the export handler's
twin. The start card names the byte ceiling -- the organisation's upload
setting inside the source ceiling, resolved by the API and carried on the
target view -- the row ceiling and the accepted formats, and the chosen file's
name and size. The mapping card carries the compatibility verdict and, for a
workbook, the sheet it was read from. The preview card draws total, valid,
invalid and duplicate, and the three predicted figures when there are any.

### The audit

Three actions joined the registry: `import.template.downloaded` (activity,
from the route, before the bytes go), `import.run.validated` (activity, from
the worker, in the transaction that records the verdict) and
`import.run.finished` (audit, from the worker, in a transaction of its own
after the write and before the notice). This supersedes the Phase 2 position
that the outcome lives on the run row alone; the run row is still the
authoritative state, and these carry counts, identifiers and the safe sentence,
never a cell. Reaching the sink from the worker cost the same change
`core/recipients` needed on 2026-09-20: `core/audit.py` imported `.database`
at module level, which builds the API's settings, and now imports it at the
point of use. The worker image copies the module.

**That last move was a defect, found on 2026-10-02.** Importing `.database`
at the point of use kept the API's settings out of the worker by moving the
failure: the worker's image has no `core/database.py`, so the import failed
on the sink's first flush, after the flush had committed. Every dry run in a
deployed worker was a failed job over a run already `validated`.
IMPORT-DEF-020. What the sink calls is `core/rebind.py` now -- a module that
imports nothing of the API, imported at the top of the file and copied into
the image -- and the image is built and run by a test of its own.
`worker-resource-envelope.md` has the account.

### What the browser found beside itself

Three defects, all on 2026-09-29, all fixed the same day, all in
`testing/runs/2026-09-29-01/README.md`: the template menu listed the target's
formats in declaration order, so Enter focused CSV on a target that declares
CSV first; the panel stayed open after a download, so the next press closed it;
and the imports page scrolled sideways at 375 pixels once a target was
rendered, because `sr-only` positions its span absolutely and the history
table's scroll wrapper was not positioned. The first two are the menu's;
the third predates this work and was unmeasurable until a target rendered at
a phone width.

### What the build found beside itself

A freshly generated product could not collect its unit suite: SQLAlchemy 2.1
resolved, and 2.1 stopped installing `greenlet` on its own, so the first
`sqlalchemy.ext.asyncio` import failed. R-044's class -- the declared floor
works, the resolved version does not. Every declaration is
`sqlalchemy[asyncio]` now.

### Verified, and how

On 2026-09-29, against a product generated `--with data_import` into a
scratchpad: `ruff` clean, `mypy` clean over 157 files, 753 tests passing in
`tests/unit` and the packages, of which 116 are the engine's own, 33 the
store's and 7 the template route's. `product-import.test.ts` passes 52 cases
in the generator, and `turbo run lint typecheck test build` on the same
product finished 71 of 71 tasks.

**Against PostgreSQL, the same day**, on a private PostgreSQL 17 cluster
because the Docker engine did not answer: all 30 migrations applied in
order on a clean database, every one of the 23 isolation suites exit 0 as a
role with no `BYPASSRLS`, the removed-force mutation check refused, and
`tests/integration/test_import_commit_rls.py` passed its four cases against
the round-trip database. `testing/runs/2026-09-29-01/README.md` is the
record.

**In a browser, the same day**, with the fixture target installed as CI
installs it: the whole Playwright suite, and the round-trip imports suite
rerun after two defects the first run found in the new control -- the panel
listed CSV before Excel and stayed open after a download -- and one manual
case 53 found in the page: the history table's screen-reader-only heading
escaped its scroll wrapper and the page scrolled sideways at 375 pixels with
a target rendered, which nothing had measured before because the frame suite
runs that width with no target. All three fixed the same day, the third with
a permanent round-trip case.

**Not executed:** manual cases 42 to 52, which need Excel, an upload with a
bucket and a queue, or a target with a writer or a matcher.

**Remote CI, the authoritative run**, on commit
`090dfa95d482845ee347f348235721dcc1b6f9c5` pushed 2026-09-29: CI 36640086463,
Security 36640086378 (gitleaks executed and passed) and Generator Integration
36640086477 all green, the last against PostgreSQL 16.15 with pgvector, with
the fixture installed and 179 browser cases passing on the full product row.
The run record has the table.

## What has not been done

- **No manual pass.** `manual-test-plan.md` here has the cases; every verdict
  is blank.
- **IMPORT-DEF-014 is closed and verified, as of 2026-10-02, so it has left
  this list too.** `source_bytes` could not read a source from a real
  bucket. It was fixed on 2026-10-02 -- the store is called on a thread, and
  the object is held to the size and, where the provider verified one, the
  digest its index row recorded -- in `2db0dc4`, merged as `eba279c` in PR
  #29, with CI, Security and Generator Integration green on both commits and
  the 512 MiB capped measurement repeated against real object storage. This
  entry said until those runs passed that it was verified locally and an
  activation constraint. The constraint is lifted at the Starter; **no
  product has activated imports**, `docoris`'s alignment is next, and OD-12
  stays blocked. FOLLOW_UPS F31, and `worker-resource-envelope.md` here for
  the evidence.
- **GR-352 itself is closed, verified, and its NFRs ratified**, on
  2026-10-02, so it has left this list. This entry said until then that it
  was open and a release gate, waiting on an NFR decision nobody had taken.
  GR-352A, GR-352B, GR-352C and GR-352E bounded the file, the two API
  routes, the worker and the worker's other heavy jobs, and measured each;
  the owner ratified the limits as they stood. IMPORT-DEF-013, and
  `worker-resource-envelope.md` here for the contract.
- **No live run.** Nothing has imported a file through a deployed product.
  Neither the dry run nor the commit has executed against a real Redis, a real
  bucket and a real scanner.
- **No independent review of Phase 2.** Closed 2026-09-22: four reviewers, one
  per seam, all four returning BLOCK. `phase-2-review.md` is the record, and
  the headline was that the commit path had never worked.
- **No live template has been downloaded from a deployed product**, and no
  workbook filled in Excel has been imported through one. `manual-test-plan.md`
  cases 41 onward are the pass.
- **No product declares a target, so nothing renders the page.** A generated
  product declares none and should not — a target names a table the product
  owns. `koras-e2e-shop` had a domain that could declare real ones and was
  brought level on 2026-09-22, which made the panel render in a browser for the
  first time; that repository is being torn down, so the gap returns. What
  closes it for good is a fixture target installed by `Generator Integration`
  rather than a domain invented in the template.
