-- The scan sweep's one cross-tenant read, and what bounds it (secure_files, migrations 00040 and 00041).
--
-- The reconciliation sweep selects `(id, tenant_id)` of files that are ready and
-- pending, on the provisioning context, and enqueues `file.scan` per row. This
-- proves, at the database and as the unprivileged role the suite runs as:
--   1. the two partial indexes the sweep reads through exist (00041), on exactly the
--      ready + pending predicate: the global due index and the tenant due index;
--   2. a session with no tenant and no provisioning context reads no file;
--   3. a tenant's own context reads only its own pending files, so a job that
--      named another tenant's file would find no row;
--   4. the provisioning context reads both tenants' pending files (the one
--      cross-tenant read, by design) and still reads neither tenant's files that
--      are clean or infected as pending;
--   5. `scan_interrupted` is a persistable reason and the pending predicate does
--      not exclude a file because of it.
--
-- Everything happens in a transaction that rolls back. The reads are limited to this
-- test's own ids, so rows other suites leave behind on a shared database cannot matter.

\set ON_ERROR_STOP on

begin;

do $$
declare
  predicate text;
  definition text;
  index_name text;
begin
  foreach index_name in array array['files_scan_due_idx', 'files_scan_due_tenant_idx'] loop
    select pg_get_expr(i.indpred, i.indrelid), pg_get_indexdef(i.indexrelid)
      into predicate, definition
    from pg_index i join pg_class c on c.oid = i.indexrelid
    where c.relname = index_name;
    if predicate is null then
      raise exception 'scan sweep: % is missing or not partial', index_name;
    end if;
    if predicate not like '%ready%' or predicate not like '%pending%' then
      raise exception 'scan sweep: the % predicate is not ready + pending: %', index_name, predicate;
    end if;
    if definition not like '%AT TIME ZONE%' or definition not like '%make_interval%' then
      raise exception 'scan sweep: % does not index the due expression: %', index_name, definition;
    end if;
  end loop;
  if exists (select 1 from pg_class where relname = 'files_scan_pending_idx') then
    raise exception 'scan sweep: the superseded files_scan_pending_idx is still there';
  end if;
  raise notice 'scan sweep indexes: ok';
end
$$;

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-sweep-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-sweep-beta', 'Beta');

insert into public.files
  (id, tenant_id, storage_key, name, size_bytes, content_type, category, status, uploaded_by,
   scan_status, scan_failure)
values
  ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000001',
   'tenants/a/a1', 'a1.csv', 10, 'text/csv', 'imports', 'ready', 'u', 'pending', null),
  ('00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000001',
   'tenants/a/a2', 'a2.csv', 10, 'text/csv', 'imports', 'ready', 'u', 'clean', null),
  ('00000000-0000-0000-0000-0000000000b1', '00000000-0000-0000-0000-000000000002',
   'tenants/b/b1', 'b1.csv', 10, 'text/csv', 'imports', 'ready', 'u', 'pending', 'scan_interrupted'),
  ('00000000-0000-0000-0000-0000000000b2', '00000000-0000-0000-0000-000000000002',
   'tenants/b/b2', 'b2.csv', 10, 'text/csv', 'imports', 'ready', 'u', 'infected', null);

set local role koras_rls_test;

do $$
declare
  seen integer;
begin
  -- 2. No context: nothing.
  select count(*) into seen from public.files;
  if seen <> 0 then
    raise exception 'scan sweep: a session with no context read % files', seen;
  end if;
  raise notice 'scan sweep, no context: ok';
end
$$;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  ids text;
begin
  -- 3. A tenant's own context.
  select string_agg(id::text, ',' order by id) into ids
  from public.files where status = 'ready' and scan_status = 'pending'
    and id::text like '00000000-0000-0000-0000-0000000000%';
  if ids is distinct from '00000000-0000-0000-0000-0000000000a1' then
    raise exception 'scan sweep: tenant A read % as pending', ids;
  end if;
  raise notice 'scan sweep, tenant context: ok';
end
$$;

reset app.tenant_id;
set local app.provisioning = 'on';

do $$
declare
  ids text;
begin
  -- 4 and 5. The provisioning context: both tenants, pending only, interrupted included.
  select string_agg(id::text, ',' order by id) into ids
  from public.files where status = 'ready' and scan_status = 'pending'
    and id::text like '00000000-0000-0000-0000-0000000000%';
  if ids is distinct from
     '00000000-0000-0000-0000-0000000000a1,00000000-0000-0000-0000-0000000000b1' then
    raise exception 'scan sweep: provisioning read % as pending', ids;
  end if;
  raise notice 'scan sweep, provisioning context: ok';
end
$$;

rollback;
