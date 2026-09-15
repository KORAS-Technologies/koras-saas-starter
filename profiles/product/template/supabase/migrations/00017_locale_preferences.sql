-- Migration: 00017_locale_preferences
-- Where a language choice is kept, once it is more than a cookie.
--
-- Phase 1 of the language work (FOLLOW_UPS F20) resolved the locale from a
-- cookie, the browser's Accept-Language and the product's default -- which is
-- a choice about *this device*. This gives it two more places to live:
--
--   member_preferences.locale   what this person chose, on any device
--   tenant_settings.locale      what this organisation's members see before
--                               they choose anything
--
-- ── Why a table of its own, and not a column on tenant_members ──────────────
--
-- `tenant_members` is written by provisioning for the owner and by nothing
-- else: a member who signed in through the organisation's identity provider
-- has no row there, so a preference stored on it would exist for one person
-- per tenant. And that table carries `role`. A policy letting a member update
-- their own row would be a policy letting them update their own role unless
-- something else stopped it, and a trigger guarding a column is a second thing
-- to keep right for a row that should never have been writable by its subject.
-- A table that holds preferences and nothing a policy protects is the simpler
-- shape: everything on it may be written by the person it is about.
--
-- ── The first policy keyed to the caller, not the tenant ─────────────────────
--
-- `current_user_id()` has existed since 00001 and nothing read it: every policy
-- scoped rows to a tenant, and the API set `app.tenant_id` alone. This is the
-- first row a person may write and another person in the same tenant may not
-- even read, so the request now declares who is asking as well as which tenant
-- (`koras_tenant.Tenant.user_id`), and the policy below checks both. Same
-- trust as the tenant id: the subject comes from a token this service verified,
-- is set transaction-locally by the one function allowed to set it, and is
-- never read from a header, a path or a body.
--
-- Both keys, always. A policy on the user alone would let a subject who is a
-- member of two tenants of this product read their preference from the wrong
-- one; a policy on the tenant alone would let a member read a colleague's.
--
-- ── The value ────────────────────────────────────────────────────────────────
--
-- Two lowercase letters, checked here as well as in the API. The API refuses
-- anything outside the catalogues it knows; the constraint refuses anything
-- that is not the shape of a language tag at all, so a row cannot hold a
-- sentence or a script whatever route wrote it. The browser tier validates
-- again, against the list the product *offers*, before the value reaches
-- `lang` -- a catalogue can exist without being offered.

-- ── The organisation's default ───────────────────────────────────────────────
alter table public.tenant_settings
  add column locale text
  constraint tenant_settings_locale_shape check (locale is null or locale ~ '^[a-z]{2}$');

-- Written under the existing `tenant_settings_upsert_own_tenant` policy from
-- 00002, which admits any caller with the tenant's context. Who among them
-- may set a default -- `settings.manage`, owners and administrators -- is the
-- API's decision, the same division 00002's own comment records.

-- ── The person's choice ──────────────────────────────────────────────────────
create table public.member_preferences (
  tenant_id   uuid not null references public.tenants(id) on delete cascade,
  user_id     text not null,                -- ZITADEL subject (sub)
  locale      text
    constraint member_preferences_locale_shape check (locale is null or locale ~ '^[a-z]{2}$'),
  updated_at  timestamptz not null default now(),
  primary key (tenant_id, user_id)
);

alter table public.member_preferences enable row level security;
alter table public.member_preferences force row level security;

create trigger member_preferences_updated_at
  before update on public.member_preferences
  for each row execute function public.set_updated_at();

-- One policy per verb rather than `for all`, because the four are read
-- differently by a reviewer: the select says who may know a preference, the
-- insert and update say who may set one, and the absence of a delete says a
-- preference is cleared by setting it null rather than by removing the row.
--
-- `current_user_id()` is null on a request that did not declare a subject --
-- the worker, a platform call -- and null compared to anything is not true, so
-- such a request sees and writes nothing here. That is the same fail-closed
-- property the tenant policies rely on.
drop policy if exists "member_preferences_select_own" on public.member_preferences;
create policy "member_preferences_select_own"
  on public.member_preferences for select
  using (
    tenant_id = public.current_tenant_id()
    and user_id = public.current_user_id()
  );

drop policy if exists "member_preferences_insert_own" on public.member_preferences;
create policy "member_preferences_insert_own"
  on public.member_preferences for insert
  with check (
    tenant_id = public.current_tenant_id()
    and user_id = public.current_user_id()
  );

drop policy if exists "member_preferences_update_own" on public.member_preferences;
create policy "member_preferences_update_own"
  on public.member_preferences for update
  using (
    tenant_id = public.current_tenant_id()
    and user_id = public.current_user_id()
  )
  with check (
    tenant_id = public.current_tenant_id()
    and user_id = public.current_user_id()
  );
