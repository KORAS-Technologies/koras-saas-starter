-- Tenant isolation, exercised rather than inspected.
--
-- 010 asserts the policies exist and that the owner cannot skip them. This
-- asserts they say the right thing: two tenants are created, the context is set
-- to one of them, and every policy is asked to produce the other one's rows.
--
-- Deliberately run as a role that is neither superuser nor the table owner,
-- because that is the only role RLS applies to and the failure being guarded
-- against is precisely a connection that turns out not to be one.
--
-- Everything happens in a transaction that rolls back, so the suite leaves no
-- rows behind and can be run against a database that has some.

\set ON_ERROR_STOP on

begin;

-- Two tenants, created as the owner with RLS bypassed by an explicit context.
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-test-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-test-beta', 'Beta');

insert into public.tenant_members (tenant_id, user_id, role)
values
  ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'admin'),
  ('00000000-0000-0000-0000-000000000002', 'user-beta', 'admin');

insert into public.tenant_settings (tenant_id, branding)
values
  ('00000000-0000-0000-0000-000000000001', '{"colour":"alpha"}'),
  ('00000000-0000-0000-0000-000000000002', '{"colour":"beta"}');

-- From here on, act as the application role rather than the owner.
set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  visible int;
begin
  -- ── tenants ───────────────────────────────────────────────────────────────
  select count(*) into visible from public.tenants;
  if visible <> 1 then
    raise exception 'tenants: expected 1 visible row, saw %', visible;
  end if;

  select count(*) into visible
  from public.tenants where slug = 'rls-test-beta';
  if visible <> 0 then
    raise exception 'tenants: another tenant row was visible';
  end if;

  -- ── tenant_members ────────────────────────────────────────────────────────
  select count(*) into visible from public.tenant_members;
  if visible <> 1 then
    raise exception 'tenant_members: expected 1 visible row, saw %', visible;
  end if;

  select count(*) into visible
  from public.tenant_members where user_id = 'user-beta';
  if visible <> 0 then
    raise exception 'tenant_members: another tenant member was visible';
  end if;

  -- ── tenant_settings ───────────────────────────────────────────────────────
  select count(*) into visible from public.tenant_settings;
  if visible <> 1 then
    raise exception 'tenant_settings: expected 1 visible row, saw %', visible;
  end if;

  raise notice 'tenant isolation, reads: ok';
end
$$;

-- Writes are the half a select-only suite misses. A policy with `using` and no
-- `with check` lets a member be written into another tenant while refusing to
-- read it back -- which looks like success to the caller.
do $$
begin
  begin
    insert into public.tenant_members (tenant_id, user_id, role)
    values ('00000000-0000-0000-0000-000000000002', 'smuggled', 'admin');
    raise exception 'tenant_members: a row was inserted into another tenant';
  exception
    when insufficient_privilege then null;
  end;

  begin
    insert into public.tenant_settings (tenant_id, branding)
    values ('00000000-0000-0000-0000-000000000002', '{"colour":"smuggled"}');
    raise exception 'tenant_settings: a row was inserted into another tenant';
  exception
    when insufficient_privilege then null;
  end;

  raise notice 'tenant isolation, writes: ok';
end
$$;

-- An unset context sees nothing at all. This is the state a connection is in
-- when the API forgets to call set_rls_context, and it has to fail closed.
do $$
declare
  visible int;
begin
  perform set_config('app.tenant_id', '', true);

  select count(*) into visible from public.tenants;
  if visible <> 0 then
    raise exception 'tenants: % rows visible with no tenant context', visible;
  end if;

  select count(*) into visible from public.tenant_members;
  if visible <> 0 then
    raise exception 'tenant_members: % rows visible with no tenant context', visible;
  end if;

  raise notice 'unset context fails closed: ok';
end
$$;

reset role;
rollback;
