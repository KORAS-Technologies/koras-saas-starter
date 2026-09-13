-- The assistant's tables: one tenant's conversations, messages, actions and
-- usage never show, admit or lose another's rows.
--
-- The same shape as 050, for the four tables the AI runtime writes. Reads and
-- writes both, and the approval row in particular: an action a person of
-- tenant B could approve would run a tool against tenant A's data on B's word,
-- which is the one thing the approval workflow exists to make impossible.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-ai-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-ai-beta', 'Beta');

insert into public.ai_conversations (id, tenant_id, created_by, agent_id, title)
values
  ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'user-alpha', 'assistant', 'Alpha asks'),
  ('10000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000002', 'user-beta', 'assistant', 'Beta asks');

insert into public.ai_messages (tenant_id, conversation_id, role, content)
values
  ('00000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'user', 'alpha secret'),
  ('00000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', 'user', 'beta secret');

insert into public.ai_actions (id, tenant_id, conversation_id, tool_id, tool_call_id, operation, status, proposed_by)
values
  ('20000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'files.delete', 'c1', 'destructive', 'awaiting_approval', 'user-alpha'),
  ('20000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', 'files.delete', 'c2', 'destructive', 'awaiting_approval', 'user-beta');

insert into public.ai_usage_events (tenant_id, user_id, agent_id, model_alias, provider, model, status)
values
  ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'assistant', 'koras-balanced', 'openai', 'gpt-4o', 'ok'),
  ('00000000-0000-0000-0000-000000000002', 'user-beta', 'assistant', 'koras-balanced', 'openai', 'gpt-4o', 'ok');

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  visible integer;
begin
  select count(*) into visible from public.ai_conversations;
  if visible <> 1 then
    raise exception 'ai: expected 1 visible conversation, saw %', visible;
  end if;

  select count(*) into visible from public.ai_messages where content = 'beta secret';
  if visible <> 0 then
    raise exception 'ai: another tenant''s message was visible';
  end if;

  select count(*) into visible from public.ai_actions where proposed_by = 'user-beta';
  if visible <> 0 then
    raise exception 'ai: another tenant''s action was visible';
  end if;

  select count(*) into visible from public.ai_usage_events;
  if visible <> 1 then
    raise exception 'ai: expected 1 visible usage event, saw %', visible;
  end if;

  -- An insert naming the other tenant must be refused, not stored unseen.
  begin
    insert into public.ai_messages (tenant_id, conversation_id, role, content)
    values ('00000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', 'user', 'x');
    raise exception 'ai: a message was written into another tenant';
  exception
    when insufficient_privilege then null;
  end;

  -- The other tenant's waiting action cannot be approved from here.
  update public.ai_actions
     set status = 'approved', decided_by = 'user-alpha'
   where id = '20000000-0000-0000-0000-000000000002';
  if found then
    raise exception 'ai: another tenant''s action was approved';
  end if;

  -- A conversation cannot be moved to another tenant.
  begin
    update public.ai_conversations
       set tenant_id = '00000000-0000-0000-0000-000000000002'
     where id = '10000000-0000-0000-0000-000000000001';
    raise exception 'ai: a conversation was moved to another tenant';
  exception
    when insufficient_privilege then null;
  end;

  -- A usage row is a fact: nobody the policies apply to may rewrite one.
  begin
    delete from public.ai_usage_events;
    if found then
      raise exception 'ai: a usage event was deleted';
    end if;
  exception
    when insufficient_privilege then null;
  end;

  raise notice 'ai isolation: ok';
end
$$;

rollback;
