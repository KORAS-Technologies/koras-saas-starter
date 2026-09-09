-- Migration: 00005_files
-- What a tenant has put into the product's object store, by name.
--
-- The bytes are never here. They live with the storage provider the Control
-- Plane's policy names for this customer -- Supabase Storage by default, a
-- bucket of their own where staff have set one -- and this table is the index
-- a page can list, sort and count without touching the bucket at all. A row
-- and an object are created in that order and deleted in the reverse, so a
-- row without an object is a `pending` upload that never finished, and an
-- object without a row is a leak the reconciliation sweep can find.
--
-- Scoped like everything else: `tenant_id` and the same three policies as
-- `tenant_settings`, forced so the owner cannot skip them either. `uploaded_by`
-- is the ZITADEL subject, as `tenant_members.user_id` is, and is informational
-- -- who may delete is decided by the caller's role, not by who uploaded.

create table public.files (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references public.tenants(id) on delete cascade,
  -- The object key in the bucket. Chosen by the API, never by the browser:
  -- tenants/<tenant>/<file id>/<name>, so a key can be read back to its owner
  -- and two tenants can upload the same name without meeting.
  storage_key   text not null unique,
  name          text not null,
  size_bytes    bigint not null check (size_bytes >= 0),
  content_type  text not null default 'application/octet-stream',
  -- pending: a signed upload URL was issued and nothing has confirmed the
  -- object exists. ready: the API checked the object and it is what was
  -- promised. Only ready rows are listed or downloadable.
  status        text not null default 'pending' check (status in ('pending', 'ready')),
  uploaded_by   text not null,
  created_at    timestamptz not null default now(),
  ready_at      timestamptz
);

create index files_tenant_ready_idx on public.files (tenant_id, created_at desc)
  where status = 'ready';

alter table public.files enable row level security;
alter table public.files force row level security;

drop policy if exists "files_select_own_tenant" on public.files;
create policy "files_select_own_tenant"
  on public.files for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "files_insert_own_tenant" on public.files;
create policy "files_insert_own_tenant"
  on public.files for insert
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "files_update_own_tenant" on public.files;
create policy "files_update_own_tenant"
  on public.files for update
  using (tenant_id = public.current_tenant_id())
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "files_delete_own_tenant" on public.files;
create policy "files_delete_own_tenant"
  on public.files for delete
  using (tenant_id = public.current_tenant_id());
