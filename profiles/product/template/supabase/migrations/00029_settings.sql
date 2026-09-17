-- Migration: 00029_settings
-- Where a setting's value lives, at each of the three levels that may hold one.
--
-- The framework is described in `docs/SETTINGS_ARCHITECTURE.md` and decided in
-- ADR 0007. What matters here is the split: a *definition* is code -- declared
-- in `koras_settings`, registered at import, refusing a duplicate key or a
-- default outside its own bounds before the process starts -- and a *value* is
-- a row. Nothing in this file knows what settings exist, which is why adding
-- one later is a definition and a translation and no migration at all.
--
-- ── Why three tables and not one with two nullable keys ──────────────────────
--
-- One table with a nullable `tenant_id` and a nullable `user_id` would need a
-- policy reading `tenant_id is null or tenant_id = current_tenant_id()`, and an
-- `or` in a policy is where cross-tenant reads come from. Three narrow tables
-- have three narrow policies, each of which is wrong in only one way and
-- obviously so. The cost is two more `create table` statements.
--
-- ── Why one row per key and not a jsonb document per scope ──────────────────
--
-- `tenant_settings.branding` is a document because branding is read and written
-- whole. Settings are not: a reset is one key, an audit event is one key with
-- one value before and one after, and two administrators saving two categories
-- at the same time must not overwrite each other. A document makes each of
-- those a read-modify-write, and the last of them a lost update.
--
-- ── Why not `organization_settings`, which is what the design said ──────────
--
-- In this schema `organization` already means the ZITADEL organization --
-- `current_organization_id()` returns one, `tenants.zitadel_org_id` holds one,
-- and `00004` exists because the two are not the same key. The customer is a
-- *tenant* in every other table here: `tenant_settings`, `tenant_members`,
-- `tenant_plans`. A table named for the organization and keyed by the tenant
-- would read as the other one on the day somebody is looking for a bug.

-- ── What a setting value may not be ──────────────────────────────────────────
--
-- Secrets never enter this framework. That is a rule in ADR 0007 and rules are
-- what people forget, so it is also a constraint -- the same one
-- `storage_policies` and `ai_policies` carry in the Control Plane, extended to
-- cover the key as well as the value.
--
-- Both halves are needed. A key called `integrations.apiToken` is a credential
-- whatever it holds, and a value `{"secret": "..."}` is one whatever the key is
-- called. `immutable` is honest: it reads its two arguments and no table.
--
-- **The `_?` in `(private|access|api|secret)_?key` is not decoration.** Setting
-- keys here are camelCase after the first segment -- `grid.pageSize`,
-- `files.maxUploadSizeMb` -- so a pattern written only in snake_case catches
-- `access_key` and waves `accessKey` through. It did, until the isolation suite
-- asked it to refuse one.
--
-- `key` on its own is deliberately not a word here. A product with a
-- `shop.sortKey` setting is naming a column, not a credential, and a guard that
-- refuses the honest case is a guard somebody turns off.
create or replace function public.setting_holds_no_secret(p_key text, p_value jsonb)
returns boolean as $$
  select
    p_key !~* '(secret|token|password|passwd|credential|(private|access|api|secret)_?key)'
    and not exists (
      select 1
        from jsonb_each(case when jsonb_typeof(p_value) = 'object' then p_value else '{}'::jsonb end)
             as entry(key, value)
       where entry.key ~* '(secret|token|password|passwd|credential|(private|access|api|secret)_?key)'
    );
$$ language sql immutable;

-- ── The platform's defaults ──────────────────────────────────────────────────
--
-- No tenant column, because there is no tenant. These are what this product
-- ships with once a platform operator has changed them from what the code
-- declares, and they are the third rung of the ladder: a person's value, then
-- the tenant's, then this, then the definition's own default.
--
-- `version` is the monotonic counter the design asks for, kept per row rather
-- than in a table of its own. The current global version is
-- `coalesce(max(version), 0)`, which is what a tenant records having been
-- copied from; keeping it per row also says *which* defaults changed at which
-- version, which a single counter could not.
create table public.global_settings (
  key         text primary key,
  value       jsonb not null,
  version     integer not null,
  updated_at  timestamptz not null default now(),
  constraint global_settings_holds_no_secret
    check (public.setting_holds_no_secret(key, value))
);

alter table public.global_settings enable row level security;
alter table public.global_settings force row level security;

create trigger global_settings_updated_at
  before update on public.global_settings
  for each row execute function public.set_updated_at();

-- Readable by any caller that has declared what it is, and by nothing else.
--
-- Every tenant reads the same rows, deliberately: a platform default is not a
-- customer's data, and a tenant that could not read one would resolve that
-- setting to the code default instead -- the failure mode that looks exactly
-- like everything working. So there is no tenant predicate to write here, and
-- the table has no tenant column for one to reference.
--
-- `using (true)` was the first attempt and was wrong, caught by
-- `rls-policy-ordering.test.ts` on 2026-09-17. The guard's rule is that a
-- policy with no predicate admits everybody, and the useful half of that is
-- true here even though the tenant half is not: `true` also admits a
-- transaction that declared nothing at all. Every other table in this schema
-- fails closed on an undeclared caller, and a table that did not would be the
-- one place a connection opened by mistake still reads something.
--
-- So the predicate is the declaration itself. A customer request has a tenant;
-- the platform router and the worker's sweeps have `app.provisioning`; a
-- transaction that has said neither reads nothing.
drop policy if exists "global_settings_select_declared" on public.global_settings;
create policy "global_settings_select_declared"
  on public.global_settings for select
  using (
    public.current_tenant_id() is not null
    or public.is_provisioning()
  );

-- Written only by the platform, through `PUT /internal/platform/v1/settings/global`,
-- which runs on the provisioning session. A customer request carries tenant
-- context and never `app.provisioning`, so it matches none of these.
drop policy if exists "global_settings_insert_provisioning" on public.global_settings;
create policy "global_settings_insert_provisioning"
  on public.global_settings for insert
  with check (public.is_provisioning());

drop policy if exists "global_settings_update_provisioning" on public.global_settings;
create policy "global_settings_update_provisioning"
  on public.global_settings for update
  using (public.is_provisioning())
  with check (public.is_provisioning());

drop policy if exists "global_settings_delete_provisioning" on public.global_settings;
create policy "global_settings_delete_provisioning"
  on public.global_settings for delete
  using (public.is_provisioning());

-- ── A tenant's own values ────────────────────────────────────────────────────
--
-- Written twice in a tenant's life: once by provisioning, which copies every
-- applicable platform default in, and thereafter by whoever holds
-- `settings.manage`.
--
-- The copy is the whole point of the feature. After it, a platform operator
-- changing a default does not change this tenant -- their row already says
-- what they were given. `00030` records which version it was copied from.
create table public.tenant_setting_values (
  tenant_id   uuid not null references public.tenants(id) on delete cascade,
  key         text not null,
  value       jsonb not null,
  updated_at  timestamptz not null default now(),
  primary key (tenant_id, key),
  constraint tenant_setting_values_holds_no_secret
    check (public.setting_holds_no_secret(key, value))
);

alter table public.tenant_setting_values enable row level security;
alter table public.tenant_setting_values force row level security;

create trigger tenant_setting_values_updated_at
  before update on public.tenant_setting_values
  for each row execute function public.set_updated_at();

drop policy if exists "tenant_setting_values_select_own" on public.tenant_setting_values;
create policy "tenant_setting_values_select_own"
  on public.tenant_setting_values for select
  using (tenant_id = public.current_tenant_id());

drop policy if exists "tenant_setting_values_insert_own" on public.tenant_setting_values;
create policy "tenant_setting_values_insert_own"
  on public.tenant_setting_values for insert
  with check (tenant_id = public.current_tenant_id());

drop policy if exists "tenant_setting_values_update_own" on public.tenant_setting_values;
create policy "tenant_setting_values_update_own"
  on public.tenant_setting_values for update
  using (tenant_id = public.current_tenant_id())
  with check (tenant_id = public.current_tenant_id());

-- **No delete policy for a tenant, and that is the design rather than an
-- omission.** Resetting a tenant setting copies the platform's current value
-- into the row; it does not remove the row. Those are different states: a
-- tenant that has reset holds a value somebody chose to take, and a tenant with
-- no row has never been given one. Deleting would quietly restore the dynamic
-- inheritance the snapshot exists to prevent, because the next read would fall
-- through to whatever the platform holds *now*.

-- Provisioning writes the snapshot and reads it back to confirm what it wrote.
-- Insert and select only: a platform caller may give a tenant their starting
-- values and may never edit them afterwards, which is the boundary
-- `no_direct_writes` draws in the platform contract.
drop policy if exists "tenant_setting_values_select_provisioning" on public.tenant_setting_values;
create policy "tenant_setting_values_select_provisioning"
  on public.tenant_setting_values for select
  using (public.is_provisioning());

drop policy if exists "tenant_setting_values_insert_provisioning" on public.tenant_setting_values;
create policy "tenant_setting_values_insert_provisioning"
  on public.tenant_setting_values for insert
  with check (public.is_provisioning());

-- ── A person's own values ────────────────────────────────────────────────────
--
-- The second table in this schema keyed to the caller as well as the tenant,
-- after `member_preferences` in `00017` -- which this supersedes, and which
-- `00030` migrates and drops. The policies below are that table's, unchanged
-- except for the key: they were right, and the reasoning in `00017`'s own
-- comment applies here word for word.
--
-- Both keys on every verb. On the person alone, somebody who belongs to two
-- tenants of this product would read their value from the wrong one; on the
-- tenant alone, a member would read a colleague's.
create table public.member_setting_values (
  tenant_id   uuid not null references public.tenants(id) on delete cascade,
  user_id     text not null,               -- ZITADEL subject (sub)
  key         text not null,
  value       jsonb not null,
  updated_at  timestamptz not null default now(),
  primary key (tenant_id, user_id, key),
  constraint member_setting_values_holds_no_secret
    check (public.setting_holds_no_secret(key, value))
);

alter table public.member_setting_values enable row level security;
alter table public.member_setting_values force row level security;

create trigger member_setting_values_updated_at
  before update on public.member_setting_values
  for each row execute function public.set_updated_at();

drop policy if exists "member_setting_values_select_own" on public.member_setting_values;
create policy "member_setting_values_select_own"
  on public.member_setting_values for select
  using (
    tenant_id = public.current_tenant_id()
    and user_id = public.current_user_id()
  );

drop policy if exists "member_setting_values_insert_own" on public.member_setting_values;
create policy "member_setting_values_insert_own"
  on public.member_setting_values for insert
  with check (
    tenant_id = public.current_tenant_id()
    and user_id = public.current_user_id()
  );

drop policy if exists "member_setting_values_update_own" on public.member_setting_values;
create policy "member_setting_values_update_own"
  on public.member_setting_values for update
  using (
    tenant_id = public.current_tenant_id()
    and user_id = public.current_user_id()
  )
  with check (
    tenant_id = public.current_tenant_id()
    and user_id = public.current_user_id()
  );

-- **A delete policy here, and none on the tenant table above.** The asymmetry
-- is the difference between the two resets. A person resetting says "stop
-- deciding this for me", and the honest way to store that is to have no row --
-- their organisation's value then answers, and keeps answering as it changes.
-- A tenant resetting says "give me what the platform has today", which is a
-- value, and a value is a row.
drop policy if exists "member_setting_values_delete_own" on public.member_setting_values;
create policy "member_setting_values_delete_own"
  on public.member_setting_values for delete
  using (
    tenant_id = public.current_tenant_id()
    and user_id = public.current_user_id()
  );

-- Provisioning never writes a person's value -- there is no person at
-- provisioning time -- so this table gets no provisioning policy. A platform
-- call sees nothing here, which is the fail-closed property `current_user_id()`
-- being null already gives every policy above.
