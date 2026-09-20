# Data import, as built

Phase 1, 2026-09-19. Read `README.md` here first for what is and is not in it,
and `docs/platform/execution/CAT-02-data-import.md` for the plan this was built
against.

## The shape

```
python-packages/koras-import/          the engine. No database, no bucket, no product
  targets.py     Operation, Format, FieldKind, FieldSpec, ImportTarget, TargetRegistry
  reading.py     encodings, delimiter sniffing, the header, bounded row reads
  mapping.py     resolve (the allowlist), suggest, validate (every problem, one pass)
  states.py      RunState and the only edges that exist
  jobs.py        VALIDATE_RUN and COMMIT_RUN, declared where the API can enqueue them

services/api/koras_api/
  imports/targets.py     the product's own list. Empty in a generated product
  imports/__init__.py    the registry, built at import
  core/imports.py        the run store: two tables, every move through the machine
  routers/imports.py     eight routes, all behind imports.manage

services/worker/koras_worker/tasks/imports.py   validate_run, the first enqueued job

supabase/migrations/00036_imports.sql       import_runs, import_row_errors
supabase/tests/320_imports_isolation.sql    the isolation suite

apps/web/src/app/dashboard/imports/         the page, its actions and its labels
e2e/imports.spec.ts                          four browser checks
```

## The four properties worth keeping

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

## The permission

`imports.manage`, on **every** route including the reads. A run names a
customer's own records and its mapping shows their column headings, so the
history is not less sensitive than the act. The permission is administrative,
held by owners and administrators alone, so an ordinary member does not see the
module at all — hidden rather than locked, since there is nothing to upsell.

A target may also declare its own `permission`, and `_require_target` enforces
it on top. Both are required: a target cannot widen access by declaring a
permission everybody holds. That check was added when writing this document
found the field declared and enforced nowhere, which is precisely the state its
own comment says is worse than having no field.

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
| The preview drawn through the shared data table (IMPORT-GAP-006) | **Not used.** A plain table in the panel | The shared table reads `grid.*` from the effective settings and paginates on the client; the preview is a bounded head of the file with columns that vary per file. Using it would have meant a column set built at runtime, which the table does not take |

None of the three affects the safety properties above. All three are Phase 2
candidates.

## What has not been done

- **No manual pass.** `manual-test-plan.md` here has the cases; every verdict
  is blank.
- **No live run.** Nothing has imported a file through a deployed product. The
  dry run has never executed against a real Redis, a real bucket and a real
  scanner.
- **`koras-e2e-shop` is not level with this.** It has a shop domain that could
  declare real targets; nothing has been synced to it.
