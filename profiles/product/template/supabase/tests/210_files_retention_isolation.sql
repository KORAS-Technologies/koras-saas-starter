-- Object retention: what the lifecycle sweep may reach, and what a hold stops.
--
-- 00021 gives `files` its first provisioning policies, because the sweep that
-- resolves and purges retention runs on the only context that reaches every
-- tenant. Three things are asserted, and the third is the whole point of the
-- legal hold:
--
--   * provisioning may read and remove, and may not create a file row;
--   * a tenant still cannot see another tenant's rows, unchanged by 00021;
--   * a row under a hold is not selected by the sweep's own query, whether the
--     hold is the per-object flag or a `legal_holds` record covering the scope.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-ret-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-ret-beta', 'Beta');

insert into public.files
  (tenant_id, storage_key, name, size_bytes, status, uploaded_by, retain_until, legal_hold)
values
  -- Due, unheld: the sweep should find exactly this one for Alpha.
  ('00000000-0000-0000-0000-000000000001', 'tenants/alpha/documents/a/due.pdf',
   'due.pdf', 10, 'ready', 'user-alpha', now() - interval '1 day', false),
  -- Due, but flagged on the object itself.
  ('00000000-0000-0000-0000-000000000001', 'tenants/alpha/documents/b/flagged.pdf',
   'flagged.pdf', 10, 'ready', 'user-alpha', now() - interval '1 day', true),
  -- No policy resolved. Null is not expired, and must never be swept.
  ('00000000-0000-0000-0000-000000000001', 'tenants/alpha/documents/c/unresolved.pdf',
   'unresolved.pdf', 10, 'ready', 'user-alpha', null, false),
  -- Not due yet.
  ('00000000-0000-0000-0000-000000000001', 'tenants/alpha/documents/d/future.pdf',
   'future.pdf', 10, 'ready', 'user-alpha', now() + interval '365 days', false),
  -- Beta: due and unflagged, but covered by a hold record below.
  ('00000000-0000-0000-0000-000000000002', 'tenants/beta/documents/e/beta.pdf',
   'beta.pdf', 10, 'ready', 'user-beta', now() - interval '1 day', false);

insert into public.legal_holds (tenant_id, scope, reason, requested_by, approved_by, status)
values ('00000000-0000-0000-0000-000000000002', 'files', 'beta matter', 'user-beta',
        'owner-beta', 'active');

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  visible integer;
begin
  -- 00021 added provisioning policies and must not have widened the tenant's
  -- own view by accident.
  select count(*) into visible from public.files;
  if visible <> 4 then
    raise exception 'retention: expected 4 rows visible to alpha, saw %', visible;
  end if;

  select count(*) into visible from public.files where name = 'beta.pdf';
  if visible <> 0 then
    raise exception 'retention: another tenant''s file was visible';
  end if;

  raise notice 'files retention tenant view: ok';
end
$$;

do $$
declare
  due     integer;
  held    integer;
  removed integer;
begin
  perform set_config('app.tenant_id', '', true);
  perform set_config('app.provisioning', 'on', true);

  -- This is the sweep's own query, verbatim in shape.
  select count(*) into due
    from public.files f
   where f.retain_until is not null and f.retain_until < now()
     and f.legal_hold = false and f.status <> 'purged'
     and not public.under_legal_hold(f.tenant_id, 'files');

  -- Exactly one: alpha's `due.pdf`. The flagged one is excluded by its own
  -- column, beta's by a hold record, and the unresolved and future ones by
  -- their dates.
  if due <> 1 then
    raise exception 'retention: the sweep would take % rows, expected 1', due;
  end if;

  select count(*) into held
    from public.files f
   where f.retain_until is not null and f.retain_until < now() and f.status <> 'purged'
     and (f.legal_hold = true or public.under_legal_hold(f.tenant_id, 'files'));
  if held <> 2 then
    raise exception 'retention: expected 2 held rows, saw %', held;
  end if;

  -- Provisioning may mark a row purged, which the sweep does before removing
  -- the object.
  update public.files set status = 'purged' where name = 'due.pdf';
  if not found then
    raise exception 'retention: provisioning could not mark a row purged';
  end if;

  -- And may remove it.
  with gone as (
    delete from public.files where name = 'due.pdf' returning id
  )
  select count(*) into removed from gone;
  if removed <> 1 then
    raise exception 'retention: provisioning removed % rows, expected 1', removed;
  end if;

  -- And may not create one. A sweep that could insert a file row could do
  -- considerably more than remove an expired one, and nothing needs it to.
  begin
    insert into public.files (tenant_id, storage_key, name, size_bytes, uploaded_by)
    values ('00000000-0000-0000-0000-000000000001', 'tenants/alpha/documents/x/planted.pdf',
            'planted.pdf', 1, 'system');
    raise exception 'retention: provisioning created a file row';
  exception
    when insufficient_privilege then null;
  end;

  raise notice 'files retention sweep access: ok';
end
$$;

rollback;
