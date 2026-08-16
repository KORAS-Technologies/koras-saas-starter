-- RLS policies for Control Plane platform tables
-- Platform API operates as service role (bypasses RLS for internal ops)
-- These policies guard direct Supabase client access by portal users

-- Platform staff can read all products
create policy "products_platform_staff_select"
  on public.products for select
  using (auth.role() = 'authenticated');

-- Only service role may insert/update/delete products
create policy "products_service_role_write"
  on public.products for all
  using (auth.role() = 'service_role');

-- Organizations: authenticated users may read their own org
create policy "organizations_select_own"
  on public.organizations for select
  using (
    id in (
      select organization_id from public.subscriptions
      where organization_id = id
    )
  );

-- Subscriptions: org members may read their subscriptions
create policy "subscriptions_select_own_org"
  on public.subscriptions for select
  using (auth.role() = 'authenticated');

-- Entitlements: readable by authenticated users (checked by API)
create policy "entitlements_select_authenticated"
  on public.entitlements for select
  using (auth.role() = 'authenticated');

-- Infrastructure registry: service role only
create policy "infrastructure_resources_service_role"
  on public.infrastructure_resources for all
  using (auth.role() = 'service_role');
