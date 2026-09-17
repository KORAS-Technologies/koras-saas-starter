-- A platform default is readable by everyone and writable by nobody.
--
-- The unusual one of the three settings suites, because the property being
-- asserted is not isolation: `global_settings` has no tenant column and every
-- tenant resolves against the same rows. What has to hold is that a customer's
-- request can read them and cannot change them, and that the ability to write
-- belongs to the provisioning context alone.
--
-- Worth a suite of its own precisely because `using (true)` looks like a
-- mistake. If somebody later adds a tenant column here, or narrows the select,
-- this is what says which of those was intended.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-gs-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-gs-beta', 'Beta');

insert into public.global_settings (key, value, version)
values
  ('grid.pageSize', '75'::jsonb, 3),
  ('ui.theme', '"dark"'::jsonb, 3);

-- From here on, act as the application role, as a person in tenant alpha.
set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';
set local app.user_id = 'user-alpha';

do $$
declare
  visible integer;
  seen jsonb;
begin
  -- ── reads: every platform default, for any tenant ────────────────────────
  select count(*) into visible from public.global_settings;
  if visible <> 2 then
    raise exception 'global_settings: expected 2 visible rows, saw %', visible;
  end if;

  select value into seen from public.global_settings where key = 'grid.pageSize';
  if seen <> '75'::jsonb then
    raise exception 'global_settings: read % rather than the platform default', seen;
  end if;

  -- ── writes: none, at all ─────────────────────────────────────────────────
  begin
    insert into public.global_settings (key, value, version)
    values ('grid.rowDensity', '"compact"'::jsonb, 4);
    raise exception 'global_settings: a tenant request inserted a platform default';
  exception
    when insufficient_privilege then null;
  end;

  -- An update the policy refuses matches no row rather than raising: the
  -- `using` clause on the update policy is `is_provisioning()`, and this
  -- request is not. Zero rows changed is the assertion, the same shape
  -- `160_member_preferences_isolation.sql` uses for a colleague's row.
  update public.global_settings set value = '250'::jsonb where key = 'grid.pageSize';
  get diagnostics visible = row_count;
  if visible <> 0 then
    raise exception 'global_settings: a tenant request changed a platform default';
  end if;

  delete from public.global_settings where key = 'ui.theme';
  get diagnostics visible = row_count;
  if visible <> 0 then
    raise exception 'global_settings: a tenant request deleted a platform default';
  end if;

  -- The row is still there and still says what it said.
  select value into seen from public.global_settings where key = 'grid.pageSize';
  if seen <> '75'::jsonb then
    raise exception 'global_settings: the default changed after a refused write';
  end if;

  raise notice 'global settings, read by all and written by none: ok';
end
$$;

-- ── a transaction that declared nothing reads nothing ────────────────────────
--
-- The property the first version of this policy did not have. Every tenant may
-- read every platform default, and a connection that has not said what it is
-- for is not a tenant -- it is a mistake, and the rest of this schema fails
-- closed on one.
--
-- The callers that legitimately hold no tenant -- the worker's sweeps, the
-- platform's own router -- declare `app.provisioning` instead, which the second
-- half of the policy admits and the next block checks.
do $$
declare
  visible integer;
begin
  perform set_config('app.tenant_id', '', true);
  perform set_config('app.user_id', '', true);

  select count(*) into visible from public.global_settings;
  if visible <> 0 then
    raise exception 'global_settings: % rows visible with nothing declared', visible;
  end if;

  raise notice 'global settings, undeclared reads nothing: ok';
end
$$;

-- ── the platform reads them without a tenant, and writes them ────────────────
--
-- The other side of the same policy, and the one the provisioning snapshot
-- depends on: `seed_tenant` reads every platform default on a session that has
-- no tenant, because at that moment the tenant is what is being created.
do $$
declare
  visible integer;
begin
  perform set_config('app.provisioning', 'on', true);

  select count(*) into visible from public.global_settings;
  if visible <> 2 then
    raise exception 'global_settings: % rows visible to provisioning', visible;
  end if;

  insert into public.global_settings (key, value, version)
  values ('ui.density', '"compact"'::jsonb, 4);

  update public.global_settings set value = '100'::jsonb where key = 'grid.pageSize';
  get diagnostics visible = row_count;
  if visible <> 1 then
    raise exception 'global_settings: provisioning could not change a platform default';
  end if;

  perform set_config('app.provisioning', '', true);

  raise notice 'global settings, written by the platform alone: ok';
end
$$;

-- ── the secret guard holds whoever writes ────────────────────────────────────
--
-- Asserted as the owner, after `reset role`, because this is a constraint
-- rather than a policy: the point is that even the connection that runs the
-- migrations cannot store a credential here.
reset role;

do $$
begin
  begin
    insert into public.global_settings (key, value, version)
    values ('integrations.apiToken', '"not-a-real-one"'::jsonb, 4);
    raise exception 'global_settings: a credential-shaped key was accepted';
  exception
    when check_violation then null;
  end;

  begin
    insert into public.global_settings (key, value, version)
    values ('integrations.webhook', '{"secret": "shh"}'::jsonb, 4);
    raise exception 'global_settings: a value holding a secret was accepted';
  exception
    when check_violation then null;
  end;

  raise notice 'global settings, secrets refused by the database: ok';
end
$$;

rollback;
