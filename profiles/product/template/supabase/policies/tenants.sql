-- RLS policies for tenants table
-- Service role bypasses RLS for internal operations

-- tenants: users can only see their own tenant
create policy "tenants_select_own"
  on public.tenants for select
  using (id = public.current_tenant_id());

create policy "tenants_update_own"
  on public.tenants for update
  using (id = public.current_tenant_id());

-- tenant_members: members can see others in their tenant
create policy "tenant_members_select_own_tenant"
  on public.tenant_members for select
  using (tenant_id = public.current_tenant_id());

create policy "tenant_members_insert_own_tenant"
  on public.tenant_members for insert
  with check (tenant_id = public.current_tenant_id());

create policy "tenant_members_delete_own_tenant"
  on public.tenant_members for delete
  using (tenant_id = public.current_tenant_id());

-- tenant_settings: members can read, only admins can write (enforced in API layer)
create policy "tenant_settings_select_own_tenant"
  on public.tenant_settings for select
  using (tenant_id = public.current_tenant_id());

create policy "tenant_settings_upsert_own_tenant"
  on public.tenant_settings for all
  using (tenant_id = public.current_tenant_id())
  with check (tenant_id = public.current_tenant_id());
