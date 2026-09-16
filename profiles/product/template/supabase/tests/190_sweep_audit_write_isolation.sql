-- The sweep's own audit write: a cross-context insert, bounded.
--
-- The reconciliation sweep reads every tenant on the provisioning context and
-- then has something to record about one of them. It cannot record it from
-- there: `audit_events` has a select and a delete policy for provisioning and
-- deliberately **no insert policy**, so a sweep must become the tenant to write
-- about the tenant.
--
-- That switch is the only place in the product where a process holding
-- cross-tenant reach writes a tenant-owned row, and it was unproven until this
-- test. The failure it guards against is not exotic: the switch sets two
-- settings, and a version that cleared the provisioning flag and forgot to bind
-- the tenant -- or bound the wrong one -- would insert rows attributed to
-- whatever was left in the session, which on a pooled connection is the
-- previous tenant.
--
-- The worker runs as the application role, which is under forced row-level
-- security exactly as this restricted role is, so what is asserted here is what
-- the worker gets.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-sweep-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-sweep-beta', 'Beta');

set local role koras_rls_test;

do $$
declare
  visible integer;
  owner   uuid;
begin
  -- 1. The provisioning context can read every tenant, which is why the sweep
  --    runs there at all.
  perform set_config('app.tenant_id', '', true);
  perform set_config('app.provisioning', 'on', true);

  select count(*) into visible from public.tenants;
  if visible < 2 then
    raise exception 'sweep write: provisioning could not see both tenants, saw %', visible;
  end if;

  -- 2. And cannot record anything from there. This refusal is the reason the
  --    switch below exists; if it ever stops being a refusal, the switch is
  --    dead code and nobody will notice.
  begin
    insert into public.audit_events
      (tenant_id, actor_id, action, target_type, target_id, outcome, classification)
    values ('00000000-0000-0000-0000-000000000001', 'system',
            'storage.reconcile.orphan_found', 'tenant',
            '00000000-0000-0000-0000-000000000001', 'ok', 'audit');
    raise exception 'sweep write: provisioning inserted an audit row';
  exception
    when insufficient_privilege then null;
  end;

  -- 3. The switch the sweep actually performs: drop provisioning, bind the
  --    tenant, write. Both settings in one step, as `_AS_TENANT` does.
  perform set_config('app.provisioning', '', true);
  perform set_config('app.tenant_id', '00000000-0000-0000-0000-000000000001', true);

  insert into public.audit_events
    (tenant_id, actor_id, action, target_type, target_id, outcome, details, classification)
  values ('00000000-0000-0000-0000-000000000001', 'system',
          'storage.reconcile.orphan_found', 'tenant',
          '00000000-0000-0000-0000-000000000001', 'ok',
          '{"orphan_objects": 2, "stale_pending": 1}'::jsonb, 'audit');

  select count(*) into visible
    from public.audit_events where action = 'storage.reconcile.orphan_found';
  if visible <> 1 then
    raise exception 'sweep write: expected the row to be readable back, saw %', visible;
  end if;

  select tenant_id into owner
    from public.audit_events where action = 'storage.reconcile.orphan_found';
  if owner <> '00000000-0000-0000-0000-000000000001' then
    raise exception 'sweep write: the row was attributed to %', owner;
  end if;

  -- 4. Bound to Alpha, the sweep cannot write about Beta. This is the case the
  --    switch gets wrong when a loop reuses a session and forgets to re-bind:
  --    the row would be attributed to whoever was bound last.
  begin
    insert into public.audit_events
      (tenant_id, actor_id, action, target_type, target_id, outcome, classification)
    values ('00000000-0000-0000-0000-000000000002', 'system',
            'storage.reconcile.orphan_found', 'tenant',
            '00000000-0000-0000-0000-000000000002', 'ok', 'audit');
    raise exception 'sweep write: a row was written about another tenant';
  exception
    when insufficient_privilege then null;
  end;

  -- 5. Having become a tenant, the sweep has lost its cross-tenant reach --
  --    which is the point of the settings being transaction-local rather than
  --    a flag someone remembers to clear.
  select count(*) into visible from public.tenants;
  if visible <> 1 then
    raise exception 'sweep write: still saw % tenants after binding one', visible;
  end if;

  -- 6. And the row it just wrote is as immutable as any other: the sweep
  --    cannot correct its own counts afterwards.
  update public.audit_events
     set details = '{"orphan_objects": 0}'::jsonb
   where action = 'storage.reconcile.orphan_found';
  if found then
    raise exception 'sweep write: the sweep rewrote its own audit row';
  end if;

  raise notice 'sweep audit write isolation: ok';
end
$$;

-- The return leg. A sweep records for one tenant and then goes back to
-- provisioning for the next, and the row it wrote must still be there and still
-- be readable from the context that will eventually delete it.
do $$
declare
  visible integer;
begin
  perform set_config('app.tenant_id', '', true);
  perform set_config('app.provisioning', 'on', true);

  select count(*) into visible
    from public.audit_events where action = 'storage.reconcile.orphan_found';
  if visible <> 1 then
    raise exception 'sweep write: provisioning could not read the row back, saw %', visible;
  end if;

  raise notice 'sweep audit write return leg: ok';
end
$$;

rollback;
