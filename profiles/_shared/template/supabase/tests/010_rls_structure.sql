-- Structural invariants of row-level security.
--
-- These assert things about the schema rather than about data, so they hold
-- for any profile and need no fixtures. They exist because the failure they
-- catch is silent: a table with RLS enabled and no policy, or a policy the
-- connecting role bypasses, behaves exactly like a correctly isolated one
-- right up until it returns another tenant's rows.
--
-- Run with `local/scripts/test-rls.sh`. Any failure raises, so psql with
-- ON_ERROR_STOP=1 exits non-zero.

\set ON_ERROR_STOP on

-- Declared by a schema whose tables carry RLS with no policies on purpose:
-- deny-all is the arrangement, so the checks that assume policies exist are
-- the wrong ones to run. Set here, before the blocks that read it -- the
-- first version set it at the end of the file, where every check had already
-- run without it.
\if :{?deny_all_by_default}
select set_config('koras.deny_all_by_default', 'true', false) as _;
\else
select set_config('koras.deny_all_by_default', 'false', false) as _;
\endif

do $$
declare
  offender text;
begin
  -- Every RLS table forces it -- where policies do the scoping.
  --
  -- Skipped when :deny_all_by_default is set, because a schema with no policies
  -- must NOT force: force binds the owner to policies that do not exist, and
  -- every query returns nothing. See the note in the Control Plane's 00001.
  --
  -- `enable row level security` does not apply to the table's owner, and never
  -- has. The migrations and the application both connect as the owner, so a
  -- policy set that reads as airtight is skipped in its entirety by the one
  -- connection that matters. `force` is what closes that, and its absence is
  -- invisible to any test that connects as a non-owner -- which is every test
  -- anyone writes by hand.
  if not coalesce(nullif(current_setting('koras.deny_all_by_default', true), '')::boolean, false) then
    select string_agg(c.relname, ', ' order by c.relname) into offender
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relkind = 'r'
      and c.relrowsecurity
      and not c.relforcerowsecurity;

    if offender is not null then
      raise exception
        'RLS is enabled but not forced on: %. The table owner bypasses every policy on these tables.',
        offender;
    end if;
  end if;

  -- Every RLS table has at least one policy.
  --
  -- RLS on with no policy denies everyone. That is safe, but it is also what a
  -- half-finished migration looks like, and it presents as an empty screen
  -- rather than as an error.
  select string_agg(c.relname, ', ' order by c.relname) into offender
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public'
    and c.relkind = 'r'
    and c.relrowsecurity
    and not exists (select 1 from pg_policy p where p.polrelid = c.oid);

  if offender is not null then
    -- Deny-all is a legitimate arrangement: RLS on with no policy denies every
    -- role RLS applies to, which is how a schema with no tenant model keeps
    -- everything but its service role out. It is also exactly what a
    -- half-finished migration looks like, so the schema has to say which it
    -- meant rather than the suite guessing.
    if coalesce(nullif(current_setting('koras.deny_all_by_default', true), '')::boolean, false) then
      raise notice 'deny-all by default on: % (declared)', offender;
    else
      raise exception 'RLS is enabled with no policy on: %. Every read returns nothing.', offender;
    end if;
  end if;

  -- Every tenant-scoped table has RLS.
  --
  -- The inverse, and the one that actually leaks: a table carrying a tenant
  -- discriminator and no RLS is readable across tenants by anyone who can
  -- reach the database.
  select string_agg(c.relname, ', ' order by c.relname) into offender
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public'
    and c.relkind = 'r'
    and not c.relrowsecurity
    and exists (
      select 1 from pg_attribute a
      where a.attrelid = c.oid
        and a.attnum > 0
        and not a.attisdropped
        and a.attname in ('tenant_id', 'organization_id')
    );

  if offender is not null then
    raise exception
      'These tables carry a tenant discriminator and no RLS: %. They are readable across tenants.',
      offender;
  end if;

  raise notice 'rls structure: ok';
end
$$;

-- The context helper is null-safe when nothing set it.
--
-- Every policy is written as `<column> = public.current_tenant_id()`. The
-- `true` in `current_setting(..., true)` is what makes an unset GUC null
-- rather than an error, and null is what makes those policies match no row.
-- Were it ever to return a value with no context set, every policy would match
-- somebody.
do $$
begin
  -- Only where there is a tenant to scope to. A schema with no tenant model
  -- defines no such helper, and demanding one would be demanding it invent a
  -- concept it does not have.
  if to_regprocedure('public.current_tenant_id()') is null then
    raise notice 'no current_tenant_id(): this schema scopes no rows by tenant';
    return;
  end if;

  if (select public.current_tenant_id()) is not null then
    raise exception 'current_tenant_id() returns a value with no context set';
  end if;
  raise notice 'rls context helper: ok';
end
$$;

-- The role the application connects as must be one RLS can restrain.
--
-- `force row level security` binds the table *owner* to its policies. It does
-- nothing to a superuser, and nothing to a role holding BYPASSRLS -- both
-- bypass unconditionally, forced or not. Measured against a real database:
--
--     connecting role        force   rows visible
--     superuser              ON      2   <- bypassed
--     non-superuser owner    ON      1   <- isolated
--     non-superuser owner    OFF     2   <- bypassed
--
-- So `force` alone does not give tenant isolation, and a managed Postgres
-- usually offers a superuser as its default connection role. Pass
-- `-v app_role=<role>` to check the role the service actually uses; without it
-- the check is skipped, because this suite is run by a privileged role and
-- cannot infer the application's.
--
-- The name is carried through a setting rather than interpolated into the block
-- below: psql does not substitute its variables inside dollar-quoted strings,
-- so `:'app_role'` there is a syntax error rather than a value.
\if :{?app_role}
select set_config('koras.app_role', :'app_role', false) as _;

do $$
declare
  role_name text := current_setting('koras.app_role');
  is_super boolean;
  bypasses boolean;
begin
  select rolsuper, rolbypassrls into is_super, bypasses
  from pg_roles where rolname = role_name;

  if is_super is null then
    raise exception 'the application role % does not exist', role_name;
  end if;

  if is_super or bypasses then
    raise exception
      'the application role % bypasses RLS (superuser=%, bypassrls=%). Every tenant policy is inert on its connections.',
      role_name, is_super, bypasses;
  end if;

  raise notice 'application role: ok';
end
$$;
\else
\echo 'app_role not supplied - skipping the connecting-role check'
\endif
