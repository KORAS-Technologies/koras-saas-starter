# CAT-02 — Data import and migration framework

| | |
|---|---|
| **Category ID** | CAT-02 |
| **Feature name** | Data import and migration framework |
| **Owner** | CAT-02 lead |
| **Written** | 2026-09-19 |
| **Status** | **Phase 1 built 2026-09-19.** PLAT-F1 shipped the same day and this is its first caller. Phases 2-4 not started. Three Phase 1 items deliberately unbuilt — see `docs/features/data-import/architecture.md`. **Phase 2 built 2026-09-20; Phase 3's format bullet built 2026-09-29** with downloadable templates, XLSX and the preview counts, from `docs/features/data-import/templates-and-formats-analysis.md` and ADR 0012 rather than from this plan's wording |
| **Read first** | `docs/platform/master-platform-plan.md` §7, §9; `docs/platform/feature-dependency-map.md`; `docs/platform/gap-defect-register.md` IMPORT rows; and `docoris/docs/architecture/IMPORT.md`, which is a requirements source written by the product that needs this |

## Objective

Let a customer load their existing records into a KORAS product without a
developer: upload a file, map its columns, see what would happen, fix what is
wrong, and commit — with every created row attributable to the run that created
it. The engine must never know a product's table names; a product declares what
may be imported, the way it already declares reports, settings and cron jobs.

## Repository scope

| Repository | Allowed | What |
|---|---|---|
| `koras-saas-starter` | **Yes — owner** | The engine, the registry, the tables, the routes, the UI |
| `output/koras-e2e-shop` | Yes, after the integration gate | Validation. It has a real shop domain to import into, which the generated product does not |
| `koras-control-plane` | **No** | No import surface belongs there |
| `docoris` | **No** | Read for requirements; never written to |

**A rule this category can break easily and must not.** No product table name,
no Docoris concept and no shop concept reaches the engine. If the engine needs
to know something about a target, the target declares it.

## Dependencies

| Dependency | Class | State |
|---|---|---|
| **PLAT-F1 job contract** | **HARD, from Phase 1** | **Satisfied 2026-09-19.** `koras-queue` ships, and the dry run is its first caller |
| Auth, tenant context, forced RLS | HARD | Satisfied |
| Storage upload ticket and quota | HARD | Satisfied |
| Storage governance: retention, hold, reconciliation | HARD | Satisfied, and inherited free by using the existing imports category |
| Audit action registry | HARD | Satisfied |
| Permissions catalogue | HARD | Satisfied; one new string needed |
| Settings framework | HARD | Satisfied; three file settings exist and are enforced by nothing |
| Malware scan seam | HARD | Satisfied as a seam; no scanner exists |
| The run-table decision (**PLAT-GAP-006**) | HARD for the data model | Open. Due at Phase 0 |
| Export engine, as the shape to copy | SOFT | Satisfied |
| **CAT-01 notification contract** | **SOFT** | A no-op emitter satisfies it |
| Shared data table | SOFT | Client-paginated. Phase 1 works within it |
| Upload primitive | SOFT | Extracted in Phase 1 from the existing Files page |
| Validation package | OPTIONAL | A stub. Phase 1 shares the row schema with the single-record route instead |
| AI-assisted mapping, connectors | FUTURE | Named so they are not rediscovered |

**Hard blockers.** PLAT-F1, and one decision this category owes itself before
writing a migration.

## Shared contracts

**Produced — `ImportTarget`.** A product declares, at import time, in an empty
product-owned file beside the product reports list and the product settings
list:

- the target and its human name;
- the operations permitted — create, update, upsert, and skip-duplicate;
- the match keys that decide what a duplicate is;
- the allowed fields, the required fields, and any field the import may never
  write;
- the permission an execute needs;
- a row validator, shared with the single-record route so that one schema
  serves both.

**Delete, merge and replace are absent from the operation set on purpose.**
Delete is not enabled by default and is not in this plan at all.

**Consumed — the PLAT-F1 job contract**, and the CAT-01 emitter for five events:
started, completed, completed with errors, failed, cancelled.

## Required documents

| Document | When |
|---|---|
| A feature directory under `docs/features/` with a README, the feature, user stories, acceptance criteria, architecture, a data model, security, testing and a manual test plan | Phase 0, before Phase 1 code |
| An ADR for the run-table decision — a third instance of the pattern, or the extraction of it | Phase 0 |
| A top-level import architecture document describing what was built | After Phase 3 |
| Rows in `docs/platform/gap-defect-register.md` | Continuously |

## Phases

### Phase 0 — Registry, contract, and one decision

- The target registry and the declaration shape, following the conventions every
  other registry in the repository uses.
- The import permission added in both languages, plus a route that checks it
  (**IMPORT-GAP-008**). A permission nothing enforces is worse than an absent
  one, which the permissions package says in its own comment.
- **The decision:** the run-and-record pattern exists twice already, with its own
  table, status vocabulary, expiry sweep and download route each time. Import
  needs a third. Extract it, or choose the duplication and write down why.
  Recorded as an ADR either way, because a third unexamined copy is how a
  pattern becomes four.
- The state machine named and written down: created, mapped, validating,
  validated, validation failed, commit requested, committing, committed, failed,
  and cancelled from any non-terminal state.

### Phase 1 — Upload, map, dry run, preview (CSV)

- The source file is an ordinary upload with the existing imports category
  (**IMPORT-GAP-002**), so retention, legal hold and reconciliation apply to it
  without being asked for.
- **The three file settings are enforced at the presign route** — maximum size,
  allowed extensions, files per upload (**IMPORT-DEF-001**). The hardcoded 5 GiB
  ceiling stays as the outer bound; the settings narrow it.
- **A file whose scan status is pending or skipped is not parsed**
  (**IMPORT-GAP-011**). This is narrower than the platform default, which
  deliberately withholds only infected files, and it needs no scanner to exist.
- Analyze: detect the delimiter and encoding, read the header, and read a bounded
  head of the file. Never the whole file into memory.
- Map: source column to target field, with required columns named at mapping time
  and a missing one refused there rather than at validation.
- Validate as a dry run: every row, one pass, writing nothing.
- Preview: the first bounded set of mapped rows, drawn through the shared data
  table, which paginates on the client — so the preview is a head of the file and
  not the file (**IMPORT-GAP-006**).
- An upload primitive extracted into `packages/ui` from the existing Files page
  flow rather than written a second time (**IMPORT-GAP-007**).

**Exit:** a customer uploads a CSV, maps it, runs a dry run, and sees what would
happen. Nothing is written.

**Met 2026-09-19, with three exceptions recorded rather than quietly dropped.**
`files.maxFilesPerUpload` is unsurfaced rather than enforced, the upload flow was
not extracted into a shared primitive, and the preview is a plain table rather than
the shared one. Each is a row in `docs/platform/gap-defect-register.md` and each is
explained in `docs/features/data-import/architecture.md`. None affects the
exit criterion itself: nothing is written.

### Phase 2 — Commit, row errors, error file

- Commit: create, update, upsert, skip-duplicate, per run, **atomic within the
  run**. A partial commit is the defect the requirements forbid outright.
- Every created row carries its run reference, so per-row attribution is the run
  rather than one audit event per row.
- Row-level errors stored per row with a column, a code and a message, read as a
  page, localised through the existing error-code path (**IMPORT-GAP-005**).
- A downloadable error file: the source with an errors column appended, written
  by the worker to the exports category, fetched through a signed URL, expiring
  on a sweep — the shape audit exports already use.
- Idempotency: a client key on create and on commit, plus a natural key per
  target, so a re-run reports duplicates rather than creating them.
- Progress as counts on the run row.

**Exit:** a commit that fails leaves nothing behind, and the customer can
download a file naming every bad row.

**Met 2026-09-20, with two items answered differently from the plan and one
not built.**

The commit writes through a `Writer` the product declares on its target, in one
transaction that also carries the run's own `committed` row — so the two cannot
disagree — and records a failure in a second transaction opened after the first
has rolled back, which is the only arrangement where a failure is both recorded
and leaves nothing behind. The job declares `attempts=1`: a retry after a write
that committed and then failed later would write a customer's records twice,
and nothing outside the transaction can tell that case from a clean failure.

**The error file is a CSV built in the browser, not the source with a column
appended.** The plan's shape — the worker writes it to the exports category and
a signed URL fetches it — is the audit-export shape, and it buys durability for
a file whose whole life is one download by the person looking at the report. The
rows are already stored, paged and localised; what was missing was a way to take
them away. `allErrors` pages the report to exhaustion and the panel writes the
file. If somebody later needs the source *annotated* rather than the problems
listed, that is a different artefact and the plan's shape is right for it.

**Idempotency is two locks, not a client key.** The state machine refuses a
second `commit_requested` and the enqueue carries `commit:{run_id}`. A client
key would be a third, and its failure mode — a client that generates a new key
per retry — is the one the other two already cover.

**Progress as counts on the run row is not built.** A row counter would need the
worker to write outside its one transaction, which is the property this phase
exists to protect. A run in `committing` says so and nothing more.

IMPORT-US-016 is met by halves, and the halves are named in
`docs/features/data-import/architecture.md`: the request is audited
(`import.run.started`, `import.run.committed`, `import.run.refused`) and the
outcome is the run row rather than a fourth action, because auditing from the
worker would mean the worker satisfying the API's whole configuration surface
to write one row.

### Phase 3 — Formats, mapping profiles, retry, cancellation

- XLSX, reusing the spreadsheet dependency already declared, first sheet or a
  named one; JSON as an array of objects.
- Saved mapping profiles per tenant per target, so the second import of the same
  export is one click.
- Retry: a failed run re-validates or re-commits as a **new** run linked to the
  old one, so history is never rewritten.
- Cancellation by state, not by killing a job (**IMPORT-GAP-010**): a cancelled
  run is not picked up, and a running one finishes its batch and stops.
- Relationship resolution: a row referring to another record by a natural key.

### Phase 4 — Large files

- Chunked validation with a per-run cursor, and a commit that batches with a
  skip-locked cursor (**IMPORT-GAP-009**). Until this lands, Phases 1 to 3 bound
  the row count and **refuse rather than truncate** — the rule audit exports
  already follow with an explicit ceiling.
- Streaming parse throughout. The whole file never enters memory, at any phase.

**Future, and not in this plan:** connectors to other systems, AI-assisted
mapping suggestions, and migration from a named competitor.

## User stories

| ID | As a | I want | So that | Phase |
|---|---|---|---|---|
| IMPORT-US-001 | organisation admin | to upload a spreadsheet of my existing records | I do not retype them | 1 |
| IMPORT-US-002 | organisation admin | to map my columns to the product's fields | my export does not have to match a template | 1 |
| IMPORT-US-003 | organisation admin | to be told at mapping time that a required column is missing, by name | I fix it before waiting for a validation run | 1 |
| IMPORT-US-004 | organisation admin | a dry run that writes nothing | I can be wrong safely | 1 |
| IMPORT-US-005 | organisation admin | to see what the first rows will look like | I catch a mis-mapped column before committing | 1 |
| IMPORT-US-006 | organisation admin | every problem reported in one pass | I do not fix one error per attempt | 2 |
| IMPORT-US-007 | organisation admin | to download a file naming every bad row | I can fix them in the tool I exported from | 2 |
| IMPORT-US-008 | organisation admin | to choose whether a duplicate is skipped or updated | a re-import is safe | 2 |
| IMPORT-US-009 | organisation admin | a commit that either fully happens or does not | I am never left half-imported | 2 |
| IMPORT-US-010 | organisation admin | to see my past imports and what each did | I can answer where a record came from | 2 |
| IMPORT-US-011 | organisation admin | to save a mapping and reuse it | the monthly import is one click | 3 |
| IMPORT-US-012 | organisation admin | to cancel a running import | a mistake is not a twenty-minute wait | 3 |
| IMPORT-US-013 | organisation admin | to retry a failed import without losing its history | I can see what happened both times | 3 |
| IMPORT-US-014 | organisation admin | a large file to work | my real data is not a demo size | 4 |
| IMPORT-US-015 | member without the permission | to be refused | importing is not something everyone does | 1 |
| IMPORT-US-016 | security admin | every import attributable and audited | I can answer who loaded this | 2 |
| IMPORT-US-017 | developer | to declare what may be imported without touching the engine | a new target is a declaration, not a fork | 0 |
| IMPORT-US-018 | organisation admin | to be told when a long import finishes | I do not watch a progress bar | 2 |

## Acceptance criteria — the ones that decide the phase

- **P1.** A dry run writes nothing, asserted by a test that counts rows before
  and after. A file uploaded by tenant A is not readable by tenant B. A file
  larger than the setting is refused at presign, not after upload. A file whose
  scan is pending is refused parsing, with a distinguishable reason.
- **P2.** A commit that raises on row 900 of 1000 leaves zero rows. Two commits
  of the same run with the same idempotency key create one set of records. Every
  created row names its run. The error file's row numbers match the source file's.
- **P3.** A retry creates a new run linked to the old; neither run's history is
  rewritten. A cancelled run writes nothing more after cancellation.
- **P4.** A file larger than one job's timeout completes. Memory does not scale
  with file size, asserted rather than assumed.

## Security requirements

**Server-side, independently of the browser, every request validates:** the
tenant; the target, against the registry; the operation, against what the target
permits; each field, against the allowed list; the permission; the row count;
and the file size. A mapping arrives from a browser and is data, never
authorisation.

- **Target and field allowlists are the core control.** A mapping naming a field
  the target did not declare is refused, not ignored. Ignoring it is how an
  import writes a column it was never meant to reach.
- A field the target marks as never-writable — an identifier, a tenant
  reference, a role — cannot be mapped at all.
- The source file inherits the tenant's storage policy, quota, retention and
  legal hold, because it is an ordinary file.
- **A file is not parsed until its scan says clean or the target opts out
  explicitly.** The platform default withholds only infected files, by a
  deliberate decision; parsing is stricter than downloading, and the difference
  is written down.
- Spreadsheet writing already defends against formula injection on every cell;
  **reading needs the mirror**: a cell beginning with a formula character is data
  and is never evaluated.
- A row count ceiling and a per-tenant rate limit, refused loudly.
- Every run state change is audited. Per-row audit is the run, not one event per
  row — the distinction the brief draws between an audit record and a worker log.
- The error file may contain customer data and therefore expires like an audit
  export rather than living forever.

## Database impact

Reserved migration range **`00036`–`00039`**, RLS test range **`320`–`340`**.
Every table tenant-owned, `enable` and `force`, four policies, one numbered
isolation test, a retention class at creation. The exact shape waits on the
Phase 0 decision about the run-and-record pattern.

| Phase | Tables |
|---|---|
| 1 | The run, and its mapping |
| 2 | The row-level errors |
| 3 | Saved mapping profiles |
| 4 | None — a cursor is a column |

Worker rows are written on the tenant session, as reporting exports are, and not
on the provisioning context.

## APIs

Create a run against a completed upload; set a mapping; validate; read the
report; commit; list history; download the error file. A tenant id never appears
in a path — the product profile's first rule.

## UI impact

One dashboard module registered in the navigation registry, with the steps as
steps: upload, map, validate, preview, confirm, results. Every async surface
handles loading, empty, error, unauthorised, forbidden and validation states.
Keyboard operation and visible focus throughout; the mapping step is a form and
follows the repository's form rules.

## Background jobs

**This is the category that makes PLAT-F1 necessary.** Validation and commit are
both enqueued. Neither is a cron job, and neither is a request.

## Observability

Structured logs per run with the tenant and the run, trace context across the
queue, counts on the run row. Rows processed per second and queue depth belong
on a metrics endpoint the repository does not have (**PLAT-GAP-007**).

## Testing

| Kind | What |
|---|---|
| Python unit | The parser against malformed CSV, a byte-order mark, mixed line endings, quoted delimiters and a ragged row; mapping resolution; validation; duplicate matching; idempotency |
| Database | Commit atomicity — the failure at row 900 |
| RLS | One numbered isolation test per table; a cross-tenant file-read case |
| Generator | A `product-import.test.ts`: the capability gates exactly the declared paths; the module resolves; the permission exists in both languages; every message key in all three catalogues |
| Worker | Retry, cancellation, and a chunked run resuming |
| Security | A mapping naming an undeclared field; an unscanned file; a formula-shaped cell; a row count over the ceiling; a member without the permission |
| Browser | The whole path at 375 and 1440, including a deliberately broken file |
| Failure paths | Worker dies mid-commit; storage unavailable at parse time; the plan lapses mid-run |

## Manual QA

A manual test plan in the feature directory. The case that matters most is the
one no automated test reaches: a real customer export, from a real tool, with
the encoding and the stray columns that real exports have.

## Migration, rollout, rollback

- **Migration.** Additive.
- **Rollout.** The capability is **off by default**. A product with nothing to
  import should not carry the surface, and unlike notifications there is no
  general case where every product wants it on day one.
- **Rollback.** Disabling the capability removes the surface; runs and their rows
  remain and are read by nothing. **Rows a commit created are not rolled back by
  disabling the capability** — they are the customer's records, and the run
  reference on each is how they are found.

## Cross-repository sync

`output/koras-e2e-shop` after the integration gate, by hand-carried commit. That
repository is where a real import target can be declared, because the generated
product has no domain of its own — the same reason the page that makes the grid
page size observable lives there.

## Definition of done

As CAT-01, plus: the target registry proven by a second target declared outside
the engine; the atomicity test; and a real customer-shaped file imported by a
person, recorded with a verdict.

## Known gaps, defects and debt

IMPORT-GAP-001 to 011, IMPORT-DEF-001, and PLAT-GAP-001, 003 and 006, in
`docs/platform/gap-defect-register.md`.

## Next three features, after this category

1. Server-side pagination for the shared data table, which import is the first
   feature to genuinely need.
2. A malware scanner registered as a file hook, which the seam has awaited since
   storage shipped.
3. Export as the mirror of import — the engine exists; what is absent is a
   customer-facing "export my records" surface over it.
