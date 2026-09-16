-- Migration: 00026_restore_requests
--
-- Restore is destructive, and this table is built around that one fact.
--
-- **Its own state machine, not the assistant's.** ADR 0006 decision 6 said
-- restore would reuse the AI foundation's action machinery. It cannot, and the
-- reason is worth writing down: `ai_actions` arrives with the `ai` capability,
-- which is off by default, so a storage safety operation would have depended on
-- whether the product bought an assistant. `legal_holds` faced the same choice
-- in 00020 and answered it the same way -- borrow the rule, not the machinery.
-- Amended on 2026-09-16.
--
-- **Two people, and the second one is not the first.** The requester proposes;
-- somebody else approves. The rule the assistant applies to a destructive tool
-- and holds apply to a lift, for the same reason: a person who can propose and
-- approve alone is a person with no second pair of eyes.
--
-- **Overwriting is a separate decision, twice.** A restore writes a new object
-- by default, which is not destructive at all. Overwriting an existing one is,
-- so it must be asked for on the request *and* confirmed on the approval --
-- an approver who did not notice a checkbox has not approved a deletion.

create table if not exists public.restore_requests (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references public.tenants (id) on delete cascade,

  -- What is being restored. Not a foreign key, deliberately and for the same
  -- reason `file_backups.file_id` is not one: the object this names has usually
  -- been deleted, which is why somebody is asking for it back.
  file_id       uuid not null,
  -- The catalogue row the bytes will come from, resolved when the request is
  -- made so that a later retirement is visible as a failure rather than as a
  -- silently different source.
  backup_id     uuid not null references public.file_backups (id) on delete restrict,

  reason        text not null check (length(btrim(reason)) between 3 and 2000),
  -- False writes a new object and is not destructive. True replaces one, and
  -- is the only way this table can lose anything.
  overwrite     boolean not null default false,

  requested_by  text not null,
  approved_by   text,
  -- Where the bytes landed. Null until the restore has run; a new file id
  -- unless the request was an overwrite.
  restored_file_id uuid,
  error         text,

  status        text not null default 'requested'
                check (status in ('requested', 'approved', 'restoring',
                                  'completed', 'failed', 'refused')),

  created_at    timestamptz not null default now(),
  approved_at   timestamptz,
  finished_at   timestamptz,
  updated_at    timestamptz not null default now()
);

-- One request in flight per object. A second person asking for the same file
-- while the first request is being approved is a duplicate, not a queue, and
-- two restores racing to write the same object is the one way a non-destructive
-- restore becomes destructive.
create unique index if not exists restore_requests_in_flight_idx
  on public.restore_requests (tenant_id, file_id)
  where status in ('requested', 'approved', 'restoring');

-- The sweep's query: approved and not yet run, across tenants.
create index if not exists restore_requests_approved_idx
  on public.restore_requests (status, approved_at)
  where status = 'approved';

alter table public.restore_requests enable row level security;
alter table public.restore_requests force row level security;

drop policy if exists "restore_requests_select_own_tenant" on public.restore_requests;
create policy "restore_requests_select_own_tenant"
  on public.restore_requests for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "restore_requests_insert_own_tenant" on public.restore_requests;
create policy "restore_requests_insert_own_tenant"
  on public.restore_requests for insert
  with check (tenant_id = public.current_tenant_id());

-- A tenant moves its own request between states; the route decides who may.
-- The database's job here is the tenant boundary, and the two-person rule is
-- not expressible as a policy -- a policy cannot see who requested it and who
-- is asking now in the same predicate without trusting a GUC the API sets,
-- which is the API's check wearing a hat.
drop policy if exists "restore_requests_update_own_tenant" on public.restore_requests;
create policy "restore_requests_update_own_tenant"
  on public.restore_requests for update
  using (tenant_id = public.current_tenant_id())
  with check (tenant_id = public.current_tenant_id());

-- No delete policy for a tenant at all. A restore request is a record of
-- somebody asking for data back, and the request that was refused is exactly
-- the one somebody asks about later.

drop policy if exists "restore_requests_select_provisioning" on public.restore_requests;
create policy "restore_requests_select_provisioning"
  on public.restore_requests for select
  using (public.is_provisioning());

-- The sweep runs an approved request and records what happened. It cannot
-- approve one: `approved` is reachable only through the route, where the
-- second-person rule lives.
drop policy if exists "restore_requests_run_provisioning" on public.restore_requests;
create policy "restore_requests_run_provisioning"
  on public.restore_requests for update
  using (public.is_provisioning() and status in ('approved', 'restoring'))
  with check (public.is_provisioning() and status in ('restoring', 'completed', 'failed'));

drop trigger if exists restore_requests_set_updated_at on public.restore_requests;
create trigger restore_requests_set_updated_at
  before update on public.restore_requests
  for each row execute function public.set_updated_at();

comment on table public.restore_requests is
  'A request to bring an object back from its backup. Two people, its own '
  'state machine rather than the assistant''s, and a refused request is kept '
  'because it is the one somebody asks about later.';
