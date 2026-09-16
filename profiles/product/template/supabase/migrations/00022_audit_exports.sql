-- Migration: 00022_audit_exports
-- A record of every audit export: who asked, for what, and what came out.
--
-- An export is the moment audit records leave the product, so the export is
-- itself an event worth keeping -- and keeping it in the same table as the
-- records it copied would be circular. This is its own table.
--
-- **Why not `report_exports`.** That table has exactly the right shape and is
-- the wrong table: it arrives in migration 00014, which the manifest gates on
-- the `reporting` capability, and audit is foundation. A product generated
-- `--without reporting` would have an export route writing to a table it does
-- not have. That is the mistake 00013 made and 2026-09-15 undid; repeating it
-- here would be repeating it knowingly.
--
-- What is reused is the shape rather than the table: a row before the artifact,
-- a background write, a signed URL, and a retirement sweep. Two tables with the
-- same columns is a smaller problem than one table two capabilities fight over.

create table public.audit_exports (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references public.tenants(id) on delete cascade,

  requested_by  text not null,

  -- csv for a spreadsheet, json for a person, ndjson for a pipeline that reads
  -- a line at a time and should not hold the whole export in memory.
  format        text not null check (format in ('csv', 'json', 'ndjson')),

  -- The filters the export was taken with, so that a file handed to an auditor
  -- can be explained six months later. Bound values only; there is no
  -- free-text filter to record.
  filters       jsonb not null default '{}',

  -- pending while it is being written, then one of the other two. The row
  -- exists before the artifact, so an export that dies half way is a `pending`
  -- row somebody can find rather than a request that vanished.
  status        text not null default 'pending'
                check (status in ('pending', 'ready', 'failed')),

  rows_exported integer not null default 0 check (rows_exported >= 0),
  size_bytes    bigint check (size_bytes is null or size_bytes >= 0),

  -- Null until the artifact is written. The object key, not a URL: a signed
  -- URL is a bearer credential and is minted per request, never stored.
  storage_key   text,

  -- A safe sentence for a person. Never a stack and never a provider body.
  error         text,

  -- When the artifact stops being downloadable. An export of audit records is
  -- exactly the kind of file that should not sit in a bucket forever because
  -- somebody clicked once.
  expires_at    timestamptz,

  created_at    timestamptz not null default now(),
  ready_at      timestamptz
);

-- The listing query: this tenant's exports, newest first.
create index audit_exports_tenant_created_idx
  on public.audit_exports (tenant_id, created_at desc);

-- The retirement sweep: what is ready, has an artifact, and has expired.
create index audit_exports_expiry_idx
  on public.audit_exports (expires_at)
  where status = 'ready' and storage_key is not null;

alter table public.audit_exports enable row level security;
alter table public.audit_exports force row level security;

drop policy if exists "audit_exports_select_own_tenant" on public.audit_exports;
create policy "audit_exports_select_own_tenant"
  on public.audit_exports for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "audit_exports_insert_own_tenant" on public.audit_exports;
create policy "audit_exports_insert_own_tenant"
  on public.audit_exports for insert
  with check (tenant_id = public.current_tenant_id());

-- Updatable by the tenant, because the background write that fills in the
-- artifact runs on the tenant's own session -- the same path reporting's
-- exports take.
drop policy if exists "audit_exports_update_own_tenant" on public.audit_exports;
create policy "audit_exports_update_own_tenant"
  on public.audit_exports for update
  using (tenant_id = public.current_tenant_id())
  with check (tenant_id = public.current_tenant_id());

-- Retiring an expired artifact removes its row, and the tenant's own request
-- to retire it runs on their session.
drop policy if exists "audit_exports_delete_own_tenant" on public.audit_exports;
create policy "audit_exports_delete_own_tenant"
  on public.audit_exports for delete
  using (tenant_id = public.current_tenant_id());
