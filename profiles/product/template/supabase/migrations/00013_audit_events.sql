-- Audit: what people did in this product, durable, per tenant.
--
-- `koras_audit` has named the shape since the AI foundation -- an action, an
-- actor, a tenant, a target, an outcome, and a small detail map that refuses
-- anything named like a secret -- and the assistant kept its own copy in
-- `ai_audit_events`. Reporting was the first module outside the assistant
-- with something to record: an export that left the product, a report about
-- people that was opened. This is the general table, the second durable
-- implementation of the same sink, and where every later module records.
--
-- It shipped inside the `reporting` capability and is foundation as of
-- 2026-09-15, because a table every module records to cannot be removable by
-- one of them: a product generated without reporting had nowhere to record.
--
-- The same shape and the same rules as 00009: a tenant column, RLS enabled
-- and forced, insert and select for the tenant, no update and no delete for
-- anyone the policies apply to, and the retention sweep on the provisioning
-- context admitted to delete and nothing else. An audit row that can be
-- edited is not an audit row.

create table public.audit_events (
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

create index audit_events_tenant_time_idx
  on public.audit_events (tenant_id, created_at desc);

-- The Activity report groups by action within a range; the first index
-- serves the range and this one the breakdown.
create index audit_events_tenant_action_idx
  on public.audit_events (tenant_id, action, created_at desc);

alter table public.audit_events enable row level security;
alter table public.audit_events force row level security;

drop policy if exists "audit_events_select_own_tenant" on public.audit_events;
create policy "audit_events_select_own_tenant"
  on public.audit_events for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "audit_events_insert_own_tenant" on public.audit_events;
create policy "audit_events_insert_own_tenant"
  on public.audit_events for insert
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "audit_events_select_provisioning" on public.audit_events;
create policy "audit_events_select_provisioning"
  on public.audit_events for select
  using (public.is_provisioning());

drop policy if exists "audit_events_delete_provisioning" on public.audit_events;
create policy "audit_events_delete_provisioning"
  on public.audit_events for delete
  using (public.is_provisioning());
