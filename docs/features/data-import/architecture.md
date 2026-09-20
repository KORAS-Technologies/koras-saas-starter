# Data import, as built

Phase 1, 2026-09-19, **as amended by the review the same day** — `review.md`
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

## What has not been done

- **No manual pass.** `manual-test-plan.md` here has the cases; every verdict
  is blank.
- **No live run.** Nothing has imported a file through a deployed product. The
  dry run has never executed against a real Redis, a real bucket and a real
  scanner.
- **`koras-e2e-shop` is not level with this.** It has a shop domain that could
  declare real targets; nothing has been synced to it.
