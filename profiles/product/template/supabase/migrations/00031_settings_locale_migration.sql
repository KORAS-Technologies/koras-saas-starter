-- Migration: 00031_settings_locale_migration
-- The language preference moves into the settings framework, and stops being
-- stored twice.
--
-- `00017` gave a language choice two homes: `tenant_settings.locale` for the
-- organisation's default and `member_preferences.locale` for a person's own.
-- Both were right, and both are now the framework's `general.language` at
-- exactly those two levels. Leaving the columns would mean two answers to one
-- question, which is the failure `audit_events` had when it sat inside the
-- `reporting` gate: nothing goes red, and a product quietly disagrees with
-- itself.
--
-- ── Why this is a separate migration from 00029 ─────────────────────────────
--
-- `00029` created the tables and nothing read them. This drops two columns
-- that `routers/tenant.py` selects on every signed-in request, so it lands in
-- the same commit as the router that reads the new home instead. Dropping them
-- when the tables arrived would have left a broken read standing between two
-- pieces of work.
--
-- ── What is *not* migrated, deliberately ────────────────────────────────────
--
-- The cookie. `packages/i18n` resolves a request's language from the stored
-- choice, then the cookie, then the tenant default, then `Accept-Language`,
-- then the product's default; the cookie is a fact about a device and is
-- unaffected by where the stored halves live.

-- ── The organisation's default ───────────────────────────────────────────────
--
-- `on conflict do nothing` because `00029`'s snapshot has already written a
-- row for `general.language` for every tenant that existed when it ran -- the
-- definition's default, since the platform had no value. A real choice must
-- win over that default, so the conflict target takes the update rather than
-- being skipped.
--
-- Only rows that hold something. A tenant whose `locale` is null never chose,
-- and writing null over their seeded default would replace a working answer
-- with one the resolver ignores.
insert into public.tenant_setting_values (tenant_id, key, value)
select s.tenant_id, 'general.language', to_jsonb(s.locale)
  from public.tenant_settings s
 where s.locale is not null
on conflict (tenant_id, key) do update set value = excluded.value;

-- ── Each person's own ────────────────────────────────────────────────────────
--
-- No seeded row to collide with -- provisioning writes nothing at the member
-- level, because at provisioning time there are no members -- so this inserts
-- into empty space. The conflict clause is still written, because a migration
-- run twice against one database must not be the thing that fails a deploy.
--
-- `tenant_id` is carried across rather than derived: a person may belong to two
-- tenants of this product and hold a different language in each, which is the
-- property `00017`'s two-key policy exists to preserve.
insert into public.member_setting_values (tenant_id, user_id, key, value)
select p.tenant_id, p.user_id, 'general.language', to_jsonb(p.locale)
  from public.member_preferences p
 where p.locale is not null
on conflict (tenant_id, user_id, key) do update set value = excluded.value;

-- ── The old homes go ─────────────────────────────────────────────────────────
--
-- The column first. `tenant_settings` keeps its other four -- branding,
-- domains, features and the retention overrides -- so the table stays and only
-- the language leaves it.
alter table public.tenant_settings drop column if exists locale;

-- And the table. `member_preferences` held one column and it has just moved;
-- what is left would be a row per person carrying nothing but the fact that
-- they once chose a language. `member_setting_values` is the same shape with
-- the same two-key policies, and keeping both would be two tables for one job
-- with nothing to say which a new preference belongs in.
--
-- The `create table` in `00017` stays where it is, as every migration does.
-- This is the sequence saying the table had a life and it ended, not a claim
-- that it never existed.
drop table if exists public.member_preferences;

-- ── What checks the values now ───────────────────────────────────────────────
--
-- `00017` put a shape constraint on both columns: two lowercase letters, so a
-- row could not hold a sentence whatever route wrote it. The framework refuses
-- more than that and refuses it earlier -- `general.language` is an enum whose
-- options are the catalogues the frontend actually has, checked by `coerce`
-- before a statement is built, so a value outside them never reaches a table.
--
-- The database-level guard that remains is `setting_holds_no_secret`, which is
-- about a different risk. A shape constraint per setting is not available and
-- would not be wanted: it would mean a migration for every definition, which is
-- exactly the property this framework exists to remove.
