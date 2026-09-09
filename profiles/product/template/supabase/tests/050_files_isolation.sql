-- Files: one tenant's index never shows, admits or loses another's rows.
--
-- The same shape as 020, for the table the Files module writes. Reads and
-- writes both, because a policy with `using` and no `with check` would let an
-- upload be recorded against another tenant while refusing to list it back --
-- which looks like success to the caller and is a leak to the other tenant.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-files-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-files-beta', 'Beta');

insert into public.files (tenant_id, storage_key, name, size_bytes, status, uploaded_by)
values
  ('00000000-0000-0000-0000-000000000001', 'tenants/alpha/a/alpha.pdf', 'alpha.pdf', 10, 'ready', 'user-alpha'),
  ('00000000-0000-0000-0000-000000000002', 'tenants/beta/b/beta.pdf', 'beta.pdf', 20, 'ready', 'user-beta');

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  visible integer;
begin
  select count(*) into visible from public.files;
  if visible <> 1 then
    raise exception 'files: expected 1 visible row, saw %', visible;
  end if;

  select count(*) into visible from public.files where name = 'beta.pdf';
  if visible <> 0 then
    raise exception 'files: another tenant''s file was visible';
  end if;

  -- An insert naming the other tenant must be refused, not stored unseen.
  begin
    insert into public.files (tenant_id, storage_key, name, size_bytes, uploaded_by)
    values ('00000000-0000-0000-0000-000000000002', 'tenants/beta/x/x.pdf', 'x.pdf', 1, 'user-alpha');
    raise exception 'files: an insert into another tenant was admitted';
  exception
    when insufficient_privilege then null;
  end;

  -- A delete aimed at the other tenant's row touches nothing.
  delete from public.files where name = 'beta.pdf';
  if found then
    raise exception 'files: another tenant''s file was deleted';
  end if;

  -- An update cannot move a row to another tenant.
  begin
    update public.files
       set tenant_id = '00000000-0000-0000-0000-000000000002'
     where name = 'alpha.pdf';
    raise exception 'files: a row was moved to another tenant';
  exception
    when insufficient_privilege then null;
  end;

  raise notice 'files isolation: ok';
end
$$;

rollback;
