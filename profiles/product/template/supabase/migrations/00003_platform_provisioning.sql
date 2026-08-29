-- Migration: 00003_platform_provisioning
--
-- What the private platform API needs in order to store a tenant, and the
-- policies that let it. Before this, `services/api/koras_api/routers/platform.py`
-- kept tenants in a module-level dict: every tenant the Control Plane created
-- was lost when the process recycled, and the second call about a tenant
-- answered 404 while the first had answered 201.
--
-- The columns come from the create-tenant request in
-- `contracts/product-platform.v1.json` and the contract it points at. Only the
-- parts this side has a use for are stored; `environment` is checked against
-- the service's own and deliberately not kept, because a product database
-- belongs to exactly one environment and a column would invite rows that
-- disagree with the database they are in.

-- ── What the Control Plane names a tenant by ─────────────────────────────────
--
-- Client-supplied and deterministic, which is what makes the create call
-- retryable: the same key names the same tenant, so a retry after a timeout
-- returns the tenant the first attempt made rather than making a second one.
-- The unique constraint is not a nicety here -- it is the thing that decides a
-- concurrent retry, and the API's insert relies on it by name.
--
-- Nullable, because a tenant seeded by hand or by a fixture has no Control
-- Plane behind it. Postgres permits many nulls in a unique index, so those rows
-- coexist without claiming the key.
alter table public.tenants add column if not exists tenant_key text;

create unique index if not exists tenants_tenant_key_key
  on public.tenants (tenant_key);

-- ── Lifecycle ────────────────────────────────────────────────────────────────
--
-- `provisioning` is where a tenant starts: the Control Plane's run has more
-- steps after this one, and a tenant nobody has finished setting up must not
-- look the same as a working one. `suspended` is what rollback produces --
-- never a delete, because the customer may already have data behind it.
--
-- Defaulted to `active` rather than `provisioning` so that rows predating this
-- migration are not all declared half-built. New rows name their status.
alter table public.tenants add column if not exists status text not null default 'active';

alter table public.tenants drop constraint if exists tenants_status_check;
alter table public.tenants add constraint tenants_status_check
  check (status in ('provisioning', 'active', 'suspended'));

-- ── Who this tenant belongs to, on the other side ────────────────────────────
--
-- The Control Plane's organization id. A product needs it to ask what the
-- customer may do -- entitlements are resolved per organization and product,
-- not per tenant -- and the alternative is a second lookup over an identifier
-- the product would then have to store anyway.
--
-- `owner_email` is the address the first administrator was invited at. It is
-- kept because the owner may have no ZITADEL user yet: the Control Plane
-- creates the identity in its own step, and a create that arrives before it
-- would otherwise lose the only thing identifying the person it is for.
--
-- Neither is a credential. Both are references, which is the same line the
-- registration contract draws in the other direction.
alter table public.tenants add column if not exists organization_id uuid;
alter table public.tenants add column if not exists owner_email text;

-- ── The provisioning context ─────────────────────────────────────────────────
--
-- Every policy in 00002 is written as `<column> = public.current_tenant_id()`,
-- which is right for a request made by a tenant's own user and useless for the
-- call that creates the tenant: there is no tenant yet, so the predicate
-- matches nothing and the insert is refused.
--
-- The flag is set by `koras_database.set_provisioning_context`, from one
-- dependency, serving one router, which admits a machine identity only. It is
-- transaction-local, so it cannot outlive a request on a pooled connection, and
-- `set_rls_context` clears it besides.
--
-- `current_setting(..., true)` returns null rather than raising when nothing set
-- it, and null is what makes this false. The same property the tenant helper
-- depends on, for the same reason: were it ever to be true by default, the
-- policies below would admit everyone.
create or replace function public.is_provisioning() returns boolean as $$
  select coalesce(nullif(current_setting('app.provisioning', true), ''), 'off') = 'on';
$$ language sql stable;

-- ── Policies for it ──────────────────────────────────────────────────────────
--
-- Permissive, so these are OR'd with the tenant-scoped ones rather than
-- narrowing them: a tenant's own user keeps exactly the access 00002 gave them,
-- and the provisioning transaction gets a second way in.
--
-- Read is as broad as write on purpose. The create call arrives with a
-- tenant_key and no tenant id, so finding out whether that key already names a
-- tenant is a read across the table -- which is precisely why this is a
-- separate session dependency and not a flag on the tenant one.

drop policy if exists "tenants_select_provisioning" on public.tenants;
create policy "tenants_select_provisioning"
  on public.tenants for select
  using (public.is_provisioning());

drop policy if exists "tenants_insert_provisioning" on public.tenants;
create policy "tenants_insert_provisioning"
  on public.tenants for insert
  with check (public.is_provisioning());

-- Update, for activate and suspend. Both address a tenant by id and neither
-- runs with that tenant's context, so `tenants_update_own` does not reach them.
drop policy if exists "tenants_update_provisioning" on public.tenants;
create policy "tenants_update_provisioning"
  on public.tenants for update
  using (public.is_provisioning())
  with check (public.is_provisioning());

-- The owner's membership row, written in the same transaction as the tenant.
--
-- Insert *and* select, and the select is not decoration. `tenant_store.py`
-- writes this row with `on conflict (tenant_id, user_id) do nothing`, and an
-- `on conflict` that names an arbiter index requires the table's select
-- policies to admit the proposed row -- otherwise the uniqueness check could
-- tell the caller about rows it may not see. Without a select policy the insert
-- is refused with "new row violates row-level security policy", which reads
-- like a `with check` failure and is not one.
--
-- The pair above got this by accident: `tenants` needed a select policy anyway,
-- for the lookup by `tenant_key`, so its identical `on conflict` worked and
-- this one did not. The asymmetry was the bug.
--
-- Dropping the arbiter would be the other way out and is worse: `on conflict do
-- nothing` with no arbiter swallows every unique violation on the table,
-- including ones nobody has thought about. Naming the conflict that is expected
-- is the point of naming it.
--
-- No update or delete. Provisioning creates the first administrator; what
-- happens to a membership afterwards is the tenant's own business.
drop policy if exists "tenant_members_select_provisioning" on public.tenant_members;
create policy "tenant_members_select_provisioning"
  on public.tenant_members for select
  using (public.is_provisioning());

drop policy if exists "tenant_members_insert_provisioning" on public.tenant_members;
create policy "tenant_members_insert_provisioning"
  on public.tenant_members for insert
  with check (public.is_provisioning());
