-- The backup catalogue: a tenant reads its own and writes none of it, and the
-- catalogue outlives the object it describes.
--
-- The second property is the one worth a test. A catalogue row that went when
-- the object went would be insurance expiring at the moment of the accident,
-- and nothing about the schema makes that obvious -- `file_id` is deliberately
-- not a foreign key, and a later hand could "fix" that in one line.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-backup-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-backup-beta', 'Beta');

insert into public.files
  (id, tenant_id, name, storage_key, content_type, size_bytes, status, uploaded_by)
values
  ('80000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001',
   'a.pdf', 'tenants/1/documents/a/a.pdf', 'application/pdf', 10, 'ready', 'user-alpha'),
  ('80000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000002',
   'b.pdf', 'tenants/2/documents/b/b.pdf', 'application/pdf', 20, 'ready', 'user-beta');

insert into public.file_backups
  (id, tenant_id, file_id, source_key, backup_key, destination, size_bytes, status)
values
  ('90000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001',
   '80000000-0000-0000-0000-000000000001',
   'tenants/1/documents/a/a.pdf', 'tenants/1/documents/a/a.pdf', 'backups', 10, 'verified'),
  ('90000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000002',
   '80000000-0000-0000-0000-000000000002',
   'tenants/2/documents/b/b.pdf', 'tenants/2/documents/b/b.pdf', 'backups', 20, 'copied');

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  visible integer;
begin
  select count(*) into visible from public.file_backups;
  if visible <> 1 then
    raise exception 'backups: alpha sees %, expected its own 1', visible;
  end if;

  -- A tenant that could write here could claim a backup exists that does not,
  -- which is worse than having no catalogue at all. Every row is a sweep's.
  -- A file id no catalogue row uses, so that what refuses this is the absent
  -- insert policy and not the uniqueness index. An assertion that passes
  -- because of a different control is an assertion about the wrong thing, and
  -- it goes on passing after the control it names is removed.
  begin
    insert into public.file_backups
      (tenant_id, file_id, source_key, backup_key, destination, status)
    values ('00000000-0000-0000-0000-000000000001',
            '80000000-0000-0000-0000-00000000000f',
            'tenants/1/documents/a/a.pdf', 'anywhere', 'backups', 'verified');
    raise exception 'backups: a tenant wrote its own catalogue row';
  exception
    when insufficient_privilege then null;
  end;

  -- Nor upgrade `copied` to `verified`, which is the same claim by another route.
  update public.file_backups set status = 'verified'
   where id = '90000000-0000-0000-0000-000000000001';
  if found then
    raise exception 'backups: a tenant edited its own catalogue row';
  end if;

  raise notice 'a tenant reads its backup catalogue and writes none of it: ok';
end
$$;

-- The sweep, on the provisioning context.
select set_config('app.tenant_id', '', true) as _;
select set_config('app.provisioning', 'on', true) as _;

do $$
declare
  visible integer;
begin
  select count(*) into visible from public.file_backups;
  if visible <> 2 then
    raise exception 'backups: the sweep sees %, expected both tenants', visible;
  end if;

  -- The object goes; the catalogue row stays, and is dated.
  delete from public.files where id = '80000000-0000-0000-0000-000000000001';

  select count(*) into visible from public.file_backups
   where file_id = '80000000-0000-0000-0000-000000000001';
  if visible <> 1 then
    raise exception 'backups: the catalogue row went with the object it describes';
  end if;

  update public.file_backups
     set expires_at = now() + interval '30 days'
   where file_id = '80000000-0000-0000-0000-000000000001';
  if not found then
    raise exception 'backups: the sweep could not date an orphaned copy';
  end if;

  raise notice 'a copy outlives the object it copies: ok';
end
$$;

-- One catalogue row per object per destination. A second run updates rather
-- than laying a second row beside it, or a re-verified object reads as two
-- backups and a console counts twice.
do $$
begin
  insert into public.file_backups
    (tenant_id, file_id, source_key, backup_key, destination, status)
  values ('00000000-0000-0000-0000-000000000002',
          '80000000-0000-0000-0000-000000000002',
          'tenants/2/documents/b/b.pdf', 'tenants/2/documents/b/b.pdf', 'backups', 'verified');
  raise exception 'backups: one object gained two rows at one destination';
exception
  when unique_violation then
    raise notice 'one catalogue row per object per destination: ok';
end
$$;

rollback;
