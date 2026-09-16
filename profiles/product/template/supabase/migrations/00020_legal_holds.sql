-- Migration: 00020_legal_holds
-- A reason to stop retention, and the one thing that outranks every date.
--
-- Retention is a schedule. A hold is a reason to stop the schedule. Until now
-- the schedule always won: the audit sweep deletes by class and age, the object
-- sweep was about to, and neither had anything to consult. A customer in
-- litigation would have watched the evidence expire on time, which is the worst
-- possible moment for a retention policy to work correctly.
--
-- `files.legal_hold` has existed as a boolean since 00018 and nothing read it.
-- That column stays -- it is the per-object flag an operator can set directly --
-- and this table is the record behind it: who asked, who approved, what it
-- covers, and when it stops.
--
-- The scope is deliberately coarse. A hold that has to enumerate the rows it
-- covers is a hold that misses the row written after it was placed, and the row
-- written after it was placed is usually the interesting one.

create table public.legal_holds (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references public.tenants(id) on delete cascade,

  -- What the hold reaches. `tenant` is everything; the other two are for a
  -- matter that concerns one or the other and should not freeze both.
  scope         text not null default 'tenant'
                check (scope in ('tenant', 'files', 'audit')),

  -- Free text for a person to read. Never parsed, never matched against a case
  -- management system this product does not have.
  reason        text not null check (length(reason) between 1 and 2000),

  requested_by  text not null,
  -- Null until somebody approves it. A hold in `requested` holds nothing: a
  -- request that froze data before anyone agreed would be a denial of service
  -- with a legal-sounding name.
  approved_by   text,

  -- requested -> active -> released, or -> expired when its end passes.
  status        text not null default 'requested'
                check (status in ('requested', 'active', 'released', 'expired')),

  starts_at     timestamptz not null default now(),
  -- Null is normal. A hold usually ends when somebody decides it does, not on
  -- a date chosen when nobody knew how long the matter would take.
  ends_at       timestamptz,

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create trigger legal_holds_updated_at
  before update on public.legal_holds
  for each row execute function public.set_updated_at();

-- The sweeps ask one question of this table, per tenant, every night: is
-- anything active right now that covers this scope. This is that query.
create index legal_holds_active_idx
  on public.legal_holds (tenant_id, scope, status)
  where status = 'active';

alter table public.legal_holds enable row level security;
alter table public.legal_holds force row level security;

drop policy if exists "legal_holds_select_own_tenant" on public.legal_holds;
create policy "legal_holds_select_own_tenant"
  on public.legal_holds for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "legal_holds_insert_own_tenant" on public.legal_holds;
create policy "legal_holds_insert_own_tenant"
  on public.legal_holds for insert
  with check (tenant_id = public.current_tenant_id());

-- Updatable, unlike an audit row: approving, releasing and expiring are all
-- updates, and a hold that could not change state could never be lifted. What
-- protects it is that every transition is decided in the API by role and
-- recorded as an administrative audit event, and that a row cannot be moved to
-- another tenant.
drop policy if exists "legal_holds_update_own_tenant" on public.legal_holds;
create policy "legal_holds_update_own_tenant"
  on public.legal_holds for update
  using (tenant_id = public.current_tenant_id())
  with check (tenant_id = public.current_tenant_id());

-- No delete policy for anyone, deliberately. A hold is released, not deleted:
-- the record that data was frozen between two dates is itself evidence, and a
-- hold that can be erased is a hold that can be pretended never to have
-- existed.

-- The sweeps run on the provisioning context and must be able to see every
-- tenant's holds, or they would purge on behalf of a tenant whose hold they
-- could not read. Select only: nothing cross-tenant may create or change one.
drop policy if exists "legal_holds_select_provisioning" on public.legal_holds;
create policy "legal_holds_select_provisioning"
  on public.legal_holds for select
  using (public.is_provisioning());

-- The question both sweeps ask, in one place so that two sweeps cannot answer
-- it differently. `stable` rather than `immutable` because it reads a table and
-- calls now(); it is called once per tenant per sweep, not once per row.
--
-- A hold covers a scope when it is active, has started, and has not ended. The
-- `tenant` scope covers everything, which is why it is named rather than
-- implied by a null.
create or replace function public.under_legal_hold(p_tenant_id uuid, p_scope text)
returns boolean as $$
  select exists (
    select 1
      from public.legal_holds
     where tenant_id = p_tenant_id
       and status = 'active'
       and scope in ('tenant', p_scope)
       and starts_at <= now()
       and (ends_at is null or ends_at > now())
  );
$$ language sql stable;
