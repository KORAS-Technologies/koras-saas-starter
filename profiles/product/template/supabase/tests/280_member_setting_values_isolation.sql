-- A person's setting belongs to that person in that tenant, and to nobody else.
--
-- The successor to `160_member_preferences_isolation.sql`, which asserted the
-- same two sentences about one column. The table it guarded holds every
-- personal setting now rather than a language alone, and migration `00031`
-- moves the rows and drops it -- so the assertions move here, keyed the same
-- way and failing closed in the same place.
--
-- Two tenants and three people. The second person in alpha is the case a
-- tenant-only policy gets wrong, and the delete is the case the tenant table
-- deliberately does not have: a person resetting means "stop deciding this for
-- me", and the honest way to store that is to hold no row.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-msv-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-msv-beta', 'Beta');

insert into public.member_setting_values (tenant_id, user_id, key, value)
values
  ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'grid.pageSize', '25'::jsonb),
  ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'ui.theme', '"dark"'::jsonb),
  ('00000000-0000-0000-0000-000000000001', 'user-alpha-colleague', 'grid.pageSize', '10'::jsonb),
  ('00000000-0000-0000-0000-000000000002', 'user-beta', 'grid.pageSize', '250'::jsonb);

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';
set local app.user_id = 'user-alpha';

do $$
declare
  visible integer;
  seen jsonb;
begin
  -- ── reads: my rows, and only mine ────────────────────────────────────────
  select count(*) into visible from public.member_setting_values;
  if visible <> 2 then
    raise exception 'member_setting_values: expected 2 visible rows, saw %', visible;
  end if;

  select value into seen from public.member_setting_values where key = 'grid.pageSize';
  if seen <> '25'::jsonb then
    raise exception 'member_setting_values: read somebody else''s value (%)', seen;
  end if;

  select count(*) into visible
  from public.member_setting_values where user_id = 'user-alpha-colleague';
  if visible <> 0 then
    raise exception 'member_setting_values: a colleague''s row in the same tenant was visible';
  end if;

  select count(*) into visible
  from public.member_setting_values
  where tenant_id = '00000000-0000-0000-0000-000000000002';
  if visible <> 0 then
    raise exception 'member_setting_values: another tenant''s row was visible';
  end if;

  -- ── writes: my rows, and only mine ───────────────────────────────────────
  update public.member_setting_values set value = '100'::jsonb where key = 'grid.pageSize';
  select value into seen from public.member_setting_values where key = 'grid.pageSize';
  if seen <> '100'::jsonb then
    raise exception 'member_setting_values: could not update my own value';
  end if;

  update public.member_setting_values set value = '500'::jsonb
   where user_id = 'user-alpha-colleague';
  get diagnostics visible = row_count;
  if visible <> 0 then
    raise exception 'member_setting_values: a colleague''s value was updated';
  end if;

  begin
    insert into public.member_setting_values (tenant_id, user_id, key, value)
    values ('00000000-0000-0000-0000-000000000001', 'user-alpha-newcomer',
            'ui.theme', '"light"'::jsonb);
    raise exception 'member_setting_values: a row was inserted for another person';
  exception
    when insufficient_privilege then null;
  end;

  begin
    insert into public.member_setting_values (tenant_id, user_id, key, value)
    values ('00000000-0000-0000-0000-000000000002', 'user-alpha',
            'ui.theme', '"light"'::jsonb);
    raise exception 'member_setting_values: a row was inserted into another tenant';
  exception
    when insufficient_privilege then null;
  end;

  -- The upsert the API issues for a person's own value.
  insert into public.member_setting_values (tenant_id, user_id, key, value)
  values ('00000000-0000-0000-0000-000000000001', 'user-alpha',
          'ui.density', '"compact"'::jsonb)
  on conflict (tenant_id, user_id, key) do update set value = excluded.value;
  select value into seen from public.member_setting_values where key = 'ui.density';
  if seen <> '"compact"'::jsonb then
    raise exception 'member_setting_values: the upsert did not store the value';
  end if;

  -- ── deletes: my own, which is what a reset is ────────────────────────────
  delete from public.member_setting_values where key = 'ui.density';
  select count(*) into visible from public.member_setting_values where key = 'ui.density';
  if visible <> 0 then
    raise exception 'member_setting_values: could not clear my own value';
  end if;

  delete from public.member_setting_values where user_id = 'user-alpha-colleague';
  get diagnostics visible = row_count;
  if visible <> 0 then
    raise exception 'member_setting_values: a colleague''s value was deleted';
  end if;

  raise notice 'member setting values, one person one row per key: ok';
end
$$;

-- ── no subject, no rows ──────────────────────────────────────────────────────
--
-- A request that declared a tenant and no person -- the worker, the platform's
-- collector -- sees no personal value and can write none. The tenant is still
-- set, which is what makes this the interesting case: the tenant policies alone
-- would admit every row in alpha.
do $$
declare
  visible integer;
begin
  perform set_config('app.user_id', '', true);

  select count(*) into visible from public.member_setting_values;
  if visible <> 0 then
    raise exception 'member_setting_values: % rows visible with no subject declared', visible;
  end if;

  begin
    insert into public.member_setting_values (tenant_id, user_id, key, value)
    values ('00000000-0000-0000-0000-000000000001', 'user-alpha',
            'ui.theme', '"light"'::jsonb);
    raise exception 'member_setting_values: a row was written with no subject declared';
  exception
    when insufficient_privilege then null;
  end;

  raise notice 'member setting values, no subject fails closed: ok';
end
$$;

-- ── the secret guard ─────────────────────────────────────────────────────────
reset role;

do $$
begin
  begin
    insert into public.member_setting_values (tenant_id, user_id, key, value)
    values ('00000000-0000-0000-0000-000000000001', 'user-alpha',
            'integrations.accessKey', '"not-a-real-one"'::jsonb);
    raise exception 'member_setting_values: a credential-shaped key was accepted';
  exception
    when check_violation then null;
  end;

  raise notice 'member setting values, secrets refused by the database: ok';
end
$$;

rollback;
