-- A language preference belongs to one person in one tenant.
--
-- The first policy in this schema keyed to `current_user_id()` as well as to
-- the tenant. Two tenants and three people are created; then the suite acts as
-- one of them and asks for everybody else's row, tries to write one for a
-- colleague and for a stranger, and finally drops the subject and expects to
-- see nothing at all. The tenant default on `tenant_settings` is checked in
-- the same pass, because it is the other half of the same feature.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-locale-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-locale-beta', 'Beta');

insert into public.tenant_settings (tenant_id, locale)
values
  ('00000000-0000-0000-0000-000000000001', 'de'),
  ('00000000-0000-0000-0000-000000000002', 'es');

-- Two people in alpha, one in beta. The second alpha member is the case a
-- tenant-only policy would get wrong.
insert into public.member_preferences (tenant_id, user_id, locale)
values
  ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'en'),
  ('00000000-0000-0000-0000-000000000001', 'user-alpha-colleague', 'de'),
  ('00000000-0000-0000-0000-000000000002', 'user-beta', 'es');

-- From here on, act as the application role, as user-alpha in tenant alpha.
set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';
set local app.user_id = 'user-alpha';

do $$
declare
  visible integer;
  seen text;
begin
  -- ── reads: one row, and it is mine ────────────────────────────────────────
  select count(*) into visible from public.member_preferences;
  if visible <> 1 then
    raise exception 'member_preferences: expected 1 visible row, saw %', visible;
  end if;

  select locale into seen from public.member_preferences;
  if seen <> 'en' then
    raise exception 'member_preferences: read somebody else''s preference (%)', seen;
  end if;

  select count(*) into visible
  from public.member_preferences where user_id = 'user-alpha-colleague';
  if visible <> 0 then
    raise exception 'member_preferences: a colleague''s row in the same tenant was visible';
  end if;

  -- ── writes: my own row, and only my own ──────────────────────────────────
  update public.member_preferences set locale = 'es';
  select locale into seen from public.member_preferences where user_id = 'user-alpha';
  if seen <> 'es' then
    raise exception 'member_preferences: could not update my own preference';
  end if;

  -- An update aimed at a colleague matches no row rather than being refused:
  -- the `using` clause hides it. Zero rows changed is the assertion.
  update public.member_preferences set locale = 'en' where user_id = 'user-alpha-colleague';
  get diagnostics visible = row_count;
  if visible <> 0 then
    raise exception 'member_preferences: a colleague''s preference was updated';
  end if;

  begin
    insert into public.member_preferences (tenant_id, user_id, locale)
    values ('00000000-0000-0000-0000-000000000001', 'user-alpha-newcomer', 'de');
    raise exception 'member_preferences: a row was inserted for another person';
  exception
    when insufficient_privilege then null;
  end;

  begin
    insert into public.member_preferences (tenant_id, user_id, locale)
    values ('00000000-0000-0000-0000-000000000002', 'user-alpha', 'de');
    raise exception 'member_preferences: a row was inserted into another tenant';
  exception
    when insufficient_privilege then null;
  end;

  -- The shape constraint holds whoever writes.
  begin
    update public.member_preferences set locale = 'not a language';
    raise exception 'member_preferences: a value that is not a language tag was stored';
  exception
    when check_violation then null;
  end;

  -- The upsert the API issues: the same statement creates a first row and
  -- replaces a later one, and both are admitted for the caller's own key.
  insert into public.member_preferences (tenant_id, user_id, locale)
  values ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'de')
  on conflict (tenant_id, user_id) do update set locale = excluded.locale;
  select locale into seen from public.member_preferences where user_id = 'user-alpha';
  if seen <> 'de' then
    raise exception 'member_preferences: the upsert did not replace the preference';
  end if;

  raise notice 'member preferences, one person one row: ok';
end
$$;

-- ── the tenant default ────────────────────────────────────────────────────────
do $$
declare
  seen text;
  visible integer;
begin
  select locale into seen from public.tenant_settings;
  if seen <> 'de' then
    raise exception 'tenant_settings: expected the tenant''s own default, read %', seen;
  end if;

  update public.tenant_settings set locale = null;
  select locale into seen from public.tenant_settings where tenant_id = '00000000-0000-0000-0000-000000000001';
  if seen is not null then
    raise exception 'tenant_settings: could not clear the tenant''s own default';
  end if;

  update public.tenant_settings set locale = 'en' where tenant_id = '00000000-0000-0000-0000-000000000002';
  get diagnostics visible = row_count;
  if visible <> 0 then
    raise exception 'tenant_settings: another tenant''s default was updated';
  end if;

  begin
    update public.tenant_settings set locale = 'english';
    raise exception 'tenant_settings: a value that is not a language tag was stored';
  exception
    when check_violation then null;
  end;

  raise notice 'tenant default language, own tenant only: ok';
end
$$;

-- ── no subject, no rows ───────────────────────────────────────────────────────
-- A request that declared a tenant and no person -- the worker, the platform's
-- collector -- sees no preference and can write none. The tenant is still set,
-- which is what makes this the interesting case: the tenant policies alone
-- would admit every row in alpha.
do $$
declare
  visible integer;
begin
  perform set_config('app.user_id', '', true);

  select count(*) into visible from public.member_preferences;
  if visible <> 0 then
    raise exception 'member_preferences: % rows visible with no subject declared', visible;
  end if;

  begin
    insert into public.member_preferences (tenant_id, user_id, locale)
    values ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'en');
    raise exception 'member_preferences: a row was written with no subject declared';
  exception
    when insufficient_privilege then null;
  end;

  raise notice 'member preferences, no subject fails closed: ok';
end
$$;

reset role;
rollback;
