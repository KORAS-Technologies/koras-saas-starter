# Data import: downloadable templates and formats — analysis before implementation

Written 2026-09-29, against the repository as it stood at `2fe5701`. This is
the analysis a brief asked for before any code: what the repository already
has for data import, what the brief asks for beyond it, and the decisions that
have no accepted record and therefore need approval first. **Nothing in this
document had been built when it was written; the decisions were resolved
the same day and implementation followed** — see the end of section 18. Where it names a file, a column or a route that does
not exist, the name is a proposal and appears in a fenced block rather than in
prose, which is the convention that keeps the documentation tests honest.

The brief is the one headed *Data Import Framework with Downloadable Import
Templates*: download a template in a chosen format, upload it filled in,
validate, preview, confirm, process in the background, and read the results
or the error report. Read `README.md` and `architecture.md` in this directory
first; they describe the two phases that exist, and this document does not
repeat them.

## Contents

1. Gap analysis
2. Proposed architecture
3. Feature requirements
4. User stories and acceptance criteria
5. Import definition registration model
6. Download Template design
7. Format selection UX
8. API contracts
9. Validation architecture
10. Background job design
11. Results and error report design
12. Security and privacy analysis
13. Audit model
14. Test plan
15. Migration and backward compatibility
16. Documentation changes
17. Affected packages and files
18. Decisions that need approval before implementation

## 1. Gap analysis

Everything below was read from the code on 2026-09-29, not from the documents
about it.

### What exists and is reused as it stands

| Brief item | State | Where |
|---|---|---|
| Import definition registry | **Built.** `ImportTarget`, `FieldSpec`, `TargetRegistry`, one empty product-owned list, a duplicate key raising at import | `profiles/product/template/python-packages/koras-import/src/koras_import/targets.py`, `profiles/product/template/services/api/koras_api/imports/targets.py` |
| Upload through storage, scanning, quota, retention | **Built.** An ordinary `/files` ticket on the `imports` category; a file whose scan is pending, skipped or infected is never parsed | `profiles/product/template/services/api/koras_api/core/imports.py` |
| File size and extension limits | **Built** at the ticket, from `files.maxUploadSizeMb` and `files.allowedExtensions` inside the 5 GiB ceiling; a 64 MiB source ceiling on top | `profiles/product/template/services/api/koras_api/core/storage.py` |
| CSV parsing: encoding, delimiter, header, bounded rows, cell ceiling | **Built.** | `profiles/product/template/python-packages/koras-import/src/koras_import/reading.py` |
| Field mapping, suggestion, allowlist refusal | **Built.** Unknown target fields are refused rather than dropped; a required field nobody mapped is refused by name | `profiles/product/template/python-packages/koras-import/src/koras_import/mapping.py` |
| Validation: required, type, enum, date, number, email, length, extra cells, in-file duplicates, product rule | **Built**, one pass, every problem in every row, capped at 1,000 reported | same file |
| Preview | **Built** as a head of 200 rows in a plain table, plus total, valid and error counts | `profiles/product/template/apps/web/src/app/dashboard/imports/ImportPanel.tsx.hbs` |
| Explicit confirmation before writing | **Built.** A second act, recorded as `committed_by` | `profiles/product/template/services/api/koras_api/routers/imports.py` |
| Duplicate behaviour per target | **Built.** `Operation` is create, update, upsert, skip_duplicate; the target declares which it permits and the run chooses one | `targets.py` |
| Background processing on the platform queue | **Built.** Two declared tasks on `koras-queue`, ARQ underneath, `attempts=1`, two idempotency locks on the commit | `profiles/product/template/python-packages/koras-import/src/koras_import/jobs.py`, `profiles/product/template/services/worker/koras_worker/tasks/imports.py` |
| Survives leaving or reloading the page | **Built.** The run row is the state; the page polls it and any past run opens from the history | `ImportPanel.tsx.hbs` |
| Atomic commit through a product-declared writer | **Built.** | `profiles/product/template/python-packages/koras-import/src/koras_import/writing.py` |
| Error report download | **Built** as a CSV the browser writes from the paged report: row, column, field, problem, value; every cell quoted and formula-guarded | `ImportPanel.tsx.hbs`, `actions.ts.hbs` |
| Completion notice | **Built**, in-app only, through the one dispatch point | `profiles/product/template/services/api/koras_api/core/import_notify.py` |
| Audit | **Part built.** Three actions: `import.run.started`, `import.run.committed`, `import.run.refused`. The upload itself is recorded by the files router as `storage.object.uploaded` | `core/imports.py`, `routers/files.py` |
| RBAC | **Built.** `imports.manage` on every route including reads, plus the target's own permission on every route that resolves one | `routers/imports.py` |
| Tenant isolation | **Built.** Both tables under forced row-level security with an update check; an isolation suite; a cross-tenant read answers 404 | `profiles/product/template/supabase/migrations/00036_imports.sql`, `profiles/product/template/supabase/tests/320_imports_isolation.sql` |
| Capability gating | **Built.** `data_import`, off by default, requires `notifications`, a template map of fourteen paths | `profiles/product/manifest.yaml` |
| Spreadsheet library | **Declared.** `openpyxl` is a dependency of the API and of `koras-reporting`, which writes workbooks; `core/knowledge.py` reads one for indexing | `profiles/product/template/services/api/pyproject.toml.hbs`, `profiles/_shared/template/python-packages/koras-reporting/src/koras_reporting/export.py` |
| A download route handler pattern | **Exists** for report exports: same-site check, permission, the caller's token, the API's bytes streamed with its headers | `profiles/product/template/apps/web/src/app/api/reports/[key]/export/route.ts.hbs` |
| A format chooser | **Exists** for exports as one plain anchor per format, deliberately, so the router never prefetches a download | `profiles/product/template/packages/ui/src/reporting/export-menu.tsx` |
| A disclosure menu pattern | **Exists** in the shell: a button with `aria-expanded` over a panel of links, Escape and outside click to close, no `role="menu"` by a stated decision | `profiles/product/template/packages/ui/src/shell/profile-menu.tsx.hbs` |

### What the brief asks for that does not exist

| Brief item | Gap | Size |
|---|---|---|
| Download Template button and format option | Nothing. No generator, no route, no control, no audit action | The centre of the work |
| Template generation from the canonical definition | Nothing. `FieldSpec` carries name, label key, kind, required, max length and options; it has no example value, no help text and no format guidance, so a template rendered from it today would be headers alone | Engine change |
| XLSX and JSON reading | Declared in `Format` and in the table's check constraint, refused by the reader. IMPORT-GAP-003 is part closed for this reason | Engine change |
| Template and schema versioning | Nothing. A target has no version; the run stores nothing about the template it came from; the reader compares headers to fields and nothing else | Engine and store change |
| The run's format | The `format` column exists and is always its default: the insert in the run store never sets it | Store fix |
| Upload display: selected file name and size, maximum file size | The input resets after upload and the panel shows nothing about the file; the row ceiling and formats are shown, the byte ceiling is resolved on the server and never reaches the page | Page and API change |
| Preview: duplicate rows, rows expected to create, update and skip | In-file duplicates are counted only as errors; expected create, update and skip cannot be known because only the product's writer can look a record up, and the dry run never calls the product | Needs a new seam on the target |
| Preview pagination or the shared table | A 200-row head in a plain table. The shared table gained a server-paging seam on 2026-09-19 and the preview does not use it | Page change |
| Duplicate strategy: reject | The `create` operation exists, but with no way to look a record up at validation time a duplicate is discovered by the writer during the commit, which refuses the whole run | Same seam as above |
| Duplicate strategy: manual review | Nothing, and no state in the machine for it | New states and a review surface |
| Results: created, updated, skipped as separate figures | The writer returns all three and the store folds them into `rows_total` and `rows_valid`; the page says "wrote N of M" | Store and schema change |
| Job id, queued state, progress counts | The queue answers a job id and the run does not store it; `commit_requested` is the queued state; progress counts were deliberately not built (Phase 2, and `architecture.md` says why) | Store change; the counts are a decision |
| Error report usable for re-import | The report lists problems, not the source with a status column; the plan's original shape was replaced on purpose in Phase 2 | A decision |
| Audit: template downloaded, validation completed, validation failed, completed, failed | Absent. Validation and commit outcomes are on the run row rather than in the audit table, a Phase 2 decision recorded in `docs/features/STATUS.md` | A decision |
| Field labels and help in the interface | `label_key` reaches the browser in the target view and the panel renders the raw key and the raw field name; the keys exist only in the product's own message catalogue | Page change |

### The three carried findings this work has to take with it

Three medium findings carried in `phase-2-review.md` become blocking once a
workbook is read, because a workbook cell arrives typed rather than as text:

- **IMP2-19**: the parsed date is discarded and the original string handed
  on. A workbook date is a `datetime`, and the writer must receive one shape.
- **IMP2-18**: `float()` accepts `nan` and `inf`. A workbook can hold both as
  numbers.
- **IMP2-21**: a NUL byte passes every check. A workbook string can carry one.

And **IMP2-15**, that the 64 MiB ceiling bounds the transfer and not the
memory, matters more for a compressed format: a small workbook can expand by
two orders of magnitude.

## 2. Proposed architecture

The shape stays what it is. The engine gains a template renderer and two more
readers; the run store learns the format and the counts; the API gains one
download route; the page gains one control and three figures. No new package,
no new job, no new table.

```
python-packages/koras-import/src/koras_import/
  targets.py       FieldSpec gains example, help and a date/number hint;
                   ImportTarget gains a version and an optional matcher
  templates.py     NEW. render(target, format) -> bytes. Pure: no session,
                   no tenant, no locale. Reads the declaration and nothing else
  reading.py       CSV as today, plus a common Header/Row shape the two new
                   readers produce
  reading_xlsx.py  NEW. openpyxl read_only + data_only, first sheet or the
                   sheet named "Data", bounded by rows, cells and bytes
  reading_json.py  NEW, if JSON is approved (section 18): an array of objects
  compatibility.py NEW. fingerprint(target) and compare(target, header):
                   compatible / compatible-with-unknown-columns / incompatible
  mapping.py       normalises a parsed date to ISO and a decimal to a canonical
                   string (IMP2-19); refuses non-finite numbers (IMP2-18)

services/api/koras_api/
  routers/imports.py   + GET /imports/targets/{key}/template?format=
                       + TargetView carries version, formats, limits and the
                         richer field view
                       + POST /imports stores the format and refuses one the
                         target does not accept
                       + AnalysisView carries the compatibility verdict
  core/imports.py      + format on create; rows_created/updated/skipped and
                         the predicted counts on the run; the four new audit
                         actions declared beside the three existing ones

services/worker/koras_worker/tasks/imports.py
                       validate_run reads any accepted format; calls the
                       target's matcher when one is declared and records the
                       predicted counts; records validation audit rows the way
                       _tell already reaches the dispatch point

supabase/migrations/00038_import_counts.sql
                       NEW. Nullable columns for the written and predicted
                       counts, the template version, the job id

apps/web/src/app/api/imports/[key]/template/route.ts
                       NEW route handler, the export handler's twin
apps/web/src/app/dashboard/imports/
  ImportPanel.tsx      the Download Template control, the file summary,
                       the preview figures, the results table
  actions.ts           unchanged in shape; two new reads
packages/ui/src/primitives/download-menu.tsx
                       NEW. A disclosure over plain anchors: the profile
                       menu's pattern with the export menu's anchors
```

**What the engine still never knows.** A table name, a product concept, a
tenant, a session. The renderer takes a declaration and returns bytes; a
test can render every target of every product without a database. The
matcher, like the writer, is the product's own callable and the engine only
calls it.

**Why the API renders the template and not the web application.** The
canonical definition is Python; rendering it anywhere else means a second
description of the schema, which is what the brief forbids. The web route
handler streams what the API answers, exactly as report exports do.

## 3. Feature requirements

Numbered so the test plan can point at them.

| # | Requirement |
|---|---|
| R1 | The Imports page offers one **Download Template** control per selected target, with a format choice among the formats the target accepts |
| R2 | A template is rendered from the target declaration at request time; there is no second definition anywhere |
| R3 | An XLSX template has a Data sheet whose first row is the field names, and an Instructions sheet listing every field with required or optional, type, format guidance, allowed values, an example and help text |
| R4 | An XLSX template applies data validation to enumerated, date, integer and decimal columns over a bounded range of rows |
| R5 | A CSV template is UTF-8 with a byte-order mark, its header is the field names, and it carries no metadata row |
| R6 | A template carries the target's version and a fingerprint of its fields, visibly in the Instructions sheet and as a document property in XLSX; a CSV carries neither and is judged by its header |
| R7 | The analysis of an uploaded file states whether it is compatible with the target as declared today, and names missing required columns and unknown columns |
| R8 | The page shows, before upload, the accepted formats, the byte ceiling, the row ceiling and the target; after choosing a file, its name and size |
| R9 | A workbook is parsed with the same bounds as a CSV, plus a decompressed-size bound, and a formula cell contributes its cached value or nothing |
| R10 | The preview shows total, valid, invalid and in-file duplicate rows, and — when the target declares a matcher — the rows the import would create, update and skip; for a target without a matcher the page says the figures are unknown rather than showing zeros |
| R11 | The run records the format it was read from, the template version it matched, the job id of its last enqueue, and after a commit the created, updated and skipped counts separately |
| R12 | The results card shows total, created, updated, skipped and failed as a table, and offers the error report when problems exist |
| R13 | Every template download, validation outcome and commit outcome is an audit row carrying tenant, actor, target, format, version, run id and counts, and never a cell value |
| R14 | Every new route checks `imports.manage` and the target's permission; a template for a target the caller may not import is a 403 before any bytes are rendered |
| R15 | Every new control is keyboard-operable with a visible focus ring, and the page stays usable at 375 pixels |

## 4. User stories and acceptance criteria

Numbered after the last story in `docs/platform/execution/CAT-02-data-import.md`.

| ID | As a | I want | Acceptance |
|---|---|---|---|
| IMPORT-US-019 | organisation admin | to download a template for a target | The control appears for every target I may import and for none I may not; the file opens in a spreadsheet with the field names as headers |
| IMPORT-US-020 | organisation admin | to choose the template's format | One control offers CSV and XLSX; a target that accepts CSV alone offers CSV alone; the choice is reachable by keyboard and closes on Escape |
| IMPORT-US-021 | organisation admin | the template to tell me how to fill it in | The XLSX Instructions sheet names every field, whether it is required, its type, its format, its allowed values and an example; an enumerated column refuses a value outside the set inside the spreadsheet |
| IMPORT-US-022 | organisation admin | to upload the filled template in the format I downloaded | A CSV and an XLSX of the same rows validate to the same verdict |
| IMPORT-US-023 | organisation admin | to be told when my template is out of date | A file from an older version of the target is named as such at analysis; missing required columns and unknown columns are listed by name |
| IMPORT-US-024 | organisation admin | to see what an import would do before confirming | The preview shows total, valid, invalid and duplicate rows; where the product can look records up, the rows that would be created, updated and skipped |
| IMPORT-US-025 | organisation admin | to see what an import did | After a commit the card shows total, created, updated, skipped and failed; the history row shows the same figures later |
| IMPORT-US-026 | organisation admin | to see the file I chose | Its name and size are shown beside the target and the ceilings, before and after the upload |
| IMPORT-US-027 | product engineer | to declare examples and help on a field once | The template, the Instructions sheet and the mapping page all draw from the one declaration |
| IMPORT-US-028 | auditor | to know who downloaded a template and how every run ended | The audit page lists template downloads and validation and commit outcomes with counts and no row content |

## 5. Import definition registration model

The brief's `registerImportDefinition` example is TypeScript. The repository's
registration mechanism is Python, built at import, and it is the same shape
reports, audit actions, settings and notification kinds use. It is kept; the
brief says to follow the existing mechanism where one exists.

What changes is the declaration, not the registry:

```python
FieldSpec(
    "name",
    "import.field.accounts.name",
    kind=FieldKind.TEXT,
    required=True,
    max_length=200,
    example="Example Account",          # NEW, synthetic, product-authored
    help="The legal name as registered",  # NEW, plain text, one language
)

ImportTarget(
    key="crm.accounts",
    label_key="import.target.crm.accounts",
    permission="imports.manage",
    fields=(...),
    match_keys=("email",),
    operations=(Operation.SKIP_DUPLICATE, Operation.UPSERT),
    formats=(Format.CSV, Format.XLSX),
    version=2,                            # NEW, bumped when a field's meaning changes
    matcher=find_existing,                # NEW, optional: which match keys exist
    writer=write_accounts,
)
```

**The example is optional and synthesised when absent**, per kind: a text
field gets a short generic phrase, an integer gets a small number, a decimal a
number with a point, a date the ISO form of a fixed day, an email an address
on `example.com`, a boolean `yes`, an enumerated field its first option. The
synthesis is deterministic, so two renders agree and a test can pin them.

**The help text is plain text in one language**, and this is a limitation
stated rather than hidden. The product's label keys resolve in the web
application's message catalogue and nowhere in Python; the only Python
catalogue in the estate is `koras_email`'s, and it holds mail. Rendering the
template in the API means the Instructions sheet can carry the field name and
the product's plain-text help, and cannot carry the localised label. The
trigger to revisit is a Python message catalogue for product keys, which no
feature has needed.

**The version is an integer the product owns.** The engine does not bump it: a
field added as optional is compatible with every older file, and a field
renamed is not, and only the product knows which change it made. What the
engine adds is a fingerprint of the declared fields, so a template from a
target that changed without a bump is still recognised as different.

**The matcher is the writer's reading half.** An async callable taking the
caller's session and the tuple of match-key values of every valid row, and
answering which of them exist. Optional, so every existing target stays valid
unchanged. Declared on the target because looking a record up is the one thing
in the dry run that needs a product table name, and the target is where such a
name is allowed to live.

## 6. Download Template design

**Where.** In the start card, beside the target and operation pickers, above
the file input, because the flow the brief describes starts there.

**What it renders.** One `Download Template` button. Activating it opens a
panel holding one plain anchor per format the selected target accepts, each
pointing at the web route handler with the format in the query. A target that
accepts one format renders the panel with one anchor rather than skipping the
disclosure, so the control behaves the same way for every target.

**Why anchors and a route handler, not a server action.** A server action
returns a value and a download is a body; the export route handler exists for
exactly this reason and is copied. The anchors are `ButtonLink`s, which render
a plain anchor for any `/api/` href so the router never prefetches — a
prefetch would be a template download recorded in the audit table as if
somebody had asked for it.

**The XLSX workbook.**

```
Sheet "Data"
  Row 1    field names, bold, required ones with a distinct fill, each with a
           cell comment holding the help text and the format guidance
  Rows 2+  empty; data validation applied from row 2 to row max_rows + 1,
           capped at 10,000 rows so the file stays small:
             options  -> list validation, the declared options
             date     -> date validation, with the ISO form in the prompt
             integer  -> whole-number validation
             decimal  -> decimal validation
           column widths set from the longer of the name and the example

Sheet "Instructions"
  Target, version, fingerprint, the date rendered, the row ceiling
  One row per field: Column | Required | Type | Format | Allowed values |
                     Example | Help
  Three sentences: dates as YYYY-MM-DD; decimals with a point and no
  thousands separator; yes/no for booleans
  Which sheet is read, and that the header row must not be renamed

Document properties
  A custom property carrying "target/version/fingerprint"
```

The Data sheet holds **no example row**. A row of synthetic values in the
sheet a customer fills in is a row that gets imported by whoever forgets to
delete it, and there is no mark a header-parsing reader can trust to tell it
from data. The examples live in the Instructions sheet and in the header
comments, which is where a person filling the sheet looks.

**The CSV.** The header row alone, UTF-8 with a byte-order mark so that a
spreadsheet opens it with accents intact, a comma delimiter, CRLF line ends,
and no example row for the same reason. The brief allows an example row
"where appropriate", and a file with no way to mark one is not the place.

**The filename.** The target key with its dots replaced by dashes, then
`-template-v` and the version, then the extension, set by the API in its
content-disposition header and carried by the route handler.

**Formula guard.** Every string the renderer writes — a field name, an option,
an example, a help text — passes the same guard the reporting writer applies
to a cell beginning with `=`, `+`, `-`, `@`, tab or carriage return. The
values are the product engineer's rather than a customer's, and the guard is
three lines, and the file is opened by the one person a product least wants
to surprise.

## 7. Format selection UX

The brief asks for one control with a format option, and the design system
has two things to say to that.

`ExportMenu` renders one anchor per format side by side, with the reason
written on it: anchors are what a download needs and what a router will not
prefetch. `ProductProfileMenu` is a disclosure — a button with `aria-expanded`
and `aria-controls` over a panel rendered in both states, closed by Escape and
by an outside click — and its docstring says why it is not a `role="menu"`:
a real menu takes arrow-key handling and roving focus, and a panel of links
does not need them.

The proposal combines the two into one new primitive in `packages/ui`, a
download menu: a `Button` that discloses a panel of `ButtonLink` anchors.
Keyboard: Tab reaches the button, Enter or Space opens the panel and moves
focus to the first anchor, Tab walks the anchors, Escape closes and returns
focus to the button, and the panel closes when focus leaves it. No arrow keys,
no `role="menu"`, no library. At 375 pixels the panel opens below the button
at full width.

The alternative — the export menu's row of anchors, one per format — is the
design system's existing answer and needs no new primitive. The brief asks
not to do that unless the design system requires it, and it does not require
it; it merely has it. This is a design-system addition, listed in section 18
for a decision rather than made quietly.

## 8. API contracts

All under `/api/v1`, all behind `imports.manage` and the target's permission,
all tenant-scoped. Unchanged routes are listed for completeness with their
additions marked.

```
GET  /imports/targets
     TargetView gains:
       version: int
       fingerprint: str                  12 hex characters
       template_formats: [str]           the formats a template can be rendered in;
                                         csv and xlsx today, json if approved
       limits: { max_bytes: int, max_rows: int }
     FieldView gains:
       max_length: int | null
       example: str
       help: str
       format_hint: str                  "YYYY-MM-DD", "decimal point", "yes/no", ""

GET  /imports/targets/{key}/template?format=csv|xlsx
     200  the file; Content-Type per format; Content-Disposition attachment
     403  imports.manage missing, or the target's permission missing
     404  no such target
     406  a format the target does not accept, or that cannot be rendered
     Audited as import.template.downloaded, outcome ok, before the bytes are sent

POST /imports
     NewRun gains nothing. The format is inferred from the file row the run
     is started against — its name's extension, then its content type — and
     stored on the run. A format the target does not accept is a 422 with
     its own error code.

GET  /imports/{run_id}/analysis
     AnalysisView gains:
       format: str
       sheet: str | null                  the workbook sheet that was read
       template: {
         verdict: "compatible" | "unknown_columns" | "incompatible"
         version_found: int | null        from the XLSX property; null for CSV
         missing_required: [str]
         unknown_columns: [str]
       }

GET  /imports/{run_id}        and every route answering RunView
     RunView gains:
       format: str
       template_version: int | null
       job_id: str | null
       source_name: str | null
       source_bytes: int | null
       rows_duplicate: int
       predicted: { create: int, update: int, skip: int } | null
       written:   { created: int, updated: int, skipped: int } | null
```

Web route handler, same-site only, the caller's own token:

```
GET  /api/imports/{key}/template?format=csv|xlsx
     Streams the API's answer with its type and filename; 403 and 406 become a
     sentence in the reader's language, as the export handler does.
```

The format, the sheet and the two count objects are the only additions the
page reads on the hot path; the rest is for the history table and support.

## 9. Validation architecture

**One `Header` and one `Row` for every format.** The CSV reader already yields
both; the workbook and JSON readers yield the same two shapes, so `mapping`
and `validate` do not change for a new format. A workbook reader turns every
typed cell into the text the validator expects before it is seen, and this is
where IMP2-19 stops being a carried finding: a `datetime` cell becomes its
ISO date; a numeric cell becomes a canonical decimal string; a boolean cell
becomes `true` or `false`; `None` becomes an empty string; `nan` and `inf`
are refused at the cell with `import.error.decimal`.

**Where each check happens, in order.**

| Check | Where | Existing |
|---|---|---|
| File type | The upload ticket refuses an extension outside `files.allowedExtensions`; starting a run refuses a format the target does not accept | Half |
| Template compatibility | The analysis, from the header and, for XLSX, the property | New |
| Required columns | `resolve`, at mapping time, refused by name | Yes |
| Unsupported columns | Ignored at mapping time by design (a column that maps to nothing is dropped) and **named** in the compatibility verdict so a person sees them | Half |
| Required values, types, enum, date, number, length, email | `validate_row` | Yes |
| Business validation | The target's own validator | Yes |
| Duplicates within the file | `validate`, by match keys | Yes |
| Duplicates against existing records | `validate_run` in the worker, through the target's matcher when declared; the outcome depends on the operation: with `create` an existing match is a row error, with `skip_duplicate` a skip, with `update` or `upsert` an update | New |
| Row ceiling, byte ceiling, cell ceiling | `count_rows`, `check_source`, the reader | Yes |
| Decompressed-size ceiling | The workbook reader, from the zip directory before any sheet is opened | New |

**Errors already identify row, column, field, code and a bounded value.** The
"recommended correction" the brief asks for is the sentence for the code, in
three languages, on the page; the codes are stable and the problem file
carries the sentence. No per-error free text is added, because a sentence
generated in the worker would be one language.

**Unsupported columns are named, not refused.** The mapping page's whole
purpose is that a customer's export does not have to match a template
(IMPORT-US-002), so a column the target does not know maps to "do not
import". The compatibility verdict lists such columns so a person who
downloaded the template and renamed a heading is told.

## 10. Background job design

Nothing new is enqueued. The two tasks stay, with the same retry policy and
the same idempotency, for the reasons `architecture.md` gives and this
document does not overturn.

| Brief state | What it is here |
|---|---|
| Job ID | `Enqueued.job_id`, stored on the run at each enqueue |
| Queued | `validating` before the worker picks it up; `commit_requested` |
| Processing | `validating` once picked up; `committing` |
| Completed | `validated`; `committed` |
| Completed with errors | `validation_failed` — the dry run's outcome. A commit has no such state: it is all or nothing by Phase 2's acceptance criterion |
| Failed | `failed`, with a safe sentence |
| Progress and counts | Counts after validation and after commit. No counter during either, because the commit is one transaction and a counter written outside it is the partial-import evidence the phase forbids |
| Retry | `attempts=1` on both tasks; a person re-runs the check, and a failed commit is a new run |
| Idempotency | The state machine refuses a second request and the enqueue carries `commit:{run_id}` |

Two things the brief lists are decisions rather than gaps and are in section
18: a progress counter, and a commit that completes with errors.

**The matcher runs inside `validate_run`**, on the worker's tenant-bound
session, after the row validation and before the counts are recorded. It is
read-only, and the worker wraps it in a savepoint so that a matcher that
raises leaves the run's own rows intact — the rule the outbox work found on
2026-09-23 about a swallowed error on a shared session.

## 11. Results and error report design

**The results card**, for a committed run:

```
Import complete

Total      1,000
Created      820
Updated      100
Skipped       80
Failed         0
```

`Failed` is zero for every committed run and equal to `Total` for every failed
one, because a commit is atomic. The row is drawn anyway, because a table a
person compares across runs should have the same rows every time, and a
missing row reads as a figure withheld.

For a run that ended in `validation_failed` the card shows total, valid,
invalid and duplicate, which is what the dry run knows.

**The error report** stays the browser-built CSV — row, column, field,
problem, value — with one column added: the run's operation and the problem's
consequence, so a row that would be skipped reads differently from a row that
would be refused. It is not the source file with a status column appended.
That artefact, which the plan originally described and Phase 2 deliberately
replaced, is listed in section 18 as a decision because it costs a worker
write to the exports category and a sweep to expire it.

**Per-row outcomes after a commit are not available**, and the brief's error
report for a completed import therefore has nothing to list: the writer
returns counts, and asking it for one status per row is a change to the
writer contract that every product with a writer would have to follow.
Listed in section 18.

## 12. Security and privacy analysis

Everything the import already enforces holds for the template route because
it is the same router, the same dependencies and the same permission helpers.
What is new is listed.

| Concern | Position |
|---|---|
| Permission before download | `imports.manage` and the target's permission, checked before the renderer is called; a 403 renders nothing |
| Tenant isolation of the template | The template carries no tenant data by construction — the renderer takes the declaration and nothing else — and the audit row is written on the tenant's context |
| Unauthorised fields | A template can only name fields the target declares, which is the allowlist the mapping already enforces |
| Formula injection on the way out | Every rendered string is guarded as the reporting writer guards a cell |
| Formula injection on the way in | Cells are read with cached values only, so a formula contributes its last value and never runs; a cell whose first character is a formula trigger is data, and the error report guards it on the way out as it already does |
| Zip expansion | A workbook is a zip. The reader sums the uncompressed sizes from the zip directory before any sheet opens and refuses past a ceiling; the compressed size is bounded by the existing 64 MiB source ceiling |
| Cell and row bounds | The 32 KiB cell ceiling and the target's row ceiling apply to every format; a workbook is read in streaming mode so the file never sits in memory as a sheet |
| Macros and external links | Macro-enabled and binary workbook extensions are outside the extension default and the reader refuses any content type other than the spreadsheet one; external-link parts are not followed |
| XML parsing | `openpyxl` binds `lxml` when installed and the standard library's parser otherwise. Which one the image carries, and whether an entity-expansion guard is needed, is a check for the security review rather than an assumption here |
| JSON depth and size | If JSON is approved: the standard parser over bytes bounded by the same ceiling, an array of flat objects required, nesting refused |
| Sensitive values in errors | Unchanged: a value is cut to 120 characters in the report and 200 in the table, and the audit rows carry counts and never a cell |
| Temporary files | None. The renderer writes to memory and the readers stream from bytes already in memory under the source ceiling |
| Cross-tenant | The template route reads no row; the run routes are unchanged and the isolation suite already covers them; a negative test for the template route asserts that tenant A's token and tenant B's target key still answer by permission alone, since the catalogue is code and not per tenant |
| Rate | A template render is a few kilobytes of CPU; the route sits behind the API's existing limiter and needs no special rule |

## 13. Audit model

The three actions stay. Four are added, named in the repository's own
`import.run.*` and `import.template.*` shape rather than the brief's flat
names, because a registry key is the thing the audit page filters on and the
existing three set the convention. The mapping to the brief's minimum is
explicit:

| Brief name | Action | Class | Outcome | Details |
|---|---|---|---|---|
| `import.template_downloaded` | `import.template.downloaded` | activity | ok | target, format, version, fingerprint |
| `import.uploaded` | `storage.object.uploaded` (exists) plus the file id added to `import.run.started` | activity | ok | target, operation, format, file id, size |
| `import.validation_completed` | `import.run.validated` | activity | ok | target, format, version, job id, rows, valid, errors, duplicates, predicted counts |
| `import.validation_failed` | `import.run.validated` | activity | error | the same |
| `import.started` | `import.run.committed` (exists) | audit | ok | target, operation, rows, job id |
| `import.completed` | `import.run.finished` | audit | ok | target, created, updated, skipped |
| `import.failed` | `import.run.finished` | audit | error | target, the safe sentence |

One kind per moment with the outcome as the outcome column rather than two
kinds per moment: it is how `import.run.refused` already records a denial,
and it means a filter on the action finds both halves.

**Two of the four are written by the worker**, which reverses the Phase 2
position that the outcome lives on the run row alone. The reason that
position was taken — the worker would need the API's configuration surface —
stopped being true on 2026-09-20 when IMPORT-DEF-008 moved the one import
that needed it to the point of use; the worker's notice already reaches the
dispatch point by name, and `record` in `core/audit.py` takes a session and
nothing else. The decision is in section 18 because it is a reversal, and
reversals are recorded rather than slipped in.

## 14. Test plan

Each row names the brief's item, the kind of test, and where it lives. Every
new assertion asks what the code does rather than what it says, which is the
FW-HARDEN-001 lesson this repository has now paid for four times; a template
test renders a file and opens it again.

| Brief item | Test | Where |
|---|---|---|
| Download Template button | Browser: the control renders for the fixture target and not for a member without the permission | `e2e/roundtrip/imports.spec.ts` |
| Format dropdown | Browser: opens on Enter, lists the fixture's formats, closes on Escape with focus back on the button; component test for the primitive | roundtrip spec; a new spec beside the primitive |
| XLSX generation | Render the fixture target, load the bytes with `openpyxl`, assert the sheets, the header, the validations, the property | the engine's own tests |
| CSV generation | Render, decode, assert the BOM, the header and nothing else | same |
| JSON generation | Only if approved | same |
| Correct headers | The Data header equals the field names in declaration order, for every target in the registry | same, parametrised |
| Required and optional | The Instructions rows and the header fill agree with the required flag | same |
| Template versioning | Bump the version and the property changes; change a field and the fingerprint changes; the analysis verdict names a missing required column and an unknown one | same, plus `tests/unit/test_imports.py` |
| Upload | Existing ticket tests, plus a run started against an `.xlsx` file stores `xlsx` | `tests/unit/test_imports.py` |
| Missing columns | Existing | `koras-import/tests/test_import.py` |
| Unsupported columns | The verdict lists them and the mapping still resolves | same |
| Invalid values | Existing, plus a workbook whose typed cells produce the same errors as their CSV text | same |
| Date and number parsing | A workbook date, a workbook float, `nan`, `inf`, a NUL byte | same |
| Enum validation | Existing, plus the workbook's list validation is present on the enumerated column | same |
| Duplicate handling | Existing in-file case, plus a matcher double: create refuses, skip counts, upsert updates | `tests/unit/test_imports.py` |
| Preview counts | The predicted counts land on the run and the view; without a matcher they are null and the page says so | unit and roundtrip |
| Field mapping | Existing | engine tests |
| Large imports | A workbook at the row ceiling passes and one row over is refused; a zip whose directory claims more than the decompressed ceiling is refused before a sheet opens | engine tests |
| Partial failures | Existing commit cases, unchanged | `tests/integration/test_import_commit_rls.py` |
| Background processing | Existing, plus the job id is stored | unit |
| Retry and idempotency | Existing | generator test, unit |
| Results | `record_commit` stores three figures and the view carries them; the card renders the five-row table | unit, roundtrip |
| Error report generation | Existing roundtrip case, plus the added column | roundtrip |
| RBAC | The template route answers 403 without the permission and without the target's permission; a mutation check removes one helper and expects red | `tests/unit/test_imports.py` |
| Tenant isolation, cross-tenant | Existing isolation suite; the audit row for a download lands under the caller's tenant | `320_imports_isolation.sql`, unit |
| Accessibility | Keyboard walk of the menu; focus after download stays on the button; the results table has a caption | roundtrip at 1440 and 375 |
| Keyboard operation of the menu | As above | roundtrip |
| Responsive | The start card and the menu at 375 | `e2e/imports.spec.ts` |
| Generator structure | The new files are in the `data_import` template map, in both the manifest and the worker image; the new audit actions are registered; the three languages carry every new key | `generators/create-koras-app/tests/product-import.test.ts` |

**What no automated test in the estate reaches**, to be added to
`manual-test-plan.md` as cases 41 onward: a template downloaded from a
deployed product, filled in Excel, saved, uploaded and committed; the same
file saved as CSV from Excel on Windows; a workbook with a formula cell; the
Instructions sheet read by a screen reader.

## 15. Migration and backward compatibility

**One migration**, gated with the rest of the capability by the manifest's own
rule, since nothing outside the capability reaches the table:

```sql
-- 00038_import_counts.sql
alter table public.import_runs
  add column template_version integer,
  add column job_id           text,
  add column rows_duplicate   integer not null default 0 check (rows_duplicate >= 0),
  add column predicted_create integer,
  add column predicted_update integer,
  add column predicted_skip   integer,
  add column rows_created     integer,
  add column rows_updated     integer,
  add column rows_skipped     integer;
```

The written and predicted columns are **nullable, not zero**. A run committed
before this migration knows only that created plus updated equals its
`rows_valid`; a default of zero would render three false figures for every
such run, and null renders the sentence the page draws today.

**Declarations.** Every new field on `FieldSpec` and `ImportTarget` has a
default, so every target declared today constructs unchanged. `Format` and
the check constraints do not change: `xlsx` and `json` were already in both.

**API views.** Every added field is additive; the TypeScript interfaces in
`packages/api-client` gain optional members and the page tolerates their
absence, so a page one deploy ahead of its API renders.

**Dependencies.** `openpyxl` moves from "declared by the API" to "declared by
`koras-import`", which the package's own project file anticipated for this
phase. The worker installs `koras-import` under the capability already and so
receives it; the worker image copies nothing more, because the renderer and
the readers live in the package rather than in the API.

**The estate**, checked on 2026-09-22 and not since: `docoris` stops at
migration `00028` and has no import feature to be compatible with;
`lexveria` is one migration behind the template and would take `00036`,
`00037` and `00038` together; `koras-e2e-shop` is being torn down. A product that declared
targets against the field set as it stands keeps working with no edit and
gains a template with synthesised examples and empty help.

**Nothing is removed or renamed.** The three existing audit actions, the ten
routes, the run view's existing fields and the page's existing controls stay.

## 16. Documentation changes

| Document | Change |
|---|---|
| `docs/features/data-import/architecture.md` | A section on templates, formats and counts as built, and the three carried findings that closed with it |
| `docs/features/data-import/README.md` | The one-paragraph summary gains the template and the formats; "XLSX and JSON" leaves the *deliberately not here* list |
| `docs/features/data-import/manual-test-plan.md` | Cases 41 onward |
| `docs/platform/execution/CAT-02-data-import.md` | The status line only. The plan is left as written; Phase 3's format bullet is what this is |
| `docs/features/STATUS.md` | Rows for IMPORT-US-019 to 028 |
| `docs/platform/gap-defect-register.md` | IMPORT-GAP-003 closed; new rows for the version fingerprint and the matcher seam |
| `docs/FOLLOW_UPS.md` | F28's list gains the manual cases and loses the audit bullet, which is stale twice over |
| `docs/adr/` | ADR 0012, template versioning: header-judged CSV, property-carried XLSX, product-owned version plus engine fingerprint |
| `docs/AUDIT_ARCHITECTURE.md` | The four actions, and the worker writing two of them |
| `CLAUDE.md` | One dated paragraph in the data import section |
| The product's `CLAUDE.md.hbs` and `koras-profile-product` skill | How to declare examples, help, a version and a matcher |

## 17. Affected packages and files

Existing files that change:

```
profiles/product/manifest.yaml                                    template map, four paths
profiles/product/template/python-packages/koras-import/pyproject.toml   openpyxl
profiles/product/template/python-packages/koras-import/src/koras_import/__init__.py
profiles/product/template/python-packages/koras-import/src/koras_import/targets.py
profiles/product/template/python-packages/koras-import/src/koras_import/reading.py
profiles/product/template/python-packages/koras-import/src/koras_import/mapping.py
profiles/product/template/python-packages/koras-import/tests/test_import.py
profiles/product/template/services/api/koras_api/core/imports.py
profiles/product/template/services/api/koras_api/routers/imports.py
profiles/product/template/services/api/koras_api/imports/targets.py    docstring example
profiles/product/template/services/worker/koras_worker/tasks/imports.py
profiles/product/template/packages/api-client/src/index.ts
profiles/product/template/packages/ui/src/index.ts
profiles/product/template/packages/i18n/src/messages/en.ts             and de.ts, es.ts
profiles/product/template/apps/web/src/app/dashboard/imports/ImportPanel.tsx.hbs
profiles/product/template/apps/web/src/app/dashboard/imports/actions.ts.hbs
profiles/product/template/apps/web/src/app/dashboard/imports/labels.ts.hbs
profiles/product/template/e2e/imports.spec.ts.hbs
profiles/product/template/e2e/roundtrip/imports.spec.ts
profiles/product/template/tests/unit/test_imports.py
profiles/product/template/supabase/tests/320_imports_isolation.sql      the new columns under the update check
generators/create-koras-app/tests/product-import.test.ts
.github/fixtures/import-target.py                                  examples, help, xlsx, a version
```

New files:

```
profiles/product/template/python-packages/koras-import/src/koras_import/templates.py
profiles/product/template/python-packages/koras-import/src/koras_import/reading_xlsx.py
profiles/product/template/python-packages/koras-import/src/koras_import/compatibility.py
profiles/product/template/python-packages/koras-import/src/koras_import/reading_json.py   if approved
profiles/product/template/supabase/migrations/00038_import_counts.sql
profiles/product/template/apps/web/src/app/api/imports/[key]/template/route.ts.hbs
profiles/product/template/packages/ui/src/primitives/download-menu.tsx
docs/adr/0012-import-template-versioning.md
```

Untouched, and stated so: the two export tables, `koras-reporting`,
`koras-storage`, the files router, the notification dispatch point, the
Control Plane, and every product's own targets.

## 18. Decisions that need approval before implementation

Each of these is either uncovered by an accepted decision or reverses one.
The recommendation is stated; the choice is the owner's.

| # | Decision | Recommendation | Why it needs a decision |
|---|---|---|---|
| D1 | **A commit that completes with errors.** The brief lists it as a state; Phase 2's accepted criterion is all-or-nothing, and a partial commit is the defect CAT-02 forbids outright | Keep atomic. "Completed with errors" is the dry run's `validation_failed`; a commit never has it | A reversal of an accepted acceptance criterion |
| D2 | **Progress counts during a commit.** The brief asks for them "where available" | Not built, as Phase 2 decided. Counts before and after only | A counter written outside the one transaction is partial-import evidence |
| D3 | **A manual-review duplicate strategy.** The brief lists it | Defer. Reject, skip and update are covered by `create`, `skip_duplicate` and `update` or `upsert` with a matcher; review needs new states and a review surface | New states in a machine whose edges are the feature |
| D4 | **JSON as a template and source format.** The brief includes it only if supported | Defer. `files.allowedExtensions` defaults to a list without `json`; ADR 0007 copies the platform default into an organisation at creation, so adding it reaches no existing organisation, and JSON imports would be refused at the ticket for every one of them until an administrator edits a list | A settings default change with a consequence ADR 0007 makes permanent |
| D5 | **Worker-written audit rows** for validation and commit outcomes | Write them, by the same importlib path the completion notice already uses | A reversal of the Phase 2 position that the run row is the outcome |
| D6 | **Template versioning mechanism.** A product-owned integer plus an engine fingerprint; CSV judged by header alone; XLSX carrying a document property | As stated, recorded as ADR 0012 | No decision record covers it |
| D7 | **A download-menu primitive** in the design system, versus the export menu's row of anchors | The primitive, as section 7 describes | A design-system addition |
| D8 | **Help and example as plain text in one language** on the declaration | Accept, with the trigger recorded | The one place a product's words reach a customer untranslated |
| D9 | **The matcher seam** on the target: a second product callable in the dry run | Add it, optional, savepoint-wrapped | The dry run has called nothing of the product's since Phase 1; this ends that property, read-only |
| D10 | **The error report as an annotated source file** for re-import, written by the worker to the exports category and expired by a sweep | Defer; keep the browser-built problems file with the added column | Phase 2 replaced this shape deliberately and said why |
| D11 | **Per-row outcomes from the writer** so a completed import's report can list rows | Defer; counts only | A change to the writer contract every product's writer would follow |
| D12 | **The decompressed-size ceiling** for a workbook | 256 MiB from the zip directory, above the 64 MiB compressed ceiling | A new bound with no prior number |

**Resolved 2026-09-29.** The owner answered all twelve the same day the
analysis was accepted; `docs/adr/0012-import-template-versioning.md` is the
record of D6 and carries the resolution of the other eleven in one table.
In short: D1, D2, D3, D4, D10 and D11 are refused or deferred as recommended;
D5, D7, D8, D9 and D12 are accepted as recommended, D5 with the boundary that
the run row stays the authoritative execution state and D9 with the condition
that the matcher is one call per run and the commit stays authoritative.
Implementation follows this document as amended by that record.
