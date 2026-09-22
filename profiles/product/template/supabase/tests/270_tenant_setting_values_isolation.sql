-- A tenant's settings belong to that tenant, and cannot be deleted.
--
-- Two tenants are seeded, then the suite acts as one of them and asks for the
-- other's rows, tries to write into them, and tries to delete its own. The last
-- of those is the unusual assertion and the one most likely to be "fixed" by
-- somebody who reads the missing delete policy as an oversight: resetting a
-- tenant setting copies the platform's current value in, and deleting the row
-- instead would restore the dynamic inheritance the whole snapshot exists to
-- prevent.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-tsv-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-tsv-beta', 'Beta');

insert into public.tenant_setting_values (tenant_id, key, value)
values
  ('00000000-0000-0000-0000-000000000001', 'grid.pageSize', '100'::jsonb),
  ('00000000-0000-0000-0000-000000000001', 'ui.theme', '"light"'::jsonb),
  ('00000000-0000-0000-0000-000000000002', 'grid.pageSize', '25'::jsonb);

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';
set local app.user_id = 'user-alpha';

do $$
declare
  visible integer;
  seen jsonb;
begin
  -- ── reads: my tenant's rows and no others ────────────────────────────────
  select count(*) into visible from public.tenant_setting_values;
  if visible <> 2 then
    raise exception 'tenant_setting_values: expected 2 visible rows, saw %', visible;
  end if;

  select value into seen from public.tenant_setting_values where key = 'grid.pageSize';
  if seen <> '100'::jsonb then
    raise exception 'tenant_setting_values: read % rather than my own value', seen;
  end if;

  select count(*) into visible
  from public.tenant_setting_values
  where tenant_id = '00000000-0000-0000-0000-000000000002';
  if visible <> 0 then
    raise exception 'tenant_setting_values: another tenant''s row was visible';
  end if;

  -- ── writes: my tenant's rows and no others ───────────────────────────────
  update public.tenant_setting_values set value = '250'::jsonb where key = 'grid.pageSize';
  select value into seen from public.tenant_setting_values where key = 'grid.pageSize';
  if seen <> '250'::jsonb then
    raise exception 'tenant_setting_values: could not update my own value';
  end if;

  update public.tenant_setting_values set value = '10'::jsonb
   where tenant_id = '00000000-0000-0000-0000-000000000002';
  get diagnostics visible = row_count;
  if visible <> 0 then
    raise exception 'tenant_setting_values: a row was rewritten in another tenant';
  end if;

  begin
    insert into public.tenant_setting_values (tenant_id, key, value)
    values ('00000000-0000-0000-0000-000000000002', 'ui.density', '"compact"'::jsonb);
    raise exception 'tenant_setting_values: a row was written into another tenant';
  exception
    when insufficient_privilege then null;
  end;

  -- The upsert the API issues: one statement creates a first value and
  -- replaces a later one, and both are admitted for the caller's own tenant.
  insert into public.tenant_setting_values (tenant_id, key, value)
  values ('00000000-0000-0000-0000-000000000001', 'grid.rowDensity', '"compact"'::jsonb)
  on conflict (tenant_id, key) do update set value = excluded.value;
  insert into public.tenant_setting_values (tenant_id, key, value)
  values ('00000000-0000-0000-0000-000000000001', 'grid.rowDensity', '"comfortable"'::jsonb)
  on conflict (tenant_id, key) do update set value = excluded.value;
  select value into seen from public.tenant_setting_values where key = 'grid.rowDensity';
  if seen <> '"comfortable"'::jsonb then
    raise exception 'tenant_setting_values: the upsert did not replace the value';
  end if;

  -- ── moves: a row may not be carried into another tenant ──────────────────
  --
  -- **SET-22.** Every assertion above this one asks whether a row can be read
  -- or written *where it is*. None asked whether it can be made to belong
  -- somewhere else, so the `with check` clause on the update policy was
  -- correct and entirely unexercised -- deleting it left this suite green,
  -- which was demonstrated rather than assumed before this was written.
  --
  -- Two clauses refuse it, and the test names the boundary rather than either
  -- one: the update policy's `with check`, and the select policy applied to
  -- the new row. That is why this asserts the refusal and not which clause
  -- produced it -- an assertion naming one would pass while the other did all
  -- the work, which is the failure it exists to catch.
  --
  -- `ui.theme` rather than `grid.pageSize`, because Beta holds a
  -- `grid.pageSize` row of its own: moving onto it collides on the primary
  -- key, and a test that goes red on a duplicate key is not testing the
  -- policy. Beta holds no `ui.theme`, so the only thing that can refuse this
  -- is row-level security.
  begin
    update public.tenant_setting_values
       set tenant_id = '00000000-0000-0000-0000-000000000002'
     where key = 'ui.theme';
    raise exception 'tenant_setting_values: a row was moved into another tenant';
  exception
    when insufficient_privilege then null;
  end;

  -- ── deletes: none, not even my own ───────────────────────────────────────
  --
  -- There is no delete policy, so the statement matches nothing rather than
  -- being refused. A tenant resets by writing the platform's current value,
  -- which is a different state from having no row at all.
  delete from public.tenant_setting_values where key = 'ui.theme';
  get diagnostics visible = row_count;
  if visible <> 0 then
    raise exception 'tenant_setting_values: a tenant deleted its own setting';
  end if;

  raise notice 'tenant setting values, own tenant only and never deleted: ok';
end
$$;

-- ── no tenant, no rows ───────────────────────────────────────────────────────
do $$
declare
  visible integer;
begin
  perform set_config('app.tenant_id', '', true);

  select count(*) into visible from public.tenant_setting_values;
  if visible <> 0 then
    raise exception 'tenant_setting_values: % rows visible with no tenant declared', visible;
  end if;

  begin
    insert into public.tenant_setting_values (tenant_id, key, value)
    values ('00000000-0000-0000-0000-000000000001', 'ui.density', '"compact"'::jsonb);
    raise exception 'tenant_setting_values: a row was written with no tenant declared';
  exception
    when insufficient_privilege then null;
  end;

  raise notice 'tenant setting values, no tenant fails closed: ok';
end
$$;

-- ── the secret guard ─────────────────────────────────────────────────────────
reset role;

do $$
begin
  begin
    insert into public.tenant_setting_values (tenant_id, key, value)
    values ('00000000-0000-0000-0000-000000000001', 'billing.apiKey', '"not-a-real-one"'::jsonb);
    raise exception 'tenant_setting_values: a credential-shaped key was accepted';
  exception
    when check_violation then null;
  end;

  raise notice 'tenant setting values, secrets refused by the database: ok';
end
$$;

-- ── the `with check` clause, on its own ──────────────────────────────────────
--
-- **SET-22, and the half the move assertion above cannot reach.** Two
-- independent clauses refuse a row move: the update policy's `with check`,
-- and the select policy applied to the new row. Because either alone is
-- enough, a test that only attempts the move stays green when `with check`
-- is deleted -- which is precisely the finding, and deleting it was shown to
-- leave this suite green before this block was written.
--
-- So the other guard is neutralised for the length of one statement and the
-- move is attempted again. What refuses it now can only be `with check`.
-- Everything here is inside the transaction this file rolls back, and the
-- temporary policy is dropped either way.
--
-- **Two things about this were checked rather than assumed**, because an
-- independent review disputed both on 2026-09-21 and one of its points was
-- right.
--
-- The mechanism holds: with `with check` set EXPLICITLY to `true`, a move is
-- still refused while the select policy is narrow, and succeeds the moment a
-- second permissive select policy widens it. Three configurations, recorded
-- in
-- `docs/features/settings-framework/testing/runs/2026-09-21-01/set22-mutation-bisection.txt`.
-- So the select policy does gate the new row, and widening it is what leaves
-- `with check` alone to refuse the move.
--
-- What the review got right is subtler and worth knowing before anybody
-- "simplifies" this: **deleting** the `with check` clause is not the same as
-- setting it to `true`. `CREATE POLICY` falls back to the `using` expression
-- when no `with check` is given, and here the two are identical -- so a
-- deletion is a no-op and nothing can or should catch it. This block catches
-- the edit that matters, which is a `with check` weakened to something that
-- admits another tenant.
create policy "tmp_set22_select_all" on public.tenant_setting_values for select using (true);

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';
set local app.user_id = 'user-alpha';

do $$
begin
  begin
    update public.tenant_setting_values
       set tenant_id = '00000000-0000-0000-0000-000000000002'
     where key = 'ui.theme';
    raise exception
      'tenant_setting_values: with check did not refuse a move the select policy allowed';
  exception
    when insufficient_privilege then null;
  end;

  raise notice 'tenant setting values, with check refuses a move on its own: ok';
end
$$;

reset role;
drop policy "tmp_set22_select_all" on public.tenant_setting_values;

rollback;
