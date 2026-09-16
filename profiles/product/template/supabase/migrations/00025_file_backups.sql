-- Migration: 00025_file_backups
--
-- The backup catalogue: one row per object that has a copy somewhere else.
--
-- **Why a table and not two columns on `files`.** `files.backup_status` says
-- what the last run concluded about an object that still exists. This says a
-- copy exists, and it has to outlive the row it describes -- a backup whose
-- catalogue entry is deleted along with the object is insurance that expires at
-- the moment of the accident. So a purge removes the `files` row and leaves
-- this one, dated, and the copy goes some days later.
--
-- **`copied` is not `verified`.** A provider acknowledging a copy tells you the
-- request was accepted, not that the bytes match. Only a digest comparison
-- makes it `verified`, and an object neither end can produce a comparable
-- digest for stays `copied` rather than becoming `failed` -- calling that a
-- mismatch would report every large object as corrupt and train whoever reads
-- the console to ignore it. ADR 0006 decisions 1 and 2.

create table if not exists public.file_backups (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references public.tenants (id) on delete cascade,

  -- The object this copies. Deliberately *not* a foreign key: the catalogue
  -- has to survive the object's removal, which is the case it exists for.
  file_id       uuid not null,

  source_key    text not null,
  backup_key    text not null,
  -- The destination as the run saw it, so a catalogue read years later does not
  -- depend on today's settings still pointing at the same bucket.
  destination   text not null,

  size_bytes    bigint,
  -- The two digests the comparison was made from, kept so that a disputed
  -- verification can be re-read rather than re-argued.
  source_digest text,
  backup_digest text,

  status        text not null default 'copied'
                check (status in ('copied', 'verified', 'failed')),
  note          text,

  copied_at     timestamptz not null default now(),
  verified_at   timestamptz,
  -- When the copy itself may go. Null while the object still exists: a copy of
  -- a live object is kept for as long as the object is. It is set when the
  -- object is purged, to that moment plus the backup retention.
  expires_at    timestamptz,

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

-- One catalogue row per object per destination. A second run must update the
-- row it wrote rather than lay a second one beside it, or a re-verified object
-- reads as two backups.
create unique index if not exists file_backups_object_destination_idx
  on public.file_backups (file_id, destination);

-- The two queries that exist: what still needs copying (by tenant), and what
-- has passed its expiry (across tenants, for the sweep).
create index if not exists file_backups_tenant_status_idx
  on public.file_backups (tenant_id, status);
create index if not exists file_backups_expiry_idx
  on public.file_backups (expires_at)
  where expires_at is not null;

-- The selection the backup run makes over `files`: everything ready and not yet
-- copied. Partial, because a product whose objects are all copied should not
-- carry an index over every row to find none of them. The first index this
-- work adds, and 00018 said each would arrive with the sweep that needs it.
create index if not exists files_backup_pending_idx
  on public.files (tenant_id, created_at)
  where status in ('ready', 'archived') and backup_status in ('none', 'failed');

alter table public.file_backups enable row level security;
alter table public.file_backups force row level security;

-- A tenant reads its own catalogue and writes none of it. Every row here is
-- written by a sweep; a tenant that could insert one could claim a backup
-- exists that does not, which is worse than having no catalogue at all.
drop policy if exists "file_backups_select_own_tenant" on public.file_backups;
create policy "file_backups_select_own_tenant"
  on public.file_backups for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "file_backups_select_provisioning" on public.file_backups;
create policy "file_backups_select_provisioning"
  on public.file_backups for select
  using (public.is_provisioning());

drop policy if exists "file_backups_insert_provisioning" on public.file_backups;
create policy "file_backups_insert_provisioning"
  on public.file_backups for insert
  with check (public.is_provisioning());

drop policy if exists "file_backups_update_provisioning" on public.file_backups;
create policy "file_backups_update_provisioning"
  on public.file_backups for update
  using (public.is_provisioning())
  with check (public.is_provisioning());

-- A qualified delete needs a select policy as well as a delete policy, which
-- the provisioning select above supplies. The lesson 00008 records.
drop policy if exists "file_backups_delete_provisioning" on public.file_backups;
create policy "file_backups_delete_provisioning"
  on public.file_backups for delete
  using (public.is_provisioning());

drop trigger if exists file_backups_set_updated_at on public.file_backups;
create trigger file_backups_set_updated_at
  before update on public.file_backups
  for each row execute function public.set_updated_at();

comment on table public.file_backups is
  'One row per object with a copy at a secondary destination. Outlives the '
  'files row it describes, because a catalogue deleted with the object is '
  'insurance that expires at the moment of the accident.';
