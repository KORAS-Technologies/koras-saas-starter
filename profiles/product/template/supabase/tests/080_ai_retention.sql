-- Retention deletes across tenants on the provisioning session, and only there.
--
-- The sweep runs as the worker, in the provisioning context, and must remove
-- an old conversation whichever tenant holds it, with its messages and
-- actions. A tenant's own session must not be able to delete another
-- tenant's conversation, and the usage rows must survive the sweep with
-- their conversation id cleared: the metering outlives the content.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-ret-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-ret-beta', 'Beta');

insert into public.ai_conversations (id, tenant_id, created_by, agent_id, title, created_at, updated_at)
values
  ('30000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'user-alpha', 'assistant', 'Old alpha', now() - interval '200 days', now() - interval '200 days'),
  ('30000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000002', 'user-beta', 'assistant', 'Old beta', now() - interval '200 days', now() - interval '200 days'),
  ('30000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000002', 'user-beta', 'assistant', 'Recent beta', now(), now());

insert into public.ai_messages (tenant_id, conversation_id, role, content)
values
  ('00000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', 'user', 'alpha old'),
  ('00000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000002', 'user', 'beta old'),
  ('00000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000003', 'user', 'beta recent');

insert into public.ai_usage_events (tenant_id, user_id, conversation_id, agent_id, model_alias, provider, model, status)
values
  ('00000000-0000-0000-0000-000000000001', 'user-alpha', '30000000-0000-0000-0000-000000000001', 'assistant', 'koras-balanced', 'openai', 'gpt-4o-mini', 'ok'),
  ('00000000-0000-0000-0000-000000000002', 'user-beta', '30000000-0000-0000-0000-000000000002', 'assistant', 'koras-balanced', 'openai', 'gpt-4o-mini', 'ok');

-- A tenant cannot reach the other tenant's conversation, old or not.
set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
begin
  delete from public.ai_conversations
   where id = '30000000-0000-0000-0000-000000000002';
  if found then
    raise exception 'retention: a tenant deleted another tenant''s conversation';
  end if;
  raise notice 'a tenant cannot delete across tenants: ok';
end
$$;

-- The sweep, as the worker: every tenant's old conversations go and the
-- recent one stays.
select set_config('app.tenant_id', '', true) as _;
select set_config('app.provisioning', 'on', true) as _;

do $$
declare
  removed integer;
begin
  with gone as (
    delete from public.ai_conversations
     where updated_at < now() - interval '90 days'
     returning id
  )
  select count(*) into removed from gone;
  if removed <> 2 then
    raise exception 'retention: removed % conversations, expected 2 (one per tenant)', removed;
  end if;
  raise notice 'the sweep removes old conversations across tenants: ok';
end
$$;

-- Back as the owner to count what the cascade did, since the provisioning
-- context has no read policy on messages or usage and should not.
reset role;
select set_config('app.provisioning', 'off', true) as _;
set local app.tenant_id = '00000000-0000-0000-0000-000000000002';

do $$
declare
  messages integer;
  usage_rows integer;
  orphaned integer;
begin
  select count(*) into messages from public.ai_messages;
  if messages <> 1 then
    raise exception 'retention: % messages remain, expected the one recent message', messages;
  end if;

  select count(*), count(*) filter (where conversation_id is null)
    into usage_rows, orphaned
  from public.ai_usage_events
  where tenant_id in ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002');
  if usage_rows <> 2 or orphaned <> 2 then
    raise exception 'retention: usage rows %, with no conversation %; expected 2 and 2', usage_rows, orphaned;
  end if;
  raise notice 'messages cascade and usage survives: ok';
end
$$;

rollback;
