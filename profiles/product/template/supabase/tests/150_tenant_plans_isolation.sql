-- The plan snapshot: a tenant reads its own and nothing of another's, writes
-- none, and the provisioning context -- the platform's route -- writes any.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-plan-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-plan-beta', 'Beta');

insert into public.tenant_plans (tenant_id, plan_code, status, entitlements)
values
  ('00000000-0000-0000-0000-000000000001', 'business', 'active',
   '{"reporting.scheduled": {"enabled": true, "limit": null}}'),
  ('00000000-0000-0000-0000-000000000002', 'starter', 'active', '{}');

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  visible integer;
  seen text;
begin
  select count(*) into visible from public.tenant_plans;
  if visible <> 1 then
    raise exception 'tenant plans: tenant alpha sees %, expected its own 1', visible;
  end if;
  select plan_code into seen from public.tenant_plans;
  if seen <> 'business' then
    raise exception 'tenant plans: tenant alpha read plan %', seen;
  end if;

  -- A tenant cannot promote itself.
  update public.tenant_plans set plan_code = 'enterprise';
  select plan_code into seen from public.tenant_plans;
  if seen <> 'business' then
    raise exception 'tenant plans: a tenant rewrote its own plan';
  end if;
  begin
    insert into public.tenant_plans (tenant_id, plan_code)
    values ('00000000-0000-0000-0000-000000000001', 'enterprise');
    raise exception 'tenant plans: a tenant inserted a plan row';
  exception
    when unique_violation or insufficient_privilege then
      raise notice 'tenant plans: insert refused for a tenant: ok';
  end;
end
$$;

-- The platform's route, on the provisioning context: writes any tenant's row.
select set_config('app.tenant_id', '', true) as _;
select set_config('app.provisioning', 'on', true) as _;

do $$
declare
  seen text;
begin
  insert into public.tenant_plans (tenant_id, plan_code, status, entitlements)
  values ('00000000-0000-0000-0000-000000000002', 'pro', 'active', '{}')
  on conflict (tenant_id) do update
    set plan_code = excluded.plan_code, synced_at = now();
  select plan_code into seen from public.tenant_plans
  where tenant_id = '00000000-0000-0000-0000-000000000002';
  if seen <> 'pro' then
    raise exception 'tenant plans: the provisioning context could not replace a plan';
  end if;
  raise notice 'tenant plans: isolation and the platform write: ok';
end
$$;

rollback;
