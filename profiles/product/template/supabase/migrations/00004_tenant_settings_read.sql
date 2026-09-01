-- Migration: 00004_tenant_settings_read
--
-- What a customer's own request needs before it can read anything.
--
-- Every policy in 00002 is written as `<column> = public.current_tenant_id()`,
-- and `app.tenant_id` is the tenant's primary key. A request arriving from a
-- customer's browser carries none of that: a verified ZITADEL token names an
-- *organization*, and the mapping from that organization to a tenant row lives
-- in the very table the policies are protecting.
--
-- So the first read of any customer request is the one read no policy admits.
-- That is why `services/api` served `health` and the private `platform` router
-- and nothing else, why `resolve_tenant` fabricated a context out of the
-- organization id rather than looking one up, and why -- had anything called
-- `get_db` -- `current_tenant_id()` would have tried to cast a ZITADEL
-- organization id to a uuid and failed. Nothing noticed, because no route
-- existed to notice.
--
-- Two ways out were available. A `security definer` function that looks the
-- tenant up with the policies suspended is the usual one, and it is a
-- privilege escalation kept narrow by convention: nothing stops the next
-- function added beside it from returning more. The other is to give the
-- policies a second key that a request genuinely has, which is what this does.
--
-- The organization id is exactly as trustworthy as the tenant id already is.
-- Both come from a token this service verified against ZITADEL, neither is
-- read from a header, a path or a body, and both are set transaction-locally by
-- the one function allowed to set them. Nothing new is trusted here; a value
-- that was already trusted is simply allowed to select a row.

-- ── The organization a verified caller belongs to ────────────────────────────
--
-- `current_setting(..., true)` returns null rather than raising when nothing
-- set it, and null is what makes the policy below match nothing. That is the
-- same property `current_tenant_id()` depends on and for the same reason: were
-- this ever to default to a value, the policy would admit somebody.
--
-- Text, not uuid. A ZITADEL organization id is a numeric string, and casting it
-- would fail on the value rather than on the absence -- which is a 500 where a
-- clean "no rows" is wanted.
create or replace function public.current_organization_id() returns text as $$
  select nullif(current_setting('app.zitadel_org_id', true), '');
$$ language sql stable;

-- ── The one row that lookup may see ──────────────────────────────────────────
--
-- Permissive, so it is OR'd with `tenants_select_own` rather than narrowing it:
-- a request that already has tenant context keeps exactly the access 00002 gave
-- it, and a request that has only organization context gets one row.
--
-- Select only. This is a lookup, not a session: nothing about holding an
-- organization id should let a caller write. Once the tenant is resolved the
-- request continues under `app.tenant_id` like every other, and the update
-- policies from 00002 are what govern it.
--
-- `zitadel_org_id` is already unique on the table, so this cannot match two
-- rows. If it ever could, the resolver takes no row rather than the first --
-- see `koras_tenant.resolve_tenant`.
drop policy if exists "tenants_select_own_organization" on public.tenants;
create policy "tenants_select_own_organization"
  on public.tenants for select
  using (
    zitadel_org_id is not null
    and zitadel_org_id = public.current_organization_id()
  );

-- ── The settings row, for the same request ───────────────────────────────────
--
-- Deliberately NOT given an organization-keyed policy of its own.
--
-- `tenant_settings_select_own_tenant` from 00002 already admits it, and by then
-- the request has real tenant context because resolving the tenant is what the
-- policy above is for. Adding a second door to the settings row would mean two
-- policies to reason about for one read, and the second would be reachable
-- without the first ever having resolved anything.
--
-- The settings row may legitimately not exist: `tenant_settings` is created by
-- whoever first writes branding, not by provisioning. The API answers with the
-- tenant's name and empty objects in that case, which is the product's own
-- branding and no features -- the correct default, not a missing row to report.
