-- The organization-keyed lookup, exercised rather than inspected.
--
-- Migration 00004 adds the one policy in this schema that admits a row without
-- tenant context: a request that has only a verified ZITADEL organization id
-- may select the tenant that organization owns, so that the tenant context can
-- be established at all.
--
-- That is a second door into `public.tenants`, and a second door is worth
-- testing in both directions. It must open for exactly one row and it must not
-- become a way to read the table -- which is what it would be if the policy
-- were written `using (true)` when nothing is set, or if the tenant it admits
-- carried its settings along with it.
--
-- Run as a role that is neither superuser nor the table owner, because that is
-- the only role RLS applies to. Everything rolls back.

\set ON_ERROR_STOP on

begin;

-- Seeded as the owner, with a context set so the tenant-scoped policies admit
-- the writes.
set local app.tenant_id = '00000000-0000-0000-0000-000000000011';

insert into public.tenants (id, slug, name, zitadel_org_id, status)
values
  ('00000000-0000-0000-0000-000000000011', 'org-test-alpha', 'Alpha', 'zorg-alpha', 'active'),
  ('00000000-0000-0000-0000-000000000012', 'org-test-beta', 'Beta', 'zorg-beta', 'active'),
  -- A tenant that exists and is switched off. `resolve_tenant` filters on
  -- status, but the policy admits the row -- so this proves the two are
  -- separate decisions rather than one accidentally covering the other.
  ('00000000-0000-0000-0000-000000000013', 'org-test-gone', 'Gone', 'zorg-gone', 'suspended');

insert into public.tenant_settings (tenant_id, branding, features)
values
  ('00000000-0000-0000-0000-000000000011', '{"primaryColor":"#0f766e"}', '{"beta":true}'),
  ('00000000-0000-0000-0000-000000000012', '{"primaryColor":"#b91c1c"}', '{"beta":true}');

set local role koras_rls_test;

do $$
declare
  visible int;
  found_slug text;
begin
  -- ── With no context at all, the table is closed ───────────────────────────
  --
  -- The property everything else rests on. `current_setting(..., true)` returns
  -- null when nothing set it, and null must match nothing -- if this policy
  -- were ever true by default it would admit every caller to every tenant.
  set local app.tenant_id = '';
  set local app.zitadel_org_id = '';

  select count(*) into visible from public.tenants;
  if visible <> 0 then
    raise exception 'tenants: % row(s) visible with no context set', visible;
  end if;

  -- ── An organization id selects exactly its own tenant ─────────────────────
  set local app.zitadel_org_id = 'zorg-alpha';

  select count(*) into visible from public.tenants;
  if visible <> 1 then
    raise exception 'organization lookup: expected 1 row, saw %', visible;
  end if;

  select slug into found_slug from public.tenants;
  if found_slug <> 'org-test-alpha' then
    raise exception 'organization lookup: saw tenant %', found_slug;
  end if;

  -- ── And nobody else's ─────────────────────────────────────────────────────
  select count(*) into visible
  from public.tenants where zitadel_org_id = 'zorg-beta';
  if visible <> 0 then
    raise exception 'organization lookup: another organization''s tenant was visible';
  end if;

  -- ── An unknown organization sees nothing ──────────────────────────────────
  --
  -- A verified token from an organization this product was never provisioned
  -- for. It is a legitimate caller and it has no tenant here.
  set local app.zitadel_org_id = 'zorg-nobody';
  select count(*) into visible from public.tenants;
  if visible <> 0 then
    raise exception 'organization lookup: an unknown organization saw % row(s)', visible;
  end if;

  -- ── A suspended tenant is still only its own row ──────────────────────────
  set local app.zitadel_org_id = 'zorg-gone';
  select count(*) into visible from public.tenants;
  if visible <> 1 then
    raise exception 'organization lookup: suspended tenant saw % row(s)', visible;
  end if;

  -- ── The lookup does not carry the settings row with it ────────────────────
  --
  -- The narrowness that makes the second door safe. `tenant_settings` was
  -- deliberately not given an organization-keyed policy: by the time the
  -- settings are read the request has real tenant context, because resolving
  -- the tenant is what the lookup is for. An organization id alone must reach
  -- no settings at all.
  set local app.zitadel_org_id = 'zorg-alpha';
  select count(*) into visible from public.tenant_settings;
  if visible <> 0 then
    raise exception 'organization lookup: % settings row(s) reachable without a tenant', visible;
  end if;

  -- ── With tenant context, the settings are the caller's own ────────────────
  set local app.zitadel_org_id = '';
  set local app.tenant_id = '00000000-0000-0000-0000-000000000011';

  select count(*) into visible from public.tenant_settings;
  if visible <> 1 then
    raise exception 'tenant_settings: expected 1 visible row, saw %', visible;
  end if;

  select count(*) into visible
  from public.tenant_settings
  where tenant_id = '00000000-0000-0000-0000-000000000012';
  if visible <> 0 then
    raise exception 'tenant_settings: another tenant''s settings were visible';
  end if;

  -- ── Holding an organization id grants no write ────────────────────────────
  --
  -- The lookup policy is select-only. Nothing about knowing which organization
  -- you belong to should let you rename somebody's tenant, and the update
  -- policies from 00002 are keyed on tenant context alone.
  set local app.tenant_id = '';
  set local app.zitadel_org_id = 'zorg-alpha';

  update public.tenants set name = 'Renamed' where zitadel_org_id = 'zorg-alpha';
  get diagnostics visible = row_count;
  if visible <> 0 then
    raise exception 'organization lookup: an update touched % row(s)', visible;
  end if;

  raise notice 'organization lookup: all assertions passed';
end $$;

rollback;
