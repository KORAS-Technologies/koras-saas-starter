-- The provisioning context, exercised rather than described.
--
-- `010` asserts that policies exist and `020` asserts that the tenant-scoped
-- ones say the right thing. Neither reaches the pair added by `00003`, and
-- those are the ones where it matters most: they are the only policies in this
-- schema with no tenant predicate, so were `is_provisioning()` true by default
-- they would admit everybody to every tenant's rows.
--
-- The parts that touch a table run as `koras_rls_test`, created by
-- `local/scripts/test-rls.sh` as neither a superuser nor a BYPASSRLS role --
-- the only kind of role RLS applies to. Sections 1 and 5 need no table and run
-- as whoever the suite connected as; they ask about the flag alone.
--
-- Every transaction here rolls back, so the suite leaves no rows behind and can
-- be run against a database that has some. Sections 4 and 5 check the two ways
-- the flag has to stop applying: cleared within a transaction, which is what
-- `set_rls_context` does when it hands the connection to a tenant, and gone by
-- the next one, which is what keeps it off a pooled connection's next occupant.

\set ON_ERROR_STOP on

-- ── 1. Nothing set means not provisioning ────────────────────────────────────
--
-- The same null-safety the tenant helper depends on. `current_setting(..., true)`
-- returns null rather than raising when the GUC was never set, and null is what
-- has to become false here. A default of true would make the two policies below
-- unconditional.
do $$
begin
  if public.is_provisioning() then
    raise exception 'is_provisioning() is true with nothing set; every provisioning policy is unconditional';
  end if;
  raise notice 'provisioning context defaults to off: ok';
end
$$;

-- ── 2. Without it, the tenant table refuses an insert ────────────────────────
--
-- Two policies could admit this and neither does. 00002 gives a tenant's own
-- user select and update on their own row and no insert at all, and 00003's
-- insert policy is the one under test -- its `with check` is false here, so the
-- row is refused. What the flag turns on is exactly the difference between this
-- section and the next one.
begin;
set local role koras_rls_test;

do $$
begin
  begin
    insert into public.tenants (tenant_key, name, slug)
    values ('rls-prov-denied', 'Denied', 'rls-prov-denied');
    raise exception 'a tenant was inserted with no provisioning context';
  exception
    when insufficient_privilege then
      raise notice 'insert refused without provisioning context: ok';
  end;
end
$$;

rollback;

-- ── 3. With it, the platform API's own statements work ───────────────────────
--
-- Shaped after `core/tenant_store.py` rather than simplified: the conflict
-- target is `tenant_key` and the statement returns, because whether a row comes
-- back is what decides 201 from 200. `returning` also needs the select policy
-- as well as the insert one, so a plainer insert would have left half of this
-- untested. The casts and bind parameters are the driver's business and are not
-- reproduced here.
begin;
set local role koras_rls_test;
select set_config('app.provisioning', 'on', true) as _;

do $$
declare
  first_id uuid;
  second_id uuid;
  visible int;
begin
  insert into public.tenants (tenant_key, organization_id, name, slug, plan, status, owner_email)
  values ('rls-prov-alpha', gen_random_uuid(), 'Alpha', 'rls-prov-alpha', 'trial', 'provisioning', 'owner@rls-prov.invalid')
  on conflict (tenant_key) do nothing
  returning id into first_id;

  if first_id is null then
    raise exception 'the insert returned no row, so the API could not tell a create from a retry';
  end if;

  -- The owner's membership, written in the same transaction, under its own
  -- pair of policies.
  --
  -- This statement is the reason `tenant_members` has a provisioning *select*
  -- policy and not only an insert one. `on conflict` naming an arbiter index
  -- requires the select policies to admit the proposed row, because the
  -- uniqueness check would otherwise reveal rows the caller cannot see. With
  -- insert alone this is refused as "new row violates row-level security
  -- policy" -- which reads like a `with check` failure and is not one, and cost
  -- an hour to find the first time. Removing that select policy as unused
  -- breaks this line and nothing else, so this is where it is asserted.
  insert into public.tenant_members (tenant_id, user_id, role)
  values (first_id, 'rls-prov-owner-subject', 'organization_owner')
  on conflict (tenant_id, user_id) do nothing;

  -- The retry, sent exactly as the Control Plane would send it: the same
  -- payload again, so the slug collides as well as the key.
  --
  -- That is the case worth pinning. `on conflict (tenant_key)` names an arbiter
  -- index, and the speculative insertion checks that index alone -- so the key
  -- conflict is absorbed and the slug's unique index is never reached. Had
  -- Postgres considered both, an ordinary retry would raise `unique_violation`
  -- and the API would answer 409 to the one call the contract requires it to
  -- answer 200 to. A repeat with a *different* slug would not have shown this:
  -- there would have been nothing for the second index to object to.
  insert into public.tenants (tenant_key, organization_id, name, slug, plan, status, owner_email)
  values ('rls-prov-alpha', gen_random_uuid(), 'Alpha', 'rls-prov-alpha', 'trial', 'provisioning', 'owner@rls-prov.invalid')
  on conflict (tenant_key) do nothing
  returning id into second_id;

  if second_id is not null then
    raise exception 'a repeated tenant_key created a second tenant';
  end if;

  -- Readable within the same context, which the lookup by key depends on.
  select count(*) into visible from public.tenants where tenant_key = 'rls-prov-alpha';
  if visible <> 1 then
    raise exception 'the provisioning context cannot read the tenant it just created';
  end if;

  raise notice 'provisioning insert, idempotent repeat and read: ok';
end
$$;

-- ── 3b. A different organization asking for the same slug is not a retry ─────
--
-- `on conflict (tenant_key)` absorbs a repeated key and nothing else, so this
-- raises rather than being silently ignored -- which is what `tenant_store.py`
-- turns into `SlugTaken` and the router into a 409. The distinction is the
-- whole point: a repeat of the same key must succeed, and two organizations
-- asking for one name must not.
do $$
begin
  begin
    insert into public.tenants (tenant_key, organization_id, name, slug, plan, status, owner_email)
    values ('rls-prov-beta', gen_random_uuid(), 'Beta', 'rls-prov-alpha', 'pro', 'provisioning', 'owner@rls-prov-beta.invalid')
    on conflict (tenant_key) do nothing;
    raise exception 'two tenants were given the same slug';
  exception
    when unique_violation then
      raise notice 'a colliding slug under a new tenant_key is refused: ok';
  end;
end
$$;

-- ── 4. Turning it off closes the table again, in the same transaction ────────
--
-- `set_rls_context` clears the flag when it sets a tenant, and this is that
-- path: a connection that has just provisioned and is then handed a tenant
-- request must not still see across tenants. Asserted here rather than trusted
-- to the transaction boundary, because the boundary is what would hide a
-- regression in the clearing.
select set_config('app.provisioning', 'off', true) as _;

do $$
declare
  visible int;
begin
  if public.is_provisioning() then
    raise exception 'the provisioning flag survived being set to off';
  end if;

  select count(*) into visible from public.tenants;
  if visible <> 0 then
    raise exception 'with no tenant context and no provisioning context, % tenant rows are readable', visible;
  end if;

  raise notice 'clearing the provisioning context closes the table: ok';
end
$$;

rollback;

-- ── 5. And it did not outlive the transaction ────────────────────────────────
do $$
begin
  if public.is_provisioning() then
    raise exception 'the provisioning flag outlived its transaction; it would be inherited on a pooled connection';
  end if;
  raise notice 'provisioning context is transaction-local: ok';
end
$$;
