-- Upload finalization: what the finalizer's own statements may touch, under forced RLS.
--
-- 00039 added the columns a finalization attempt writes (`scan_attempts`,
-- `scan_attempted_at`, `scan_failure`) and the vocabulary that bounds one of them. The
-- finalizer (`uploads/finalize.py`) and its job (`tasks/finalize.py`) read and write them as
-- the file's own tenant. Four things are asserted, against the shape of those statements:
--
--   * the swap from an incoming key to a final one applies to the tenant's own ready, pending
--     row, and to nobody else's -- another tenant's file is not reachable by id, and a row that
--     is no longer waiting on that incoming key is not swapped (the compare-and-set);
--   * the attempt counter and the hold word are writable by the tenant on its own row only;
--   * the hold word is a closed vocabulary: a word nobody declared is refused by the database;
--   * nothing a tenant writes here can make a file `clean` -- the swap and the hold leave
--     `scan_status` exactly as it was.

\set ON_ERROR_STOP on

begin;

set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

insert into public.tenants (id, slug, name)
values
  ('00000000-0000-0000-0000-000000000001', 'rls-fin-alpha', 'Alpha'),
  ('00000000-0000-0000-0000-000000000002', 'rls-fin-beta', 'Beta');

insert into public.files
  (id, tenant_id, storage_key, name, size_bytes, status, scan_status, uploaded_by,
   checksum_sha256)
values
  ('a0000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001',
   'tenants/00000000-0000-0000-0000-000000000001/documents/a0000000-0000-0000-0000-000000000001/incoming/u1/a.csv',
   'a.csv', 10, 'ready', 'pending', 'user-alpha', repeat('a', 64)),
  ('b0000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000002',
   'tenants/00000000-0000-0000-0000-000000000002/documents/b0000000-0000-0000-0000-000000000002/incoming/u2/b.csv',
   'b.csv', 10, 'ready', 'pending', 'user-beta', repeat('b', 64));

set local role koras_rls_test;
set local app.tenant_id = '00000000-0000-0000-0000-000000000001';

do $$
declare
  touched integer;
begin
  -- The finalizer's swap, in shape: compare-and-set on the incoming key.
  update public.files
     set storage_key = 'tenants/x/documents/a/final/g/a.csv', checksum_verified_at = now(),
         backup_status = 'none', backed_up_at = null
   where id = cast('a0000000-0000-0000-0000-000000000001' as uuid)
     and tenant_id = cast('00000000-0000-0000-0000-000000000001' as uuid)
     and status = 'ready' and scan_status = 'pending'
     and storage_key =
       'tenants/00000000-0000-0000-0000-000000000001/documents/a0000000-0000-0000-0000-000000000001/incoming/u1/a.csv';
  get diagnostics touched = row_count;
  if touched <> 1 then
    raise exception 'finalization: the tenant''s own swap touched % rows', touched;
  end if;

  -- The same swap a second time finds the row no longer waiting on that key: nothing applies.
  update public.files
     set storage_key = 'tenants/x/documents/a/final/g2/a.csv'
   where id = cast('a0000000-0000-0000-0000-000000000001' as uuid)
     and status = 'ready' and scan_status = 'pending'
     and storage_key =
       'tenants/00000000-0000-0000-0000-000000000001/documents/a0000000-0000-0000-0000-000000000001/incoming/u1/a.csv';
  get diagnostics touched = row_count;
  if touched <> 0 then
    raise exception 'finalization: a stale compare-and-set swapped % rows', touched;
  end if;

  raise notice 'finalization swap: ok';
end
$$;

do $$
declare
  touched integer;
  seen    text;
begin
  -- Another tenant's file is not reachable by its id, by the swap, the counter or the hold.
  update public.files set storage_key = 'tenants/x/documents/b/final/g/b.csv'
   where id = cast('b0000000-0000-0000-0000-000000000002' as uuid);
  get diagnostics touched = row_count;
  if touched <> 0 then
    raise exception 'finalization: another tenant''s file was swapped';
  end if;

  update public.files set scan_attempts = scan_attempts + 1, scan_failure = 'integrity_mismatch'
   where id = cast('b0000000-0000-0000-0000-000000000002' as uuid);
  get diagnostics touched = row_count;
  if touched <> 0 then
    raise exception 'finalization: another tenant''s file was held';
  end if;

  -- Its own: counted, and held with a word of the vocabulary.
  update public.files
     set scan_attempts = least(scan_attempts + 1, 32767), scan_attempted_at = now()
   where id = cast('a0000000-0000-0000-0000-000000000001' as uuid);
  update public.files set scan_failure = 'object_unreachable'
   where id = cast('a0000000-0000-0000-0000-000000000001' as uuid);

  select scan_status into seen from public.files
   where id = cast('a0000000-0000-0000-0000-000000000001' as uuid);
  if seen <> 'pending' then
    raise exception 'finalization: a hold or a swap changed scan_status to %', seen;
  end if;

  raise notice 'finalization isolation: ok';
end
$$;

do $$
begin
  -- A word nobody declared is refused by the database, not by whoever wrote the statement.
  begin
    update public.files set scan_failure = 'looks_fine_to_me'
     where id = cast('a0000000-0000-0000-0000-000000000001' as uuid);
    raise exception 'finalization: an undeclared failure word was accepted';
  exception when check_violation then
    null;
  end;

  begin
    update public.files set scan_attempts = -1
     where id = cast('a0000000-0000-0000-0000-000000000001' as uuid);
    raise exception 'finalization: a negative attempt count was accepted';
  exception when check_violation then
    null;
  end;

  raise notice 'finalization vocabulary: ok';
end
$$;

rollback;
