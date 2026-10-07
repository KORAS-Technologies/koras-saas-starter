-- File scan columns: shape, constraints, and tenant isolation (secure_files, migrations
-- 00039 and 00040).
--
-- 00039 adds scan_attempts, scan_attempted_at, scan_failure and scan_object_etag
-- to `public.files`; this proves, at the database and as the application role:
--   1. shape: types, nullability, defaults, and the two check constraints;
--   2. a row written without naming them takes the inert defaults and is not
--      reinterpreted: status and scan_status are exactly what was written;
--   3. scan_attempts rejects a negative value and nothing else; scan_failure
--      accepts exactly the thirteen reasons (the twelve of 00039 and 00040's
--      `scan_interrupted`, and null) and refuses the
--      rest, `scan_exhausted` included; recording a reason changes no status;
--   4. no scan column is named like a digest;
--   5. tenant A cannot read, update or insert the scan fields of tenant B's
--      file, and no policy was added for them.
--
-- Everything happens in a transaction that rolls back.

\set ON_ERROR_STOP on

begin;

do $$
declare
  got text;
begin
  select string_agg(column_name || ':' || data_type || ':' || is_nullable || ':' || coalesce(column_default, '-'),
                    ' | ' order by column_name)
    into got
  from information_schema.columns
  where table_schema = 'public' and table_name = 'files'
    and column_name in ('scan_attempts', 'scan_attempted_at', 'scan_failure', 'scan_object_etag');
  if got is distinct from
     'scan_attempted_at:timestamp with time zone:YES:- | scan_attempts:smallint:NO:0 | scan_failure:text:YES:- | scan_object_etag:text:YES:-' then
    raise exception 'scan columns: unexpected shape: %', got;
  end if;

  if (select count(*) from pg_constraint
      where conrelid = 'public.files'::regclass and contype = 'c'
        and conname in ('files_scan_attempts_check', 'files_scan_failure_check')) <> 2 then
    raise exception 'scan columns: a check constraint is missing';
  end if;

  -- The ETag is identity evidence. No scan column may read as a digest.
  if exists (select 1 from information_schema.columns
             where table_schema = 'public' and table_name = 'files'
               and column_name like 'scan%'
               and (column_name like '%sha%' or column_name like '%digest%'
                    or column_name like '%checksum%' or column_name like '%hash%')) then
    raise exception 'scan columns: a scan column is named like a digest';
  end if;

  -- No policy was added for the new columns: none of files' policies speaks of
  -- a scan field. Isolation itself is proved by behaviour, below.
  if exists (select 1 from pg_policies
             where schemaname = 'public' and tablename = 'files'
               and (coalesce(qual, '') like '%scan\_%' or coalesce(with_check, '') like '%scan\_%')) then
    raise exception 'scan columns: a files policy refers to a scan column';
  end if;

  raise notice 'scan columns structure: ok';
end
$$;

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-scan-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-scan-beta', 'Beta');

-- Written as a pre-00039 caller would write them: the scan columns are not named.
insert into public.files
  (id, tenant_id, storage_key, name, size_bytes, content_type, category, status, uploaded_by, scan_status)
values
  ('00000000-0000-0000-0000-0000000000f1', '00000000-0000-0000-0000-000000000001',
   'tenants/00000000-0000-0000-0000-000000000001/imports/f1/a.csv', 'a.csv', 10,
   'text/csv', 'imports', 'ready', 'user-alpha', 'pending'),
  ('00000000-0000-0000-0000-0000000000f2', '00000000-0000-0000-0000-000000000002',
   'tenants/00000000-0000-0000-0000-000000000002/imports/f2/b.csv', 'b.csv', 10,
   'text/csv', 'imports', 'ready', 'user-beta', 'pending');

-- As the owner: give tenant B's file scan evidence for the isolation checks.
update public.files
set scan_attempts = 3, scan_failure = 'scan_timeout', scan_object_etag = 'etag-beta',
    scan_attempted_at = now()
where id = '00000000-0000-0000-0000-0000000000f2';

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  r public.files%rowtype;
  reason text;
  seen integer;
  changed integer;
begin
  -- 2. Defaults; nothing reinterpreted.
  select * into r from public.files where id = '00000000-0000-0000-0000-0000000000f1';
  if r.scan_attempts <> 0 or r.scan_attempted_at is not null or r.scan_failure is not null
     or r.scan_object_etag is not null then
    raise exception 'scan columns: defaults are not inert';
  end if;
  if r.status <> 'ready' or r.scan_status <> 'pending' then
    raise exception 'scan columns: status or scan_status changed';
  end if;

  -- 3. scan_attempts.
  begin
    update public.files set scan_attempts = -1 where id = r.id;
    raise exception 'scan columns: a negative scan_attempts was accepted';
  exception when check_violation then null;
  end;
  update public.files set scan_attempts = 32767 where id = r.id;
  update public.files set scan_attempts = 0 where id = r.id;

  -- scan_failure: exactly the ratified set, one at a time, status untouched.
  foreach reason in array array[
    'scanner_unavailable', 'scan_timeout', 'malformed_response', 'scanner_error',
    'object_unreachable', 'object_changed', 'integrity_mismatch', 'over_ceiling',
    'misconfigured', 'scan_limit_exceeded', 'inspection_incomplete', 'identity_insufficient',
    'scan_interrupted']
  loop
    update public.files set scan_failure = reason where id = r.id;
    select * into r from public.files where id = r.id;
    if r.scan_failure <> reason or r.status <> 'ready' or r.scan_status <> 'pending' then
      raise exception 'scan columns: recording % changed a status', reason;
    end if;
  end loop;
  update public.files set scan_failure = null where id = r.id;

  foreach reason in array array['scan_exhausted', 'scan_abandoned', 'clean', 'infected', 'skipped', 'quarantined', '', 'Scanner_Error']
  loop
    begin
      update public.files set scan_failure = reason where id = r.id;
      raise exception 'scan columns: scan_failure % was accepted', reason;
    exception when check_violation then null;
    end;
  end loop;

  -- The columns take together the evidence the scanner records.
  update public.files
  set scan_attempts = 1, scan_attempted_at = now(), scan_failure = 'identity_insufficient',
      scan_object_etag = 'etag-alpha'
  where id = r.id;

  -- 5. Tenant isolation through the existing policies.
  select count(*) into seen from public.files where id = '00000000-0000-0000-0000-0000000000f2';
  if seen <> 0 then
    raise exception 'scan columns: another tenant''s file is readable';
  end if;
  select count(*) into seen from public.files
  where scan_object_etag = 'etag-beta' or scan_failure = 'scan_timeout';
  if seen <> 0 then
    raise exception 'scan columns: another tenant''s scan evidence is searchable';
  end if;
  update public.files set scan_attempts = 9, scan_failure = 'misconfigured'
  where id = '00000000-0000-0000-0000-0000000000f2';
  get diagnostics changed = row_count;
  if changed <> 0 then
    raise exception 'scan columns: another tenant''s scan fields were updated';
  end if;
  begin
    insert into public.files (tenant_id, storage_key, name, size_bytes, uploaded_by, scan_failure)
    values ('00000000-0000-0000-0000-000000000002', 'tenants/b/x', 'x', 1, 'user-alpha', 'scan_timeout');
    raise exception 'scan columns: a row was inserted into another tenant';
  exception when insufficient_privilege then null;
  end;
  begin
    update public.files set tenant_id = '00000000-0000-0000-0000-000000000002', scan_failure = null
    where id = '00000000-0000-0000-0000-0000000000f1';
    raise exception 'scan columns: a file was moved to another tenant';
  exception when insufficient_privilege then null;
  end;

  raise notice 'scan columns: defaults, constraints and tenant isolation: ok';
end
$$;

-- From the other side: tenant B still holds exactly what the owner wrote.
reset role;
do $$
declare
  r public.files%rowtype;
begin
  select * into r from public.files where id = '00000000-0000-0000-0000-0000000000f2';
  if r.scan_attempts <> 3 or r.scan_failure <> 'scan_timeout' or r.scan_object_etag <> 'etag-beta' then
    raise exception 'scan columns: tenant B''s scan evidence was altered by tenant A';
  end if;
end
$$;

rollback;
