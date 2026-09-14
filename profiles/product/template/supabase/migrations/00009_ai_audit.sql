-- AI audit: what the assistant did, durable, per tenant.
--
-- Every refusal, proposal, execution, approval and rejection already emits
-- an audit event -- actor, tenant, target, outcome, and never content. It
-- went to the structured log, which is searchable for a while and then
-- gone. This is the table that keeps it, so a customer can be shown what
-- the assistant did in their organization, and a question from a regulated
-- customer has an answer older than the log retention.
--
-- The same shape as every AI table: a tenant column, RLS enabled and
-- forced, a policy per verb scoped on the tenant helper. Insert and select
-- for the tenant; no update and no delete for anyone the policies apply to,
-- because an audit row that can be edited is not an audit row. The one
-- exception is the retention sweep, on the provisioning context, which may
-- delete and nothing else.
--
-- `details` is the event's own detail map, which `koras_audit` refuses to
-- build with anything that looks like a secret. It still never holds a
-- message or a tool's input: those stay in the conversation.

create table public.ai_audit_events (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references public.tenants(id) on delete cascade,
  actor_id     text not null,
  action       text not null,
  target_type  text not null,
  target_id    text not null,
  outcome      text not null,
  details      jsonb not null default '{}',
  created_at   timestamptz not null default now()
);

create index ai_audit_events_tenant_time_idx
  on public.ai_audit_events (tenant_id, created_at desc);

alter table public.ai_audit_events enable row level security;
alter table public.ai_audit_events force row level security;

drop policy if exists "ai_audit_events_select_own_tenant" on public.ai_audit_events;
create policy "ai_audit_events_select_own_tenant"
  on public.ai_audit_events for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "ai_audit_events_insert_own_tenant" on public.ai_audit_events;
create policy "ai_audit_events_insert_own_tenant"
  on public.ai_audit_events for insert
  with check (tenant_id = public.current_tenant_id());

-- The retention sweep, and only it. A qualified delete needs the select
-- policy too, the same lesson 00008 learned.
drop policy if exists "ai_audit_events_select_provisioning" on public.ai_audit_events;
create policy "ai_audit_events_select_provisioning"
  on public.ai_audit_events for select
  using (public.is_provisioning());

drop policy if exists "ai_audit_events_delete_provisioning" on public.ai_audit_events;
create policy "ai_audit_events_delete_provisioning"
  on public.ai_audit_events for delete
  using (public.is_provisioning());
