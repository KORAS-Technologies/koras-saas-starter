-- Legal holds: a hold on a row a tenant cannot see is not a hold.
--
-- Two claims, and the second is the one that matters. The first is the usual
-- tenancy boundary. The second is that the sweeps, which run on the
-- provisioning context and reach every tenant, can *read* every tenant's holds
-- and cannot create or change one -- because a sweep that could not read a
-- hold would purge on behalf of a tenant in litigation, and a sweep that could
-- write one could freeze a customer's data with nobody's approval.
--
-- Also asserted: a hold is released, never deleted. The record that data was
-- frozen between two dates is itself evidence, and there is no delete policy
-- for anyone.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-hold-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-hold-beta', 'Beta');

insert into public.legal_holds (tenant_id, scope, reason, requested_by, approved_by, status)
values
  ('00000000-0000-0000-0000-000000000001', 'tenant', 'alpha matter', 'user-alpha',
   'owner-alpha', 'active'),
  ('00000000-0000-0000-0000-000000000002', 'files', 'beta matter', 'user-beta',
   'owner-beta', 'active');

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  visible integer;
  held    boolean;
begin
  select count(*) into visible from public.legal_holds;
  if visible <> 1 then
    raise exception 'holds: expected 1 visible hold, saw %', visible;
  end if;

  -- The other tenant's reason names their matter and must not be readable.
  select count(*) into visible from public.legal_holds where reason = 'beta matter';
  if visible <> 0 then
    raise exception 'holds: another tenant''s hold was visible';
  end if;

  -- Releasing another tenant's hold is the attack this table exists to
  -- prevent: it is what makes their purge possible again.
  update public.legal_holds set status = 'released'
   where tenant_id = '00000000-0000-0000-0000-000000000002';
  if found then
    raise exception 'holds: another tenant''s hold was released';
  end if;

  -- And the tenant can release its own, or the mechanism would be unusable.
  update public.legal_holds set status = 'released'
   where reason = 'alpha matter';
  if not found then
    raise exception 'holds: a tenant could not release its own hold';
  end if;
  update public.legal_holds set status = 'active' where reason = 'alpha matter';

  -- A hold is released, not deleted. No delete policy exists for anyone.
  delete from public.legal_holds where reason = 'alpha matter';
  if found then
    raise exception 'holds: a hold was deleted';
  end if;

  -- An insert naming another tenant is refused.
  begin
    insert into public.legal_holds (tenant_id, scope, reason, requested_by)
    values ('00000000-0000-0000-0000-000000000002', 'tenant', 'planted', 'user-alpha');
    raise exception 'holds: a hold was created for another tenant';
  exception
    when insufficient_privilege then null;
  end;

  -- A hold cannot be moved to another tenant by update.
  begin
    update public.legal_holds
       set tenant_id = '00000000-0000-0000-0000-000000000002'
     where reason = 'alpha matter';
    raise exception 'holds: a hold was moved to another tenant';
  exception
    when insufficient_privilege then null;
  end;

  -- The helper answers for this tenant, and only from this tenant's holds.
  select public.under_legal_hold('00000000-0000-0000-0000-000000000001', 'files') into held;
  if not held then
    raise exception 'holds: an active tenant-scope hold did not cover files';
  end if;

  raise notice 'legal hold isolation: ok';
end
$$;

-- The sweeps' half: provisioning must read every tenant's holds and change
-- none of them.
do $$
declare
  visible integer;
  held    boolean;
begin
  perform set_config('app.tenant_id', '', true);
  perform set_config('app.provisioning', 'on', true);

  select count(*) into visible from public.legal_holds;
  if visible <> 2 then
    raise exception 'holds: provisioning saw % holds, expected 2', visible;
  end if;

  -- This is the question both sweeps ask, and it must answer for a tenant the
  -- sweep is not bound to.
  select public.under_legal_hold('00000000-0000-0000-0000-000000000002', 'files') into held;
  if not held then
    raise exception 'holds: provisioning could not see beta''s hold on files';
  end if;

  -- Beta's hold is scoped to files, so it must not cover audit.
  select public.under_legal_hold('00000000-0000-0000-0000-000000000002', 'audit') into held;
  if held then
    raise exception 'holds: a files-scoped hold covered audit';
  end if;

  -- Select only. A sweep that could release a hold could purge whatever it
  -- wanted, one statement earlier.
  update public.legal_holds set status = 'released' where status = 'active';
  if found then
    raise exception 'holds: provisioning released a hold';
  end if;

  begin
    insert into public.legal_holds (tenant_id, scope, reason, requested_by)
    values ('00000000-0000-0000-0000-000000000001', 'tenant', 'planted', 'system');
    raise exception 'holds: provisioning created a hold';
  exception
    when insufficient_privilege then null;
  end;

  raise notice 'legal hold sweep access: ok';
end
$$;

rollback;
