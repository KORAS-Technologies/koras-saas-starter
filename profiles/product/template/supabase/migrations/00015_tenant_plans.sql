-- Migration: 00015_tenant_plans
-- The plan as the platform last resolved it, per tenant.
--
-- A customer's request resolves the plan live, with the customer's own
-- token, and that is still what every page and every route reads. What
-- had no token was the worker: a scheduled report is delivered at six in
-- the morning with nobody signed in, so until now it delivered with the
-- plan unresolved, and a schedule made on Business kept arriving after the
-- customer moved to Starter.
--
-- The product holds no identity toward the platform by decision, so it
-- cannot ask. The platform holds one toward every product, so it tells:
-- its worker resolves each organization's effective entitlements for this
-- product hourly and writes them here through the private contract
-- (`PUT /internal/platform/v1/tenants/{id}/plan`). One row per tenant,
-- replaced on every sync; `synced_at` says how old the answer is.
--
-- Read by the tenant and by the worker on the tenant's context, written
-- by the provisioning context and nothing else. Never a substitute for
-- the live read where a token exists.

create table public.tenant_plans (
  tenant_id       uuid primary key references public.tenants(id) on delete cascade,
  plan_code       text,
  status          text,
  -- {"reporting.export": {"enabled": true, "limit": null}, ...}: the codes
  -- the platform resolved, each with whether it is on and its limit.
  entitlements    jsonb not null default '{}',
  trial_ends_at   timestamptz,
  period_ends_at  timestamptz,
  synced_at       timestamptz not null default now()
);

alter table public.tenant_plans enable row level security;
alter table public.tenant_plans force row level security;

drop policy if exists "tenant_plans_select_own_tenant" on public.tenant_plans;
create policy "tenant_plans_select_own_tenant"
  on public.tenant_plans for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "tenant_plans_select_provisioning" on public.tenant_plans;
create policy "tenant_plans_select_provisioning"
  on public.tenant_plans for select
  using (public.is_provisioning());

drop policy if exists "tenant_plans_insert_provisioning" on public.tenant_plans;
create policy "tenant_plans_insert_provisioning"
  on public.tenant_plans for insert
  with check (public.is_provisioning());

drop policy if exists "tenant_plans_update_provisioning" on public.tenant_plans;
create policy "tenant_plans_update_provisioning"
  on public.tenant_plans for update
  using (public.is_provisioning())
  with check (public.is_provisioning());
