-- Row-level security policies.
--
-- These are a numbered migration rather than a file in supabase/policies/, and
-- the distinction is not filing. `local/scripts/migrate.sh` used to apply every
-- migration and then every file in that directory, so a policy defined in both
-- places was applied twice with the directory winning.
--
-- On an existing database that is invisible: the directory had already been
-- applied before any corrective migration ran. On a clean bootstrap the
-- sequence inverted -- the corrected policy was created, then overwritten by
-- the older one it was meant to replace. The Control Plane hit exactly this and
-- it restored a cross-organization read (its R-05). The case least likely to be
-- noticed is a fresh database, which is also the one that becomes production.
--
-- A policy is part of the schema and part of its security surface, so it gets
-- what every other schema change gets: an order, a version, and a record of
-- which databases have it. To change one, add a migration that drops and
-- recreates it.
--
-- RLS is enabled on each table by 00001. A table with RLS on and no policy
-- denies every role that cannot bypass it, so the starting position is closed.
--
-- Each policy is dropped before it is created. The ledger in schema_migrations
-- already stops a migration running twice, so this is not what makes the
-- bootstrap safe -- it is here because it is the shape the README asks for when
-- a policy changes, and a file that models the wrong pattern gets copied.

-- tenants: users can only see their own tenant
drop policy if exists "tenants_select_own" on public.tenants;
create policy "tenants_select_own"
  on public.tenants for select
  using (id = public.current_tenant_id());

drop policy if exists "tenants_update_own" on public.tenants;
create policy "tenants_update_own"
  on public.tenants for update
  using (id = public.current_tenant_id());

-- tenant_members: members can see others in their tenant
drop policy if exists "tenant_members_select_own_tenant" on public.tenant_members;
create policy "tenant_members_select_own_tenant"
  on public.tenant_members for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "tenant_members_insert_own_tenant" on public.tenant_members;
create policy "tenant_members_insert_own_tenant"
  on public.tenant_members for insert
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "tenant_members_delete_own_tenant" on public.tenant_members;
create policy "tenant_members_delete_own_tenant"
  on public.tenant_members for delete
  using (tenant_id = public.current_tenant_id());

-- tenant_settings: members can read, only admins can write (enforced in API layer)
drop policy if exists "tenant_settings_select_own_tenant" on public.tenant_settings;
create policy "tenant_settings_select_own_tenant"
  on public.tenant_settings for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "tenant_settings_upsert_own_tenant" on public.tenant_settings;
create policy "tenant_settings_upsert_own_tenant"
  on public.tenant_settings for all
  using (tenant_id = public.current_tenant_id())
  with check (tenant_id = public.current_tenant_id());
