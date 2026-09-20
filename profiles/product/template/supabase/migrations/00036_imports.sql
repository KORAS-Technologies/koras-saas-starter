-- Migration: 00036_imports
-- A run, and what was wrong with it.
--
-- `docs/adr/0009-import-runs-are-not-a-third-export.md` is why this is its own
-- table rather than a third instance of the export shape: an export means "ask
-- for a file, wait, fetch it", and every column of `report_exports` and
-- `audit_exports` follows from that. A run means something else — ten states
-- against three, two actors, and an artefact that is an output of failure
-- rather than the point.
--
-- What it borrows without inheriting: the row is committed before any work
-- starts, so a process that dies half way leaves something a person can find;
-- the error is a safe sentence and never a stack; and a storage key is an
-- object key, never a URL.
--
-- ── The source file is an ordinary file ──────────────────────────────────────
--
-- `source_file_id` points at `public.files`, uploaded through the same
-- three-step ticket as anything else and shelved under the `imports` category
-- that `koras_storage` has declared and nothing has used since it was written.
-- So the source of an import inherits retention, legal hold, reconciliation and
-- the quota without any of that being restated here — which is the whole
-- argument for not giving imports their own bucket.
--
-- `on delete restrict` rather than cascade: a file under an import run is
-- evidence of where rows came from, and deleting it should be refused while a
-- run still points at it rather than silently removing the run's own history.
--
-- ── Row errors are a table, not a column ─────────────────────────────────────
--
-- A thousand errors in a `jsonb` column is a thousand errors that must be read
-- whole to show ten of them. The report is paged, so the rows are rows.
--
-- The number in `row_number` is **1-based and includes the header**, which is
-- what a spreadsheet's left margin says. An error report whose numbers
-- disagree with the file is one nobody can use.

create table public.import_runs (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references public.tenants(id) on delete cascade,

  -- The target key, dotted, as the product declared it. Not a foreign key: the
  -- catalogue is code, the same way reports and audit actions are.
  target         text not null,
  format         text not null default 'csv',

  source_file_id uuid not null references public.files(id) on delete restrict,

  -- What the reader worked out about the file, kept so a second look at the run
  -- does not have to read the file again to explain itself.
  delimiter      text not null default ',',
  encoding       text not null default 'utf-8-sig',
  columns        text[] not null default '{}',

  -- Source column name -> target field name, as a person confirmed it.
  mapping        jsonb not null default '{}',
  operation      text not null default 'skip_duplicate',

  status         text not null default 'created',

  rows_total     integer not null default 0 check (rows_total >= 0),
  rows_valid     integer not null default 0 check (rows_valid >= 0),
  errors_total   integer not null default 0 check (errors_total >= 0),
  -- True when more errors existed than the report carries.
  errors_cut     boolean not null default false,

  -- A safe sentence for a person. Never a stack and never a provider body.
  error          text,

  requested_by   text not null,
  -- Null until somebody confirms. The second actor, and the reason this is not
  -- an export: an export has one.
  committed_by   text,

  created_at     timestamptz not null default now(),
  started_at     timestamptz,
  finished_at    timestamptz,

  constraint import_runs_target_is_dotted
    check (target ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'),
  constraint import_runs_status_known
    check (status in ('created', 'mapped', 'validating', 'validated',
                      'validation_failed', 'commit_requested', 'committing',
                      'committed', 'failed', 'cancelled')),
  constraint import_runs_operation_known
    check (operation in ('create', 'update', 'upsert', 'skip_duplicate')),
  constraint import_runs_format_known
    check (format in ('csv', 'xlsx', 'json')),
  -- A committed run names who confirmed it. The database says so because the
  -- two-actor rule is the point of the table, and a route is a worse place to
  -- keep a rule than a constraint.
  constraint import_runs_committed_has_an_actor
    check (status <> 'committed' or committed_by is not null)
);

create index import_runs_tenant_created_idx
  on public.import_runs (tenant_id, created_at desc);

-- The worker's query: runs waiting for it, oldest first.
create index import_runs_queued_idx
  on public.import_runs (status, created_at)
  where status in ('validating', 'committing');

create table public.import_row_errors (
  id          bigint generated always as identity primary key,
  run_id      uuid not null references public.import_runs(id) on delete cascade,
  -- Carried rather than joined. Row-level security needs a predicate on this
  -- table, and a policy that reached through to the run would be a policy with
  -- a subquery in it -- which is where cross-tenant reads come from.
  tenant_id   uuid not null references public.tenants(id) on delete cascade,
  row_number  integer not null check (row_number > 0),
  column_name text not null default '',
  field       text not null default '',
  -- An i18n code, resolved by the browser. Never a sentence.
  code        text not null,
  value       text not null default '',

  constraint import_row_errors_code_is_dotted
    check (code ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$')
);

create index import_row_errors_run_idx
  on public.import_row_errors (run_id, row_number, id);

alter table public.import_runs enable row level security;
alter table public.import_runs force row level security;
alter table public.import_row_errors enable row level security;
alter table public.import_row_errors force row level security;

-- ── The tenant's own, and nobody's else ──────────────────────────────────────
--
-- Scoped to the tenant and not to the person: an import is an organisation's
-- act, and the colleague who confirms is deliberately not the one who uploaded.
-- **The permission is checked by the route, not here.** A policy cannot see a
-- permission, and a second, weaker rule in the database that looked like an
-- authorization check would be worse than none.

drop policy if exists "import_runs_select_own_tenant" on public.import_runs;
create policy "import_runs_select_own_tenant"
  on public.import_runs for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "import_runs_insert_own_tenant" on public.import_runs;
create policy "import_runs_insert_own_tenant"
  on public.import_runs for insert
  with check (tenant_id = public.current_tenant_id());

-- The `with check` repeats the predicate, so one statement cannot both advance
-- a run and move it into another tenant. An update policy without one admits
-- exactly that, and no suite in this repository exercised such a clause until
-- 2026-09-19 -- which the settings review found and which is why this one has
-- a case of its own in `320`.
drop policy if exists "import_runs_update_own_tenant" on public.import_runs;
create policy "import_runs_update_own_tenant"
  on public.import_runs for update
  using (tenant_id = public.current_tenant_id())
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "import_row_errors_select_own_tenant" on public.import_row_errors;
create policy "import_row_errors_select_own_tenant"
  on public.import_row_errors for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "import_row_errors_insert_own_tenant" on public.import_row_errors;
create policy "import_row_errors_insert_own_tenant"
  on public.import_row_errors for insert
  with check (tenant_id = public.current_tenant_id());

-- Cleared and rewritten when a run is validated again, which is the only way a
-- row error legitimately disappears.
drop policy if exists "import_row_errors_delete_own_tenant" on public.import_row_errors;
create policy "import_row_errors_delete_own_tenant"
  on public.import_row_errors for delete
  using (tenant_id = public.current_tenant_id());

-- ── There is no delete policy for a run, and that is the decision ────────────
--
-- A run is the provenance of every row it wrote: `import_run_id` on an imported
-- record points here, and "where did this come from" has to keep having an
-- answer. A cancelled or failed run is history too -- the second most useful
-- thing to know about an import is that somebody tried and stopped.
--
-- Retention arrives with the error file in Phase 2, on the provisioning context
-- and with a sweep, the way every other retention in this product works. Until
-- then a run is kept, and this comment is the record that it was a choice.
