-- Migration: 00006_ai
-- The assistant's runtime state: conversations, their messages, the actions
-- a model proposed and a person decided, and one row per model call.
--
-- Four tables, one shape: `tenant_id`, RLS enabled and forced, and a policy
-- per verb scoped on `current_tenant_id()`, exactly as `files` is. Every
-- statement the API runs names the tenant as well; the policies are the
-- backstop against a query that forgets.
--
-- What is stored where, and why. Messages hold content, because a
-- conversation is the content. Actions hold the model's proposed input, bounded
-- by the tool's schema, because that is what runs after a person approves it.
-- Usage events hold dimensions and counts and no content at all: they are kept
-- longer and read by more people than the conversation they describe, and a
-- meter that carried the prompt would be a second copy of it with a wider
-- audience. No table holds a provider credential, and `model` is the gateway's
-- model name, recorded so a bill can be explained -- it is never shown to a
-- customer.
--
-- Retention is the product's decision and is not made here. Every table
-- carries `created_at` so a sweep can be written without a second migration.

-- ── Conversations ────────────────────────────────────────────────────────────
create table public.ai_conversations (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references public.tenants(id) on delete cascade,
  -- The ZITADEL subject who started it, as `tenant_members.user_id` is.
  created_by    text not null,
  agent_id      text not null,
  title         text not null default '',
  -- The screen the assistant was opened beside. Informational: it scopes
  -- nothing and authorises nothing, and a tool that reads the resource it
  -- names still runs under this tenant's session and its own permission.
  context_type  text,
  context_id    text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index ai_conversations_tenant_idx
  on public.ai_conversations (tenant_id, updated_at desc);

alter table public.ai_conversations enable row level security;
alter table public.ai_conversations force row level security;

drop policy if exists "ai_conversations_select_own_tenant" on public.ai_conversations;
create policy "ai_conversations_select_own_tenant"
  on public.ai_conversations for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "ai_conversations_insert_own_tenant" on public.ai_conversations;
create policy "ai_conversations_insert_own_tenant"
  on public.ai_conversations for insert
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "ai_conversations_update_own_tenant" on public.ai_conversations;
create policy "ai_conversations_update_own_tenant"
  on public.ai_conversations for update
  using (tenant_id = public.current_tenant_id())
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "ai_conversations_delete_own_tenant" on public.ai_conversations;
create policy "ai_conversations_delete_own_tenant"
  on public.ai_conversations for delete
  using (tenant_id = public.current_tenant_id());

-- ── Messages ─────────────────────────────────────────────────────────────────
create table public.ai_messages (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references public.tenants(id) on delete cascade,
  conversation_id  uuid not null references public.ai_conversations(id) on delete cascade,
  role             text not null check (role in ('system', 'user', 'assistant', 'tool')),
  content          text not null default '',
  -- The calls an assistant message proposed, as the model shaped them. The
  -- authoritative record of what happened to each is `ai_actions`.
  tool_calls       jsonb not null default '{}',
  -- Set on a tool message: which call it answers, and which tool answered.
  tool_call_id     text,
  tool_name        text,
  created_at       timestamptz not null default now()
);

create index ai_messages_conversation_idx
  on public.ai_messages (tenant_id, conversation_id, created_at);

alter table public.ai_messages enable row level security;
alter table public.ai_messages force row level security;

drop policy if exists "ai_messages_select_own_tenant" on public.ai_messages;
create policy "ai_messages_select_own_tenant"
  on public.ai_messages for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "ai_messages_insert_own_tenant" on public.ai_messages;
create policy "ai_messages_insert_own_tenant"
  on public.ai_messages for insert
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "ai_messages_update_own_tenant" on public.ai_messages;
create policy "ai_messages_update_own_tenant"
  on public.ai_messages for update
  using (tenant_id = public.current_tenant_id())
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "ai_messages_delete_own_tenant" on public.ai_messages;
create policy "ai_messages_delete_own_tenant"
  on public.ai_messages for delete
  using (tenant_id = public.current_tenant_id());

-- ── Actions ──────────────────────────────────────────────────────────────────
--
-- A model's proposal and what became of it. `status` is the state machine in
-- `koras_ai.actions`; the database repeats the vocabulary so a row cannot hold
-- a word the runtime does not know.
create table public.ai_actions (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references public.tenants(id) on delete cascade,
  conversation_id  uuid not null references public.ai_conversations(id) on delete cascade,
  message_id       uuid references public.ai_messages(id) on delete set null,
  tool_id          text not null,
  tool_call_id     text not null,
  operation        text not null
                   check (operation in ('read', 'write', 'destructive', 'external')),
  input            jsonb not null default '{}',
  status           text not null check (status in (
                     'proposed', 'awaiting_approval', 'approved', 'rejected',
                     'executing', 'completed', 'failed'
                   )),
  proposed_by      text not null,
  decided_by       text,
  decided_at       timestamptz,
  result           jsonb,
  -- A safe sentence. Never a stack, never a provider body.
  error            text,
  executed_at      timestamptz,
  created_at       timestamptz not null default now()
);

create index ai_actions_pending_idx
  on public.ai_actions (tenant_id, conversation_id, created_at)
  where status = 'awaiting_approval';

alter table public.ai_actions enable row level security;
alter table public.ai_actions force row level security;

drop policy if exists "ai_actions_select_own_tenant" on public.ai_actions;
create policy "ai_actions_select_own_tenant"
  on public.ai_actions for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "ai_actions_insert_own_tenant" on public.ai_actions;
create policy "ai_actions_insert_own_tenant"
  on public.ai_actions for insert
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "ai_actions_update_own_tenant" on public.ai_actions;
create policy "ai_actions_update_own_tenant"
  on public.ai_actions for update
  using (tenant_id = public.current_tenant_id())
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "ai_actions_delete_own_tenant" on public.ai_actions;
create policy "ai_actions_delete_own_tenant"
  on public.ai_actions for delete
  using (tenant_id = public.current_tenant_id());

-- ── Usage events ─────────────────────────────────────────────────────────────
--
-- One row per model call, attempts that failed included: a caller who can
-- spend the provider's time without spending their allowance has an
-- allowance that bounds nothing. The monthly count the plan enforces is
-- `count(*)` over this table by tenant and month, which the index serves.
create table public.ai_usage_events (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references public.tenants(id) on delete cascade,
  user_id          text not null,
  conversation_id  uuid references public.ai_conversations(id) on delete set null,
  agent_id         text not null,
  model_alias      text not null,
  provider         text not null,
  model            text not null,
  input_tokens     integer not null default 0 check (input_tokens >= 0),
  output_tokens    integer not null default 0 check (output_tokens >= 0),
  total_tokens     integer not null default 0 check (total_tokens >= 0),
  latency_ms       integer not null default 0 check (latency_ms >= 0),
  status           text not null,
  error_code       text,
  created_at       timestamptz not null default now()
);

create index ai_usage_events_tenant_month_idx
  on public.ai_usage_events (tenant_id, created_at desc);

alter table public.ai_usage_events enable row level security;
alter table public.ai_usage_events force row level security;

drop policy if exists "ai_usage_events_select_own_tenant" on public.ai_usage_events;
create policy "ai_usage_events_select_own_tenant"
  on public.ai_usage_events for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "ai_usage_events_insert_own_tenant" on public.ai_usage_events;
create policy "ai_usage_events_insert_own_tenant"
  on public.ai_usage_events for insert
  with check (tenant_id = public.current_tenant_id());

-- No update and no delete policy: a usage row is a fact about a call that
-- happened, and a table with RLS forced and no policy for a verb refuses that
-- verb to every role the policies apply to. A retention sweep runs as the
-- migrations do and adds its own policy when it exists.
