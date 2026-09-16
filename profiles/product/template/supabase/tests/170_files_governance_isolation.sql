-- Governance columns: a hold, a digest and a retention date are as tenant-scoped
-- as the row that carries them.
--
-- 050 proves the row is isolated. This proves the columns 00018 added are
-- isolated too, which is not the same claim: the policies are written against
-- `tenant_id` and every new column rides on them, so the thing worth asserting
-- is that nobody added a column and reached it another way. A legal hold one
-- tenant can clear on another tenant's object is the whole mechanism defeated.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-gov-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-gov-beta', 'Beta');

insert into public.files
  (tenant_id, storage_key, name, size_bytes, status, uploaded_by,
   category, classification, checksum_sha256, legal_hold, retain_until)
values
  ('00000000-0000-0000-0000-000000000001', 'tenants/alpha/documents/a/alpha.pdf',
   'alpha.pdf', 10, 'ready', 'user-alpha',
   'documents', 'standard', 'aaaa', false, now() - interval '1 day'),
  ('00000000-0000-0000-0000-000000000002', 'tenants/beta/documents/b/beta.pdf',
   'beta.pdf', 20, 'ready', 'user-beta',
   'documents', 'restricted', 'bbbb', true, now() - interval '1 day');

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  visible integer;
  held    boolean;
begin
  -- The other tenant's digest and classification are not readable.
  select count(*) into visible from public.files where checksum_sha256 = 'bbbb';
  if visible <> 0 then
    raise exception 'governance: another tenant''s checksum was visible';
  end if;

  select count(*) into visible from public.files where classification = 'restricted';
  if visible <> 0 then
    raise exception 'governance: another tenant''s classification was visible';
  end if;

  -- A hold on another tenant's object cannot be lifted from here. This is the
  -- one that matters: lifting a hold is what makes a purge possible.
  update public.files set legal_hold = false where name = 'beta.pdf';
  if found then
    raise exception 'governance: another tenant''s legal hold was lifted';
  end if;

  -- Nor can its retention be shortened to bring a purge forward.
  update public.files set retain_until = now() - interval '10 years'
   where name = 'beta.pdf';
  if found then
    raise exception 'governance: another tenant''s retention was shortened';
  end if;

  -- The tenant's own row is writable, so the refusals above are the policy
  -- and not a column that nothing can update.
  update public.files set legal_hold = true where name = 'alpha.pdf';
  if not found then
    raise exception 'governance: a tenant could not hold its own object';
  end if;
  select legal_hold into held from public.files where name = 'alpha.pdf';
  if not held then
    raise exception 'governance: the hold did not take';
  end if;

  -- An insert naming another tenant is refused with the new columns too.
  begin
    insert into public.files
      (tenant_id, storage_key, name, size_bytes, uploaded_by, category, legal_hold)
    values ('00000000-0000-0000-0000-000000000002', 'tenants/beta/documents/x/x.pdf',
            'x.pdf', 1, 'user-alpha', 'documents', true);
    raise exception 'governance: an insert into another tenant was admitted';
  exception
    when insufficient_privilege then null;
  end;

  raise notice 'files governance isolation: ok';
end
$$;

rollback;
