-- The audit table: a tenant sees and writes its own rows and changes none;
-- only the retention sweep deletes.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-audit-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-audit-beta', 'Beta');

insert into public.ai_audit_events (tenant_id, actor_id, action, target_type, target_id, outcome, created_at)
values
  ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'ai.action.approved', 'action', 'a1', 'success', now()),
  ('00000000-0000-0000-0000-000000000002', 'user-beta', 'ai.action.approved', 'action', 'b1', 'success', now()),
  ('00000000-0000-0000-0000-000000000002', 'user-beta', 'ai.tool.proposed', 'action', 'b0', 'success', now() - interval '400 days');

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  visible integer;
begin
  select count(*) into visible from public.ai_audit_events;
  if visible <> 1 then
    raise exception 'audit: tenant alpha sees % rows, expected its own 1', visible;
  end if;

  insert into public.ai_audit_events (tenant_id, actor_id, action, target_type, target_id, outcome)
  values ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'ai.tool.refused', 'tool', 'files.delete', 'refused');

  begin
    insert into public.ai_audit_events (tenant_id, actor_id, action, target_type, target_id, outcome)
    values ('00000000-0000-0000-0000-000000000002', 'user-alpha', 'ai.tool.refused', 'tool', 'x', 'refused');
    raise exception 'audit: a row was written into another tenant';
  exception
    when insufficient_privilege then null;
  end;

  update public.ai_audit_events set outcome = 'success' where target_id = 'a1';
  if found then
    raise exception 'audit: a row was rewritten';
  end if;

  delete from public.ai_audit_events where target_id = 'a1';
  if found then
    raise exception 'audit: a row was deleted by a tenant';
  end if;

  raise notice 'audit isolation, no rewrite, no delete: ok';
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
    delete from public.ai_audit_events
     where created_at < now() - interval '365 days'
     returning id
  )
  select count(*) into removed from gone;
  if removed <> 1 then
    raise exception 'audit retention: removed %, expected the one 400-day-old row', removed;
  end if;
  raise notice 'audit retention removes only old rows: ok';
end
$$;

rollback;
