-- Migration: 00023_retention_overrides
-- A tenant's own retention, which may be longer than the platform's and never
-- shorter.
--
-- The precedence was decided in ADR 0003 and enforced at one level: the
-- platform floor. A customer with a seven-year regulatory obligation had no way
-- to say so. This is the missing level, and the constraint that makes it safe.
--
-- **Lengthening only, and enforced in three places.** The check constraint
-- below refuses anything under a day; `retention_days_for` takes the greater of
-- the floor and the override, so a smaller override cannot win; and the object
-- sweep's extension statement matches only rows whose date is *below* the
-- resolved floor, so a lowered override can never bring a deletion forward.
-- Three because this is the direction that deletes data, and one guard is one
-- refactor away from none.

alter table public.tenant_settings
  -- Keyed by what is being kept: `audit_activity`, `audit`, `audit_security`,
  -- `storage_standard`, `storage_sensitive`, `storage_restricted`. A map
  -- rather than columns, because the set grows with each classification and a
  -- migration per class would be a migration per policy decision.
  add column if not exists retention_overrides jsonb not null default '{}';

-- Every value must be a whole number of days, and at least one. A tenant that
-- could write a zero could wipe their own history on the next sweep, which is
-- the one thing a retention control must never make easy.
--
-- In a function because a check constraint may not contain a subquery, and
-- validating a map means iterating it. `immutable` is honest here: it reads
-- its argument and nothing else -- `jsonb_each` walks the value it was handed,
-- not a table -- so the same input always gives the same answer.
create or replace function public.retention_overrides_valid(p_overrides jsonb)
returns boolean as $$
  select not exists (
    select 1
      from jsonb_each(p_overrides) as entry(key, value)
     where jsonb_typeof(entry.value) <> 'number'
        or (entry.value)::text::numeric < 1
        or (entry.value)::text::numeric <> floor((entry.value)::text::numeric)
  );
$$ language sql immutable;

alter table public.tenant_settings drop constraint if exists tenant_settings_retention_check;
alter table public.tenant_settings add constraint tenant_settings_retention_check
  check (public.retention_overrides_valid(retention_overrides));

-- The sweeps run on the provisioning context and must read every tenant's
-- override, or a tenant's longer retention would be honoured by the API and
-- ignored by the job that actually deletes. Select only: nothing cross-tenant
-- may change a customer's policy.
drop policy if exists "tenant_settings_select_provisioning" on public.tenant_settings;
create policy "tenant_settings_select_provisioning"
  on public.tenant_settings for select
  using (public.is_provisioning());

-- The resolution rule, in one place so that the API, the audit sweep and the
-- object sweep cannot disagree about how long something is kept.
--
-- `greatest` is the whole policy: a tenant may lengthen and may never shorten.
-- A tenant with no row, no override, or an override for a different kind gets
-- the floor.
create or replace function public.retention_days_for(
  p_tenant_id uuid, p_kind text, p_floor integer
) returns integer as $$
  select greatest(
    p_floor,
    coalesce(
      (select (retention_overrides ->> p_kind)::integer
         from public.tenant_settings
        where tenant_id = p_tenant_id),
      0
    )
  );
$$ language sql stable;
