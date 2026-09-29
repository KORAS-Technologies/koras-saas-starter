-- An import run belongs to the organisation that started it.
--
-- Three properties, and the third is one no suite in this repository asserted
-- until 2026-09-19.
--
-- **Scoped to the tenant, not to the person.** An import is an organisation's
-- act and the colleague who confirms is deliberately not the one who uploaded,
-- so a run must be visible to everybody in the tenant — unlike a notification
-- feed, which is the opposite decision two migrations earlier. The permission
-- that decides who may *start* one is checked by the route; a policy cannot
-- see a permission, and a weaker second rule here that looked like an
-- authorization check would be worse than none.
--
-- **Row errors carry their own tenant.** They could have been reached through
-- their run, and a policy with a subquery in it is where cross-tenant reads
-- come from. This asserts the column is doing the work.
--
-- **An update cannot move a run.** The settings review of 2026-09-19 found
-- that all three `WITH CHECK` clauses in this repository were correct and
-- entirely unexercised — deleting any would have left every suite green. This
-- one is exercised.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-imp-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-imp-beta', 'Beta');

-- A run points at a real file, so the suite needs one per tenant.
insert into public.files
  (id, tenant_id, storage_key, name, size_bytes, content_type, category, status, uploaded_by)
values
  ('00000000-0000-0000-0000-0000000000f1',
   '00000000-0000-0000-0000-000000000001',
   'tenants/00000000-0000-0000-0000-000000000001/imports/f1/customers.csv',
   'customers.csv', 120, 'text/csv', 'imports', 'ready', 'user-alpha'),
  ('00000000-0000-0000-0000-0000000000f2',
   '00000000-0000-0000-0000-000000000002',
   'tenants/00000000-0000-0000-0000-000000000002/imports/f2/customers.csv',
   'customers.csv', 120, 'text/csv', 'imports', 'ready', 'user-beta');

insert into public.import_runs (id, tenant_id, target, source_file_id, requested_by, status)
values
  ('00000000-0000-0000-0000-0000000000a1',
   '00000000-0000-0000-0000-000000000001', 'shop.customers',
   '00000000-0000-0000-0000-0000000000f1', 'user-alpha', 'validated'),
  ('00000000-0000-0000-0000-0000000000a2',
   '00000000-0000-0000-0000-000000000001', 'shop.customers',
   '00000000-0000-0000-0000-0000000000f1', 'user-alpha-colleague', 'created'),
  ('00000000-0000-0000-0000-0000000000b1',
   '00000000-0000-0000-0000-000000000002', 'shop.customers',
   '00000000-0000-0000-0000-0000000000f2', 'user-beta', 'validated');

insert into public.import_row_errors (run_id, tenant_id, row_number, column_name, field, code)
values
  ('00000000-0000-0000-0000-0000000000a1',
   '00000000-0000-0000-0000-000000000001', 2, 'Email', 'email', 'import.error.email'),
  ('00000000-0000-0000-0000-0000000000b1',
   '00000000-0000-0000-0000-000000000002', 2, 'Email', 'email', 'import.error.email');

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';
set local app.user_id = 'user-alpha';

do $$
declare
  visible integer;
  state text;
begin
  -- ── a colleague's run is mine to see ─────────────────────────────────────
  --
  -- The opposite of the notification feed, and deliberately: somebody has to
  -- be able to confirm what somebody else uploaded.
  select count(*) into visible from public.import_runs;
  if visible <> 2 then
    raise exception 'import_runs: expected 2 visible rows in my tenant, saw %', visible;
  end if;

  select count(*) into visible
  from public.import_runs where requested_by = 'user-alpha-colleague';
  if visible <> 1 then
    raise exception 'import_runs: a colleague''s run in my own tenant was hidden';
  end if;

  select count(*) into visible
  from public.import_runs where tenant_id = '00000000-0000-0000-0000-000000000002';
  if visible <> 0 then
    raise exception 'import_runs: another tenant''s run was visible';
  end if;

  -- ── advancing a run ──────────────────────────────────────────────────────
  update public.import_runs set status = 'commit_requested', committed_by = 'user-alpha'
   where id = '00000000-0000-0000-0000-0000000000a1';
  select status into state from public.import_runs
   where id = '00000000-0000-0000-0000-0000000000a1';
  if state <> 'commit_requested' then
    raise exception 'import_runs: could not advance a run in my own tenant';
  end if;

  update public.import_runs set status = 'cancelled'
   where tenant_id = '00000000-0000-0000-0000-000000000002';
  get diagnostics visible = row_count;
  if visible <> 0 then
    raise exception 'import_runs: another tenant''s run was updated';
  end if;

  -- The case the `with check` exists for: one statement that reads as
  -- advancing a run and also hands it to another tenant.
  begin
    update public.import_runs
       set status = 'committed',
           tenant_id = '00000000-0000-0000-0000-000000000002'
     where id = '00000000-0000-0000-0000-0000000000a1';
    raise exception 'import_runs: an update moved a run into another tenant';
  exception
    when insufficient_privilege then null;
  end;

  -- The columns 00037 added, under the same clause rather than assumed. The
  -- figures a commit writes are exactly the kind of update a second tenant
  -- must not be able to reach, and a check constraint refuses half a record.
  update public.import_runs
     set rows_duplicate = 2, template_version = 2, job_id = 'imports.validate:x',
         predicted_create = 3, predicted_update = 1, predicted_skip = 0
   where id = '00000000-0000-0000-0000-0000000000a1';
  get diagnostics visible = row_count;
  if visible <> 1 then
    raise exception 'import_runs: could not record the figures on my own run';
  end if;
  update public.import_runs set rows_created = 1
   where tenant_id = '00000000-0000-0000-0000-000000000002';
  get diagnostics visible = row_count;
  if visible <> 0 then
    raise exception 'import_runs: another tenant''s figures were updated';
  end if;
  begin
    update public.import_runs set rows_created = 1
     where id = '00000000-0000-0000-0000-0000000000a1';
    raise exception 'import_runs: half a written record was accepted';
  exception
    when check_violation then null;
  end;

  begin
    insert into public.import_runs (tenant_id, target, source_file_id, requested_by)
    values ('00000000-0000-0000-0000-000000000002', 'shop.customers',
            '00000000-0000-0000-0000-0000000000f2', 'user-alpha');
    raise exception 'import_runs: a run was inserted into another tenant';
  exception
    when insufficient_privilege then null;
  end;

  -- ── row errors ───────────────────────────────────────────────────────────
  select count(*) into visible from public.import_row_errors;
  if visible <> 1 then
    raise exception 'import_row_errors: expected 1 visible row, saw %', visible;
  end if;

  -- Rewriting a report is how a second validation replaces the first.
  delete from public.import_row_errors
   where run_id = '00000000-0000-0000-0000-0000000000a1';
  insert into public.import_row_errors
    (run_id, tenant_id, row_number, column_name, field, code)
  values ('00000000-0000-0000-0000-0000000000a1',
          '00000000-0000-0000-0000-000000000001', 5, 'Name', 'name',
          'import.error.required');

  delete from public.import_row_errors
   where tenant_id = '00000000-0000-0000-0000-000000000002';
  get diagnostics visible = row_count;
  if visible <> 0 then
    raise exception 'import_row_errors: another tenant''s error was deleted';
  end if;

  raise notice 'import runs, one organisation one history: ok';
end
$$;

-- ── no tenant, no runs ───────────────────────────────────────────────────────
do $$
declare
  visible integer;
begin
  perform set_config('app.tenant_id', '', true);

  select count(*) into visible from public.import_runs;
  if visible <> 0 then
    raise exception 'import_runs: % rows visible with no tenant declared', visible;
  end if;

  select count(*) into visible from public.import_row_errors;
  if visible <> 0 then
    raise exception 'import_row_errors: % rows visible with no tenant declared', visible;
  end if;

  raise notice 'import runs, no tenant fails closed: ok';
end
$$;

-- ── what the database refuses whatever the caller ────────────────────────────
reset role;

do $$
begin
  begin
    insert into public.import_runs (tenant_id, target, source_file_id, requested_by, status)
    values ('00000000-0000-0000-0000-000000000001', 'shop.customers',
            '00000000-0000-0000-0000-0000000000f1', 'user-alpha', 'committed');
    raise exception 'import_runs: a committed run with no confirming actor was accepted';
  exception
    when check_violation then null;
  end;

  begin
    insert into public.import_runs (tenant_id, target, source_file_id, requested_by, status)
    values ('00000000-0000-0000-0000-000000000001', 'shop.customers',
            '00000000-0000-0000-0000-0000000000f1', 'user-alpha', 'halfway');
    raise exception 'import_runs: an unknown status was accepted';
  exception
    when check_violation then null;
  end;

  begin
    insert into public.import_runs (tenant_id, target, source_file_id, requested_by)
    values ('00000000-0000-0000-0000-000000000001', 'ShopCustomers',
            '00000000-0000-0000-0000-0000000000f1', 'user-alpha');
    raise exception 'import_runs: a target that is not dotted lower-case was accepted';
  exception
    when check_violation then null;
  end;

  -- Retention reaches an import source exactly as it reaches anything else.
  --
  -- This asserted the opposite until 2026-09-19: the foreign key was
  -- `on delete restrict` and this case proved the delete was refused. That
  -- refusal is what made the object-retention sweep abort -- after marking the
  -- row purged and deleting the bytes -- and abort again every night after,
  -- so no customer file was ever purged again. IMP-01 in
  -- `docs/features/data-import/review.md`.
  --
  -- The run survives the file: what it remembers about the import is on its own
  -- row, and the routes answer `import.source.missing` for a null.
  delete from public.files where id = '00000000-0000-0000-0000-0000000000f1';
  if exists (
    select 1 from public.import_runs
    where id = '00000000-0000-0000-0000-0000000000a1'
      and source_file_id is not null
  ) then
    raise exception 'import_runs: a purged source file did not null the reference';
  end if;
  if not exists (
    select 1 from public.import_runs where id = '00000000-0000-0000-0000-0000000000a1'
  ) then
    raise exception 'import_runs: purging the source file took the run with it';
  end if;

  raise notice 'import runs, the database keeps the two-actor rule: ok';
end
$$;

rollback;
