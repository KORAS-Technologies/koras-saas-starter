-- Restore requests: the tenant boundary, and the two things the sweep may not do.
--
-- ADR 0006 decision 4 asks for this one by name: "cross-tenant restore must be
-- proven impossible, by an isolation test running as the restricted role, not
-- by reading the code". A restore writes bytes into a bucket under a tenant's
-- prefix, so a request that could name another tenant's file is a route from
-- one customer's data into another's.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-restore-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-restore-beta', 'Beta');

insert into public.files
  (id, tenant_id, name, storage_key, content_type, size_bytes, status, uploaded_by)
values
  ('a0000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001',
   'a.pdf', 'tenants/1/documents/a/a.pdf', 'application/pdf', 10, 'ready', 'user-alpha'),
  ('a0000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000002',
   'b.pdf', 'tenants/2/documents/b/b.pdf', 'application/pdf', 20, 'ready', 'user-beta'),
  -- Beta's third file, backed up and with no request in flight. It exists so
  -- the cross-tenant attempt below is refused by the tenant policy and not by
  -- the in-flight uniqueness index: an assertion that passes because of a
  -- different control is an assertion about the wrong thing, and it goes on
  -- passing after the control it names is removed.
  ('a0000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000002',
   'c.pdf', 'tenants/2/documents/c/c.pdf', 'application/pdf', 30, 'ready', 'user-beta');

insert into public.file_backups
  (id, tenant_id, file_id, source_key, backup_key, destination, size_bytes, status)
values
  ('b0000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001',
   'a0000000-0000-0000-0000-000000000001',
   'tenants/1/documents/a/a.pdf', 'tenants/1/documents/a/a.pdf', 'backups', 10, 'verified'),
  ('b0000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000002',
   'a0000000-0000-0000-0000-000000000002',
   'tenants/2/documents/b/b.pdf', 'tenants/2/documents/b/b.pdf', 'backups', 20, 'copied'),
  ('b0000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000002',
   'a0000000-0000-0000-0000-000000000003',
   'tenants/2/documents/c/c.pdf', 'tenants/2/documents/c/c.pdf', 'backups', 30, 'verified');

insert into public.restore_requests
  (id, tenant_id, file_id, backup_id, reason, requested_by)
values
  ('c0000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001',
   'a0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001',
   'deleted by mistake', 'user-alpha'),
  ('c0000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000002',
   'a0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000002',
   'a matter of their own', 'user-beta');

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  visible integer;
begin
  select count(*) into visible from public.restore_requests;
  if visible <> 1 then
    raise exception 'restore: alpha sees %, expected its own 1', visible;
  end if;

  -- The decision this file exists for. A request naming another tenant is a
  -- route from one customer's data into another's bucket.
  begin
    insert into public.restore_requests
      (tenant_id, file_id, backup_id, reason, requested_by)
    values ('00000000-0000-0000-0000-000000000002',
            'a0000000-0000-0000-0000-000000000003',
            'b0000000-0000-0000-0000-000000000003', 'not mine', 'user-alpha');
    raise exception 'restore: a tenant asked to restore another tenant''s file';
  exception
    when insufficient_privilege then null;
  end;

  -- Nor approve one, which is the same crossing by the other door.
  update public.restore_requests set status = 'approved', approved_by = 'user-alpha'
   where id = 'c0000000-0000-0000-0000-000000000002';
  if found then
    raise exception 'restore: a tenant approved another tenant''s request';
  end if;

  -- A refused request is the one somebody asks about later, so nobody deletes
  -- one. There is no delete policy for a tenant at all.
  delete from public.restore_requests where id = 'c0000000-0000-0000-0000-000000000001';
  if found then
    raise exception 'restore: a tenant erased its own restore history';
  end if;

  raise notice 'restore requests are a tenant''s own, and are not erasable: ok';
end
$$;

-- The sweep, on the provisioning context: it runs what was approved and cannot
-- approve anything. The second-person rule lives in the route, and a worker
-- able to approve would be a worker able to route around it.
select set_config('app.tenant_id', '', true) as _;
select set_config('app.provisioning', 'on', true) as _;

do $$
declare
  visible integer;
  affected integer;
begin
  select count(*) into visible from public.restore_requests;
  if visible <> 2 then
    raise exception 'restore: the sweep sees %, expected both tenants', visible;
  end if;

  -- Requested, not approved: the sweep may not move it at all.
  update public.restore_requests set status = 'restoring'
   where id = 'c0000000-0000-0000-0000-000000000001';
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'restore: the sweep started a request nobody approved';
  end if;

  raise notice 'the sweep cannot start an unapproved restore: ok';
end
$$;

-- Approved by a person, and only then runnable.
select set_config('app.provisioning', '', true) as _;
select set_config('app.tenant_id', '00000000-0000-0000-0000-000000000001', true) as _;
update public.restore_requests set status = 'approved', approved_by = 'user-two'
 where id = 'c0000000-0000-0000-0000-000000000001';

select set_config('app.tenant_id', '', true) as _;
select set_config('app.provisioning', 'on', true) as _;

do $$
declare
  affected integer;
  refused boolean := false;
begin
  update public.restore_requests set status = 'restoring'
   where id = 'c0000000-0000-0000-0000-000000000001';
  get diagnostics affected = row_count;
  if affected <> 1 then
    raise exception 'restore: the sweep could not start an approved request';
  end if;

  update public.restore_requests set status = 'completed'
   where id = 'c0000000-0000-0000-0000-000000000001';
  get diagnostics affected = row_count;
  if affected <> 1 then
    raise exception 'restore: the sweep could not finish what it started';
  end if;

  raise notice 'the sweep runs an approved restore and records the end: ok';
end
$$;

-- One request in flight per object. Two restores racing to write the same
-- object is the one way a non-destructive restore becomes destructive.
select set_config('app.provisioning', '', true) as _;
select set_config('app.tenant_id', '00000000-0000-0000-0000-000000000002', true) as _;

do $$
begin
  insert into public.restore_requests
    (tenant_id, file_id, backup_id, reason, requested_by)
  values ('00000000-0000-0000-0000-000000000002',
          'a0000000-0000-0000-0000-000000000002',
          'b0000000-0000-0000-0000-000000000002', 'again', 'user-beta-two');
  raise exception 'restore: one object gained two requests in flight';
exception
  when unique_violation then
    raise notice 'one request in flight per object: ok';
end
$$;

rollback;
