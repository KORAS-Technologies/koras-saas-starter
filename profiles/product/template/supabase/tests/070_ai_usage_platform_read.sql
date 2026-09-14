-- The platform reads every tenant's AI usage; it writes none of it.
--
-- The provisioning context is what the private platform API runs under. It
-- must see the rows of every tenant, because the Control Plane collects usage
-- for the whole estate, and it must not be able to insert one, because usage
-- is a fact about a call the product made. Both halves are asserted: a policy
-- that granted the read alone could be widened to a write by the next
-- migration without anything going red.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-usage-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-usage-beta', 'Beta');

insert into public.ai_usage_events
  (tenant_id, user_id, agent_id, model_alias, provider, model, status, input_tokens, output_tokens, total_tokens, estimated_cost_micros)
values
  ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'assistant', 'koras-balanced', 'openai', 'gpt-4o-mini', 'ok', 100, 50, 150, 45),
  ('00000000-0000-0000-0000-000000000002', 'user-beta', 'assistant', 'koras-balanced', 'openai', 'gpt-4o-mini', 'error', 0, 0, 0, null);

-- The platform, on the provisioning session: both tenants' rows, aggregated.
set local role koras_rls_test;
select set_config('app.tenant_id', '', true) as _;
select set_config('app.provisioning', 'on', true) as _;

do $$
declare
  visible integer;
  tenants integer;
  cost bigint;
begin
  select count(*), count(distinct tenant_id), sum(coalesce(estimated_cost_micros, 0))
    into visible, tenants, cost
  from public.ai_usage_events
  where tenant_id in ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002');

  if visible <> 2 or tenants <> 2 then
    raise exception 'the provisioning context sees % rows of % tenants; it must see both tenants', visible, tenants;
  end if;
  if cost <> 45 then
    raise exception 'the estimated cost summed to %, not 45', cost;
  end if;
  raise notice 'provisioning context reads every tenant''s usage: ok';

  begin
    insert into public.ai_usage_events (tenant_id, user_id, agent_id, model_alias, provider, model, status)
    values ('00000000-0000-0000-0000-000000000001', 'platform', 'assistant', 'koras-fast', 'openai', 'gpt-4o-mini', 'ok');
    raise exception 'the provisioning context inserted a usage row; the platform must only read';
  exception
    when insufficient_privilege then
      raise notice 'provisioning context cannot write usage: ok';
  end;
end
$$;

rollback;

-- A tenant, with the provisioning flag off: its own rows and nothing more.
-- 060 covers this for every AI table; repeated here for the one column this
-- migration added, so a cost is never a way to see across tenants.
begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-usage-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-usage-beta', 'Beta');

insert into public.ai_usage_events
  (tenant_id, user_id, agent_id, model_alias, provider, model, status, estimated_cost_micros)
values
  ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'assistant', 'koras-balanced', 'openai', 'gpt-4o-mini', 'ok', 45),
  ('00000000-0000-0000-0000-000000000002', 'user-beta', 'assistant', 'koras-balanced', 'openai', 'gpt-4o-mini', 'ok', 99);

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000002';

do $$
declare
  cost bigint;
begin
  select sum(estimated_cost_micros) into cost from public.ai_usage_events;
  if cost <> 99 then
    raise exception 'tenant beta summed % of estimated cost; it must see only its own 99', cost;
  end if;
  raise notice 'a tenant sums only its own cost: ok';
end
$$;

rollback;
