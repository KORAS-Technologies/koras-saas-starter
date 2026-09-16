-- Classification: the column that decides how long a row is kept cannot be
-- changed by the tenant the row belongs to, or by anyone else.
--
-- 110 proves the table is tenant-scoped and insert-only. This proves the
-- narrower thing 00019 introduced: retention is now resolved from
-- `classification`, so a principal that could rewrite that column could decide
-- when their own audit trail disappears. Reclassifying a `security` row as
-- `activity` shortens it from three years to ninety days, which is deletion
-- with an extra step and no delete policy needed.
--
-- The absence of an update policy is what stops it, and an absence is exactly
-- the kind of protection that a later migration removes by accident while
-- adding something else. Hence a test rather than a comment.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-class-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-class-beta', 'Beta');

insert into public.audit_events
  (tenant_id, actor_id, action, target_type, target_id, outcome, classification, created_at)
values
  -- Alpha: one of each class that matters to the sweep.
  ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'storage.upload.refused',
   'file', 'f1', 'denied', 'security', now() - interval '200 days'),
  ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'storage.object.downloaded',
   'file', 'f2', 'ok', 'activity', now() - interval '200 days'),
  ('00000000-0000-0000-0000-000000000001', 'user-alpha', 'storage.object.uploaded',
   'file', 'f3', 'ok', 'audit', now() - interval '10 days'),
  -- Beta: one security row, which Alpha must be unable to touch.
  ('00000000-0000-0000-0000-000000000002', 'user-beta', 'storage.object.delete_refused',
   'file', 'f4', 'denied', 'security', now() - interval '200 days');

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  visible integer;
  class   text;
begin
  select count(*) into visible from public.audit_events;
  if visible <> 3 then
    raise exception 'classification: expected 3 visible rows, saw %', visible;
  end if;

  -- The other tenant's security row is not visible at all, so it cannot be
  -- reclassified by a statement that names it.
  select count(*) into visible
    from public.audit_events where classification = 'security' and target_id = 'f4';
  if visible <> 0 then
    raise exception 'classification: another tenant''s security row was visible';
  end if;

  -- The one that matters: a tenant cannot downgrade its OWN security row to a
  -- class that expires sooner. There is no update policy for anyone, so the
  -- statement matches nothing rather than being refused -- assert on `found`.
  update public.audit_events
     set classification = 'activity'
   where target_id = 'f1';
  if found then
    raise exception 'classification: a tenant reclassified its own security row';
  end if;

  select classification into class from public.audit_events where target_id = 'f1';
  if class <> 'security' then
    raise exception 'classification: the class changed to %', class;
  end if;

  -- Nor upgrade one, which would be harmless here and is refused by the same
  -- absent policy. Asserting both directions keeps the claim about the policy
  -- rather than about this particular attack.
  update public.audit_events set classification = 'security' where target_id = 'f2';
  if found then
    raise exception 'classification: a tenant reclassified its own activity row';
  end if;

  -- And cannot reach across tenants, which the visibility check above already
  -- implies and this states directly.
  update public.audit_events
     set classification = 'activity'
   where tenant_id = '00000000-0000-0000-0000-000000000002';
  if found then
    raise exception 'classification: another tenant''s row was reclassified';
  end if;

  -- An insert naming another tenant is refused with or without a class.
  begin
    insert into public.audit_events
      (tenant_id, actor_id, action, target_type, target_id, outcome, classification)
    values ('00000000-0000-0000-0000-000000000002', 'user-alpha', 'storage.object.uploaded',
            'file', 'f5', 'ok', 'activity');
    raise exception 'classification: an insert into another tenant was admitted';
  exception
    when insufficient_privilege then null;
  end;

  raise notice 'audit classification isolation: ok';
end
$$;

-- The sweep's half: on the provisioning context, deleting by class and age
-- together removes exactly the rows that class allows and leaves the others.
-- Without this the test above would pass on a table nothing could ever sweep.
do $$
declare
  removed integer;
  left_over integer;
begin
  perform set_config('app.tenant_id', '', true);
  perform set_config('app.provisioning', 'on', true);

  -- Activity is kept ninety days; the 200-day row goes.
  with gone as (
    delete from public.audit_events
     where classification = 'activity' and created_at < now() - interval '90 days'
    returning id
  )
  select count(*) into removed from gone;
  if removed <> 1 then
    raise exception 'classification sweep: expected to remove 1 activity row, removed %', removed;
  end if;

  -- Security is kept three years; both 200-day security rows stay, including
  -- the other tenant's. The sweep is bounded by age, not by tenant.
  select count(*) into left_over
    from public.audit_events where classification = 'security';
  if left_over <> 2 then
    raise exception 'classification sweep: expected 2 security rows to survive, saw %', left_over;
  end if;

  -- And the sweep cannot rewrite a class either, on any context.
  update public.audit_events set classification = 'activity' where classification = 'security';
  if found then
    raise exception 'classification sweep: provisioning rewrote a class';
  end if;

  raise notice 'audit classification sweep: ok';
end
$$;

rollback;
