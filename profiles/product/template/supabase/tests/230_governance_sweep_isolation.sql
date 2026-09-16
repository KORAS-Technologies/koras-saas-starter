-- What the worker may reach for the three sweeps 00024 exists for, and what it
-- still may not. Every assertion here is a boundary the migration crossed on
-- purpose, which is exactly the kind that nothing else would notice moving.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-sweep-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-sweep-beta', 'Beta');

insert into public.audit_exports (id, tenant_id, requested_by, format, status, storage_key, expires_at)
values
  ('60000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001',
   'user-alpha', 'csv', 'ready', 'tenants/1/exports/e1/a.csv', now() - interval '1 day'),
  ('60000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000002',
   'user-beta', 'csv', 'ready', 'tenants/2/exports/e2/b.csv', now() + interval '1 day');

insert into public.legal_holds
  (id, tenant_id, scope, reason, requested_by, approved_by, status, starts_at, ends_at)
values
  -- Bounded and past its end date: the row the sweep exists to close out.
  ('70000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001',
   'files', 'a matter', 'user-alpha', 'user-two', 'active',
   now() - interval '10 days', now() - interval '1 day'),
  -- Open-ended: no end date, so nothing automatic may ever touch it.
  ('70000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001',
   'audit', 'another matter', 'user-alpha', 'user-two', 'active',
   now() - interval '10 days', null),
  -- A second bounded, expired one, kept back so that the release attempt below
  -- is made against a row the policy's `using` clause admits. Aimed at an
  -- open-ended hold instead, that attempt would be refused by the row filter
  -- and would pass whatever `with check` said -- which is a test that cannot
  -- fail, and a test that cannot fail proves nothing.
  ('70000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000001',
   'files', 'a fourth matter', 'user-alpha', 'user-two', 'active',
   now() - interval '10 days', now() - interval '2 days');

set local role koras_rls_test;
select set_config('app.tenant_id', '', true) as _;
select set_config('app.provisioning', 'on', true) as _;

do $$
declare
  visible integer;
  keys integer;
begin
  -- The expiry sweep reads across tenants and removes what has passed its date.
  select count(*) into visible from public.audit_exports;
  if visible <> 2 then
    raise exception 'exports: the sweep sees %, expected both tenants', visible;
  end if;

  delete from public.audit_exports where id = '60000000-0000-0000-0000-000000000001';
  if not found then
    raise exception 'exports: the sweep could not retire an expired artifact';
  end if;

  -- Reconciliation gets keys, and only through the function.
  select count(*) into keys
    from public.claimed_storage_keys('00000000-0000-0000-0000-000000000002');
  if keys <> 1 then
    raise exception 'keys: the function returned % for beta, expected 1', keys;
  end if;

  -- One tenant's keys are not another's.
  select count(*) into keys
    from public.claimed_storage_keys('00000000-0000-0000-0000-000000000001');
  if keys <> 0 then
    raise exception 'keys: alpha''s retired export is still claimed';
  end if;

  raise notice 'audit export expiry and claimed keys: ok';
end
$$;

do $$
declare
  affected integer;
begin
  -- The hold expiry sweep closes out a bounded hold past its date.
  update public.legal_holds set status = 'expired'
   where id = '70000000-0000-0000-0000-000000000001';
  get diagnostics affected = row_count;
  if affected <> 1 then
    raise exception 'holds: the sweep could not close out a hold past its end date';
  end if;

  -- And nothing else. An open-ended hold is a decision with a person behind it.
  update public.legal_holds set status = 'expired'
   where id = '70000000-0000-0000-0000-000000000002';
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'holds: the sweep closed out an open-ended hold';
  end if;

  raise notice 'legal hold expiry is bounded to bounded holds: ok';
end
$$;

-- Releasing is not expiring. The policy admits `expired` and nothing else, so a
-- worker that could flip a hold to `released` would be a worker that can make a
-- purge possible again with no person and no audit row behind it.
do $$
declare
  affected integer;
begin
  insert into public.legal_holds
    (id, tenant_id, scope, reason, requested_by, approved_by, status, starts_at, ends_at)
  values ('70000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001',
          'files', 'a third matter', 'user-alpha', 'user-two', 'active',
          now() - interval '10 days', now() - interval '1 day');
  raise exception 'holds: the sweep created a hold';
exception
  when insufficient_privilege then null;
end
$$;

do $$
declare
  affected integer;
  refused boolean := false;
begin
  begin
    update public.legal_holds set status = 'released'
     where id = '70000000-0000-0000-0000-000000000004';
    get diagnostics affected = row_count;
  exception
    -- A `with check` refusal arrives as an error rather than as no rows, and
    -- either shape is the control working.
    when insufficient_privilege or check_violation then
      refused := true;
  end;

  if not refused and affected <> 0 then
    raise exception 'holds: the sweep released a hold';
  end if;
  raise notice 'the sweep may expire a hold and may not release one: ok';
end
$$;

-- Outside the provisioning context the function answers nothing, rather than
-- answering a tenant's keys to whoever asked.
select set_config('app.provisioning', '', true) as _;
select set_config('app.tenant_id', '00000000-0000-0000-0000-000000000001', true) as _;

do $$
declare
  keys integer;
begin
  select count(*) into keys
    from public.claimed_storage_keys('00000000-0000-0000-0000-000000000002');
  if keys <> 0 then
    raise exception 'keys: a tenant read % of another tenant''s keys', keys;
  end if;
  raise notice 'claimed keys are refused outside the provisioning context: ok';
end
$$;

-- And it may change the status and nothing else. The policy's `with check`
-- cannot see the old row, so it cannot express "everything else unchanged" --
-- a trigger does, and this is what proves the trigger is there. Without it one
-- statement could expire a hold and move it to another tenant in the same
-- UPDATE, which is a hold rewritten by the process whose job is to retire it.
select set_config('app.tenant_id', '', true) as _;
select set_config('app.provisioning', 'on', true) as _;

do $$
declare
  refused boolean := false;
begin
  begin
    update public.legal_holds
       set status = 'expired',
           tenant_id = '00000000-0000-0000-0000-000000000002'
     where id = '70000000-0000-0000-0000-000000000004';
  exception
    when insufficient_privilege then refused := true;
  end;

  if not refused then
    raise exception 'holds: a sweep moved a hold to another tenant while expiring it';
  end if;

  begin
    refused := false;
    update public.legal_holds
       set status = 'expired', reason = 'something else entirely'
     where id = '70000000-0000-0000-0000-000000000004';
  exception
    when insufficient_privilege then refused := true;
  end;

  if not refused then
    raise exception 'holds: a sweep rewrote a hold''s reason while expiring it';
  end if;

  raise notice 'a sweep may change a hold''s status and nothing else: ok';
end
$$;

rollback;
