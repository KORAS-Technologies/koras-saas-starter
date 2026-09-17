-- Migration: 00030_settings_snapshot
-- What a tenant was given, when, and out of which platform defaults.
--
-- `00029` created the row a tenant's settings live in. This records where that
-- row came from, which is the difference between a snapshot and a copy nobody
-- can account for.
--
-- ── Why this is on `tenants` and not a table of its own ─────────────────────
--
-- Three columns written once, read rarely, and meaningless without the tenant
-- they describe. A table would be a join for every read of a fact that is
-- one-to-one with a row that already exists. `tenants` already carries
-- provenance of exactly this shape -- `tenant_key` is who asked for it and
-- `organization_id` is on whose behalf.
--
-- ── What the version is ─────────────────────────────────────────────────────
--
-- `coalesce(max(version), 0)` over `global_settings` at the moment the copy was
-- taken. Zero is a real answer and the commonest one in a new estate: it means
-- no platform operator had changed anything, so the tenant was seeded from the
-- definitions' own defaults.
--
-- Nothing reads it to make a decision, deliberately. ADR 0007 decision 10: the
-- architecture has to permit an operator later asking "which tenants were set
-- up from defaults older than this one", and answering that needs the number
-- recorded at the time. Acting on the answer -- pushing a newer default into
-- tenants that already exist -- is a separate decision with a customer-visible
-- blast radius, and it is not taken here.

alter table public.tenants
  -- Null means the tenant predates this framework. Not zero: a tenant seeded
  -- from version 0 and a tenant never seeded at all are different, and only one
  -- of them has a full set of rows in `tenant_setting_values`. A backfill that
  -- could not tell them apart would skip the ones that need it.
  add column if not exists settings_global_version integer,
  add column if not exists settings_copied_at timestamptz,
  -- Who or what took the copy. In practice the string `provisioning`, because
  -- the only caller is the platform's create; a column rather than a constant
  -- so that a later backfill, or a repair run by a person, says so.
  add column if not exists settings_copied_by text;

-- No index. These are read when somebody asks about one tenant, or in a full
-- scan when somebody asks about all of them, and an index earning its keep on
-- neither is an index that only costs writes.
