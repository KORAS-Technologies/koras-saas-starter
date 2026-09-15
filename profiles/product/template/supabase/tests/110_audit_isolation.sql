-- The general audit table: a tenant sees and writes its own rows and changes
-- none; only the retention sweep deletes. The same proof 090 gives for the
-- assistant's table, for the one every module records to.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-gaudit-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-gaudit-beta', 'Beta');

insert into public.audit_events (tenant_id, actor_id, action, target_type, target_id, outcome, created_at)
values
  ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'report.exported', 'report', 'usage.overview', 'ok', now()),
  ('00000000-0000-0000-0000-000000000002', 'user-beta', 'report.exported', 'report', 'usage.overview', 'ok', now()),
  ('00000000-0000-0000-0000-000000000002', 'user-beta', 'report.viewed', 'report', 'people.users', 'ok', now() - interval '400 days');

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  visible integer;
begin
  select count(*) into visible from public.audit_events;
  if visible <> 1 then
    raise exception 'audit: tenant alpha sees % rows, expected its own 1', visible;
  end if;

  insert into public.audit_events (tenant_id, actor_id, action, target_type, target_id, outcome)
  values ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'report.viewed', 'report', 'people.users', 'ok');

  begin
    insert into public.audit_events (tenant_id, actor_id, action, target_type, target_id, outcome)
    values ('00000000-0000-0000-0000-000000000002', 'user-alpha', 'report.viewed', 'report', 'x', 'ok');
    raise exception 'audit: a row was written into another tenant';
  exception
    when insufficient_privilege then null;
  end;

  update public.audit_events set outcome = 'denied' where target_id = 'usage.overview';
  if found then
    raise exception 'audit: a row was rewritten';
  end if;

  delete from public.audit_events where target_id = 'usage.overview';
  if found then
    raise exception 'audit: a row was deleted by a tenant';
  end if;

  raise notice 'general audit isolation, no rewrite, no delete: ok';
end
$$;

-- The retention sweep, as the worker: only the old row goes.
select set_config('app.tenant_id', '', true) as _;
select set_config('app.provisioning', 'on', true) as _;

do $$
declare
  removed integer;
begin
  with gone as (
    delete from public.audit_events
     where created_at < now() - interval '365 days'
     returning id
  )
  select count(*) into removed from gone;
  if removed <> 1 then
    raise exception 'audit retention: removed %, expected the one 400-day-old row', removed;
  end if;
  raise notice 'general audit retention removes only old rows: ok';
end
$$;

rollback;
