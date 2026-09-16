-- Retention overrides: a tenant may lengthen, and may not shorten.
--
-- This is the direction that deletes data, so it is asserted three ways: the
-- constraint refuses a value under a day, `retention_days_for` takes whichever
-- of the floor and the override is larger, and a tenant cannot reach another
-- tenant's policy at all.
--
-- Also asserted: the sweeps can read every tenant's override. Without that
-- policy a tenant's longer retention would be honoured by the API and ignored
-- by the job that actually deletes, which is the worst of both -- a customer
-- told their records are kept for seven years, and a sweep removing them at
-- one.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-ovr-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-ovr-beta', 'Beta');

insert into public.tenant_settings (tenant_id, retention_overrides)
values
  -- Alpha keeps audit rows for seven years, which is longer than the floor,
  -- and wants its own documents gone in ninety days -- a class the platform
  -- sets no floor for, so nothing stands in the way of that.
  ('00000000-0000-0000-0000-000000000001',
   '{"audit": 2555, "storage_standard": 90}'::jsonb),
  -- Beta has asked for less than the floor. The row is allowed; the floor
  -- still wins at resolution, which is the point.
  ('00000000-0000-0000-0000-000000000002', '{"audit": 30}'::jsonb);

do $$
declare
  resolved integer;
begin
  -- A longer override wins.
  select public.retention_days_for('00000000-0000-0000-0000-000000000001', 'audit', 365)
    into resolved;
  if resolved <> 2555 then
    raise exception 'overrides: a longer override did not win, resolved %', resolved;
  end if;

  -- A shorter one does not. This is the whole policy in one assertion.
  select public.retention_days_for('00000000-0000-0000-0000-000000000002', 'audit', 365)
    into resolved;
  if resolved <> 365 then
    raise exception 'overrides: a shorter override won, resolved %', resolved;
  end if;

  -- A kind nobody overrode takes the floor.
  select public.retention_days_for('00000000-0000-0000-0000-000000000001', 'audit_security', 1095)
    into resolved;
  if resolved <> 1095 then
    raise exception 'overrides: an absent kind did not take the floor, resolved %', resolved;
  end if;

  -- A tenant with no settings row at all takes the floor.
  select public.retention_days_for('00000000-0000-0000-0000-000000000009', 'audit', 365)
    into resolved;
  if resolved <> 365 then
    raise exception 'overrides: a tenant with no row did not take the floor, resolved %', resolved;
  end if;

  -- A class with no platform floor, and nobody overriding it, resolves to
  -- zero. Zero is what the object sweep reads as "no date is due", and the
  -- statement that writes `retain_until` is guarded on it being above zero.
  --
  -- This is the case that nearly shipped as a wipe. A floor of one day made
  -- every standard object expire the night after upload; the answer is not a
  -- smaller number but no number, and this is the assertion that the absence
  -- resolves to something the sweep will refuse to act on.
  select public.retention_days_for('00000000-0000-0000-0000-000000000009', 'storage_standard', 0)
    into resolved;
  if resolved <> 0 then
    raise exception 'overrides: an absent floor resolved to %, expected 0', resolved;
  end if;

  -- And a tenant who does want their documents gone still gets a date, because
  -- their override resolves above the absent floor rather than under it.
  select public.retention_days_for('00000000-0000-0000-0000-000000000001', 'storage_standard', 0)
    into resolved;
  if resolved <> 90 then
    raise exception 'overrides: a tenant override over an absent floor resolved %', resolved;
  end if;

  raise notice 'retention override resolution: ok';
end
$$;

do $$
begin
  -- Zero would be a wipe on the next sweep, and is refused by the constraint
  -- rather than by whichever route happened to be written carefully.
  begin
    update public.tenant_settings set retention_overrides = '{"audit": 0}'::jsonb
     where tenant_id = '00000000-0000-0000-0000-000000000001';
    raise exception 'overrides: a retention of zero was accepted';
  exception
    when check_violation then null;
  end;

  -- So is a fraction of a day, and a value that is not a number at all.
  begin
    update public.tenant_settings set retention_overrides = '{"audit": 1.5}'::jsonb
     where tenant_id = '00000000-0000-0000-0000-000000000001';
    raise exception 'overrides: a fractional retention was accepted';
  exception
    when check_violation then null;
  end;

  begin
    update public.tenant_settings set retention_overrides = '{"audit": "forever"}'::jsonb
     where tenant_id = '00000000-0000-0000-0000-000000000001';
    raise exception 'overrides: a non-numeric retention was accepted';
  exception
    when check_violation then null;
  end;

  raise notice 'retention override constraint: ok';
end
$$;

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  visible integer;
begin
  select count(*) into visible from public.tenant_settings;
  if visible <> 1 then
    raise exception 'overrides: expected 1 visible settings row, saw %', visible;
  end if;

  -- Another tenant's retention policy is neither readable nor writable.
  update public.tenant_settings set retention_overrides = '{"audit": 1}'::jsonb
   where tenant_id = '00000000-0000-0000-0000-000000000002';
  if found then
    raise exception 'overrides: another tenant''s retention was changed';
  end if;

  -- The tenant may lengthen its own, which is the capability this exists for.
  update public.tenant_settings set retention_overrides = '{"audit": 3650}'::jsonb
   where tenant_id = '00000000-0000-0000-0000-000000000001';
  if not found then
    raise exception 'overrides: a tenant could not set its own retention';
  end if;

  raise notice 'retention override isolation: ok';
end
$$;

do $$
declare
  resolved integer;
begin
  perform set_config('app.tenant_id', '', true);
  perform set_config('app.provisioning', 'on', true);

  -- The sweeps must see every tenant's override, or the API and the job that
  -- deletes would disagree about how long a record is kept.
  select public.retention_days_for('00000000-0000-0000-0000-000000000001', 'audit', 365)
    into resolved;
  if resolved <> 3650 then
    raise exception 'overrides: the sweep resolved %, not the tenant''s own 3650', resolved;
  end if;

  -- Read only. A sweep that could rewrite a customer's retention policy could
  -- shorten it and then honour the shorter number.
  update public.tenant_settings set retention_overrides = '{"audit": 1}'::jsonb
   where tenant_id = '00000000-0000-0000-0000-000000000001';
  if found then
    raise exception 'overrides: provisioning rewrote a retention policy';
  end if;

  raise notice 'retention override sweep access: ok';
end
$$;

rollback;
