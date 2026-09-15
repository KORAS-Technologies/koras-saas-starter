-- Reporting's two runtime tables: what a customer asked to have delivered,
-- and what the API produced in the background.
--
-- Report and metric definitions are code and have no table. These are the
-- two things that are state: a schedule a person created, which the worker
-- reads across tenants on the provisioning context to deliver; and an
-- export too large to answer in a request, which the API writes into the
-- tenant's bucket after the response and the customer downloads later.
--
-- The same shape as every tenant table -- a tenant column, RLS enabled and
-- forced, a policy per verb on the tenant helper. The worker, on the
-- provisioning context, may read every schedule and record a run on it,
-- and nothing else: it cannot create one, and it cannot see an export.

create table public.report_schedules (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references public.tenants(id) on delete cascade,
  report_key    text not null,
  cadence       text not null check (cadence in ('daily', 'weekly', 'monthly')),
  format        text not null default 'csv' check (format in ('csv', 'xlsx', 'pdf')),
  -- Addresses the report goes to. The API bounds the count and the shape.
  recipients    text[] not null check (array_length(recipients, 1) between 1 and 10),
  -- The report's declared filters other than the period, which the cadence
  -- decides. Choice and integer values only; the API validated them against
  -- the definition before writing.
  filters       jsonb not null default '{}',
  created_by    text not null,
  active        boolean not null default true,
  next_run_at   timestamptz not null,
  last_run_at   timestamptz,
  last_error    text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index report_schedules_due_idx
  on public.report_schedules (next_run_at) where active;
create index report_schedules_tenant_report_idx
  on public.report_schedules (tenant_id, report_key);

create trigger report_schedules_updated_at
  before update on public.report_schedules
  for each row execute function public.set_updated_at();

alter table public.report_schedules enable row level security;
alter table public.report_schedules force row level security;

drop policy if exists "report_schedules_select_own_tenant" on public.report_schedules;
create policy "report_schedules_select_own_tenant"
  on public.report_schedules for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "report_schedules_insert_own_tenant" on public.report_schedules;
create policy "report_schedules_insert_own_tenant"
  on public.report_schedules for insert
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "report_schedules_update_own_tenant" on public.report_schedules;
create policy "report_schedules_update_own_tenant"
  on public.report_schedules for update
  using (tenant_id = public.current_tenant_id())
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "report_schedules_delete_own_tenant" on public.report_schedules;
create policy "report_schedules_delete_own_tenant"
  on public.report_schedules for delete
  using (tenant_id = public.current_tenant_id());

-- The worker: read what is due, record the run. Select and update only.
drop policy if exists "report_schedules_select_provisioning" on public.report_schedules;
create policy "report_schedules_select_provisioning"
  on public.report_schedules for select
  using (public.is_provisioning());

drop policy if exists "report_schedules_update_provisioning" on public.report_schedules;
create policy "report_schedules_update_provisioning"
  on public.report_schedules for update
  using (public.is_provisioning())
  with check (public.is_provisioning());

create table public.report_exports (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references public.tenants(id) on delete cascade,
  report_key    text not null,
  format        text not null check (format in ('csv', 'xlsx', 'pdf')),
  filters       jsonb not null default '{}',
  status        text not null default 'pending' check (status in ('pending', 'ready', 'failed')),
  -- tenants/<tenant>/exports/<id>/<filename>, in the tenant's bucket. Set
  -- when the object is there; the row exists before the object, so a row
  -- with no key is an export still being written or one that failed.
  storage_key   text,
  filename      text not null,
  size_bytes    bigint check (size_bytes is null or size_bytes >= 0),
  rows          integer not null default 0 check (rows >= 0),
  error         text,
  requested_by  text not null,
  created_at    timestamptz not null default now(),
  ready_at      timestamptz
);

create index report_exports_tenant_created_idx
  on public.report_exports (tenant_id, created_at desc);

alter table public.report_exports enable row level security;
alter table public.report_exports force row level security;

drop policy if exists "report_exports_select_own_tenant" on public.report_exports;
create policy "report_exports_select_own_tenant"
  on public.report_exports for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "report_exports_insert_own_tenant" on public.report_exports;
create policy "report_exports_insert_own_tenant"
  on public.report_exports for insert
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "report_exports_update_own_tenant" on public.report_exports;
create policy "report_exports_update_own_tenant"
  on public.report_exports for update
  using (tenant_id = public.current_tenant_id())
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "report_exports_delete_own_tenant" on public.report_exports;
create policy "report_exports_delete_own_tenant"
  on public.report_exports for delete
  using (tenant_id = public.current_tenant_id());
