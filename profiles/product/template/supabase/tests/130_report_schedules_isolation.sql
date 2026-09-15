-- Schedules and exports: a tenant sees and manages its own; the worker reads
-- every schedule and records a run on it, creates none, and sees no export.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-sched-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-sched-beta', 'Beta');

insert into public.report_schedules
  (id, tenant_id, report_key, cadence, format, recipients, created_by, next_run_at)
values
  ('40000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001',
   'usage.overview', 'weekly', 'csv', array['a@example.com'], 'user-alpha', now() - interval '1 hour'),
  ('40000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000002',
   'usage.overview', 'monthly', 'pdf', array['b@example.com'], 'user-beta', now() + interval '1 day');

insert into public.report_exports (id, tenant_id, report_key, format, filename, requested_by)
values
  ('50000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001',
   'usage.quotas', 'csv', 'usage-quotas.csv', 'user-alpha'),
  ('50000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000002',
   'usage.quotas', 'csv', 'usage-quotas.csv', 'user-beta');

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  visible integer;
begin
  select count(*) into visible from public.report_schedules;
  if visible <> 1 then
    raise exception 'schedules: tenant alpha sees %, expected its own 1', visible;
  end if;
  select count(*) into visible from public.report_exports;
  if visible <> 1 then
    raise exception 'exports: tenant alpha sees %, expected its own 1', visible;
  end if;

  begin
    insert into public.report_schedules
      (tenant_id, report_key, cadence, recipients, created_by, next_run_at)
    values ('00000000-0000-0000-0000-000000000002', 'usage.overview', 'daily',
            array['x@example.com'], 'user-alpha', now());
    raise exception 'schedules: a schedule was written into another tenant';
  exception
    when insufficient_privilege then null;
  end;

  update public.report_schedules set active = false
   where id = '40000000-0000-0000-0000-000000000002';
  if found then
    raise exception 'schedules: another tenant''s schedule was changed';
  end if;

  delete from public.report_schedules where id = '40000000-0000-0000-0000-000000000001';
  if not found then
    raise exception 'schedules: a tenant could not remove its own schedule';
  end if;

  raise notice 'schedules and exports isolation: ok';
end
$$;

-- The worker, on the provisioning context: reads what is due across tenants,
-- records the run, creates nothing, sees no export.
select set_config('app.tenant_id', '', true) as _;
select set_config('app.provisioning', 'on', true) as _;

do $$
declare
  visible integer;
begin
  select count(*) into visible from public.report_schedules where active;
  if visible <> 1 then
    raise exception 'schedules: the worker sees % schedules, expected the 1 left', visible;
  end if;

  update public.report_schedules
     set last_run_at = now(), next_run_at = now() + interval '1 month'
   where id = '40000000-0000-0000-0000-000000000002';
  if not found then
    raise exception 'schedules: the worker could not record a run';
  end if;

  begin
    insert into public.report_schedules
      (tenant_id, report_key, cadence, recipients, created_by, next_run_at)
    values ('00000000-0000-0000-0000-000000000002', 'usage.overview', 'daily',
            array['x@example.com'], 'worker', now());
    raise exception 'schedules: the worker created a schedule';
  exception
    when insufficient_privilege then null;
  end;

  select count(*) into visible from public.report_exports;
  if visible <> 0 then
    raise exception 'exports: the worker sees % exports, expected none', visible;
  end if;

  raise notice 'worker reads and records schedules, and nothing more: ok';
end
$$;

rollback;
