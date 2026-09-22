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

  -- ── moves: a row may not be carried to another person or tenant ─────────
  --
  -- **SET-22.** Both `with check` clauses on this table's update policy were
  -- correct and entirely unexercised: every assertion above asks whether a row
  -- can be read or written where it is, none whether it can be made to belong
  -- to somebody else. Removing them left this suite green, which was
  -- demonstrated before this was written.
  --
  -- Two moves, because the policy names two keys and a test naming one would
  -- pass with the other clause deleted.
  begin
    update public.member_setting_values
       set user_id = 'user-alpha-colleague'
     where key = 'grid.pageSize' and user_id = 'user-alpha';
    raise exception 'member_setting_values: a row was moved onto a colleague';
  exception
    when insufficient_privilege then null;
  end;

  begin
    update public.member_setting_values
       set tenant_id = '00000000-0000-0000-0000-000000000002'
     where key = 'grid.pageSize' and user_id = 'user-alpha';
    raise exception 'member_setting_values: a row was moved into another tenant';
  exception
    when insufficient_privilege then null;
  end;

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

  -- ── the four the guard used to let through ────────────────────────────────
  --
  -- Every one of these was stored by the shipped guard, which read the
  -- top-level members of an object and nothing else. Found by the first
  -- independent review of this framework on 2026-09-19 and fixed in `00033`.
  -- Asserted here because a suite that only tests what the guard already
  -- catches will keep passing while the guard is wrong -- which is exactly
  -- what happened.
  begin
    insert into public.member_setting_values (tenant_id, user_id, key, value)
    values ('00000000-0000-0000-0000-000000000001', 'user-alpha',
            'integrations.config', '{"auth": {"token": "not-a-real-one"}}'::jsonb);
    raise exception 'member_setting_values: a nested credential was accepted';
  exception
    when check_violation then null;
  end;

  begin
    insert into public.member_setting_values (tenant_id, user_id, key, value)
    values ('00000000-0000-0000-0000-000000000001', 'user-alpha',
            'integrations.config', '[{"secret": "not-a-real-one"}]'::jsonb);
    raise exception 'member_setting_values: a credential inside an array was accepted';
  exception
    when check_violation then null;
  end;

  begin
    insert into public.member_setting_values (tenant_id, user_id, key, value)
    values ('00000000-0000-0000-0000-000000000001', 'user-alpha',
            'integrations.config',
            '{"a": [{"b": {"apiKey": "not-a-real-one"}}]}'::jsonb);
    raise exception 'member_setting_values: a credential three levels down was accepted';
  exception
    when check_violation then null;
  end;

  begin
    insert into public.member_setting_values (tenant_id, user_id, key, value)
    values ('00000000-0000-0000-0000-000000000001', 'user-alpha',
            'integrations.webhookSigningKey', '"not-a-real-one"'::jsonb);
    raise exception 'member_setting_values: a signing key was accepted';
  exception
    when check_violation then null;
  end;

  -- ── and the honest cases the guard must not refuse ────────────────────────
  --
  -- A guard that refuses ordinary values is a guard somebody turns off. The
  -- scalar cases matter most: the deep walk raises on one, and the suppression
  -- of that error has to read as "found nothing" rather than as "constraint
  -- satisfied".
  insert into public.member_setting_values (tenant_id, user_id, key, value)
  values
    ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'grid.pageSize', '50'::jsonb),
    ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'shop.sortKey', '"name"'::jsonb),
    ('00000000-0000-0000-0000-000000000001', 'user-alpha',
     'files.allowedExtensions', '["pdf", "csv"]'::jsonb),
    ('00000000-0000-0000-0000-000000000001', 'user-alpha',
     'integrations.config', '{"endpoint": "https://example.test", "retries": 3}'::jsonb)
  on conflict (tenant_id, user_id, key) do update set value = excluded.value;

  raise notice 'member setting values, secrets refused by the database: ok';
end
$$;

-- ── the two `with check` keys, on their own ─────────────────────────────────
--
-- **SET-22**, as `270` does it and for the same reason: a move is refused
-- both by the update policy's `with check` and by the select policy applied
-- to the new row, so attempting the move alone stays green when `with check`
-- is deleted. The select policy is widened for the length of two statements
-- so that only `with check` can refuse them.
--
-- `ui.density` rather than `grid.pageSize`: the colleague and the Beta member
-- both hold a `grid.pageSize` row, and a move onto one collides on the
-- primary key -- which would turn this red for a reason that is not the
-- policy. Neither holds `ui.density`.
--
-- The mechanism was checked rather than assumed, and **deleting** a `with
-- check` clause is not the same as weakening one: `CREATE POLICY` falls back
-- to the `using` expression when none is given, and here the two are
-- identical, so a deletion is a no-op. `270`'s comment has the detail and
-- `set22-mutation-bisection.txt` has the runs.
insert into public.member_setting_values (tenant_id, user_id, key, value)
values ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'ui.density', '"compact"'::jsonb)
on conflict (tenant_id, user_id, key) do update set value = excluded.value;

create policy "tmp_set22_select_all" on public.member_setting_values for select using (true);

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';
set local app.user_id = 'user-alpha';

do $$
begin
  begin
    update public.member_setting_values
       set user_id = 'user-alpha-colleague'
     where key = 'ui.density' and user_id = 'user-alpha';
    raise exception
      'member_setting_values: with check did not refuse a move onto a colleague';
  exception
    when insufficient_privilege then null;
  end;

  begin
    update public.member_setting_values
       set tenant_id = '00000000-0000-0000-0000-000000000002'
     where key = 'ui.density' and user_id = 'user-alpha';
    raise exception
      'member_setting_values: with check did not refuse a move into another tenant';
  exception
    when insufficient_privilege then null;
  end;

  raise notice 'member setting values, with check refuses both moves on its own: ok';
end
$$;

reset role;
drop policy "tmp_set22_select_all" on public.member_setting_values;

rollback;
