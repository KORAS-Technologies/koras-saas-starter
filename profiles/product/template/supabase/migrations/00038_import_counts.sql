-- Migration: 00038_import_counts
-- What a run knows about its template, its job and its figures.
--
-- Nine columns on `import_runs`, arriving with the downloadable template and
-- the XLSX reader on 2026-09-29. `docs/adr/0012-import-template-versioning.md`
-- is the decision; `docs/features/data-import/templates-and-formats-analysis.md`
-- §15 is why every one of them is the shape it is.
--
-- ── Nullable, not zero ───────────────────────────────────────────────────────
--
-- A run committed before this migration knows one thing about what it wrote:
-- that created plus updated equals its `rows_valid`. A default of zero on the
-- three written columns would render "created 0, updated 0, skipped 0" for
-- every such run -- three false figures under a run that imported a thousand
-- records -- and null renders the sentence the page drew before. The same for
-- the three predicted columns: null means "the target could not say", which
-- is a different claim from "nothing would happen", and the page says so.
--
-- `rows_duplicate` is the one exception: the in-file duplicate check has run
-- on every validated run since Phase 1, and its problems are in
-- `import_row_errors` under `import.error.duplicate_in_file`. Zero for an old
-- run is a floor, not a lie.
--
-- ── No policy change ────────────────────────────────────────────────────────
--
-- Every policy on this table is a predicate on `tenant_id`, and the update
-- policy's `with check` repeats it. Nine more columns change nothing about
-- which rows a tenant may reach, and `320_imports_isolation.sql` exercises the
-- new columns under the same clause rather than assuming it.

alter table public.import_runs
  -- The product's import-definition version the file's template identity
  -- named. Null for a CSV, and for any file not made from a template.
  add column template_version integer
    check (template_version is null or template_version >= 1),
  -- The queue's id for the last job this run was handed to. Written after
  -- the enqueue answers, so a run in `validating` with no job id is one whose
  -- enqueue was refused before it could be recorded.
  add column job_id           text,
  add column rows_duplicate   integer not null default 0 check (rows_duplicate >= 0),
  add column predicted_create integer check (predicted_create is null or predicted_create >= 0),
  add column predicted_update integer check (predicted_update is null or predicted_update >= 0),
  add column predicted_skip   integer check (predicted_skip is null or predicted_skip >= 0),
  add column rows_created     integer check (rows_created is null or rows_created >= 0),
  add column rows_updated     integer check (rows_updated is null or rows_updated >= 0),
  add column rows_skipped     integer check (rows_skipped is null or rows_skipped >= 0);

-- A committed run that recorded its figures recorded all three. Half a
-- record is worse than none: a page drawing created and updated from a row
-- that never stored skipped would draw a table that does not add up.
alter table public.import_runs
  add constraint import_runs_written_counts_together
    check (
      (rows_created is null and rows_updated is null and rows_skipped is null)
      or (rows_created is not null and rows_updated is not null and rows_skipped is not null)
    ),
  add constraint import_runs_predicted_counts_together
    check (
      (predicted_create is null and predicted_update is null and predicted_skip is null)
      or (predicted_create is not null and predicted_update is not null
          and predicted_skip is not null)
    );
