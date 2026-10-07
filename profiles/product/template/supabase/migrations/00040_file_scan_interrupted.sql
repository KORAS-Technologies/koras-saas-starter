-- Migration: 00040_file_scan_interrupted   (secure_files, ADR 0013)
--
-- Semantically identical to Docoris migration 01017_file_scan_interrupted, where this was
-- proven; a later sync of a product that already carries 01017 must find the two schemas
-- equivalent. docs/SECURE_FILES.md records the mapping.
--
-- Two changes to `public.files`, both additive.
--
-- 1. `scan_failure` gains a thirteenth value, `scan_interrupted`: a scan attempt that was
--    counted and then cut short by the worker or the queue (the queue's own timeout
--    cancelling the job, or a worker shutting down) before the run reached an assessment.
--    It is a different cause from every other value -- `scan_timeout` is the *scanner's*
--    deadline, `object_unreachable` is the store -- and it stays distinct so an operator can
--    tell "the engine was too slow" from "the job was stopped under it". Recording it changes
--    neither `status` nor `scan_status`; the file stays pending and stays in the sweep. The
--    vocabulary is closed (00039), so this is the one `drop constraint` and one
--    `add constraint` that 00039 said adding a reason would be.
--
-- 2. A partial index for the sweep, which is the query 00039 deferred it for ("an index
--    arrives with the query that needs it"). The sweep reads only files that are ready and
--    pending, ordered by when they next fall due, and that predicate excludes almost every
--    row once a tenant's files have been scanned. 00041 replaces it with the due-time
--    indexes the tenant-fair selection actually reads.
--
-- No existing row changes. No policy or grant changes: RLS is inherited from `files`, and
-- the sweep reads through `files_select_provisioning` (00021).
--
-- Reversal (forward-only): drop the index; restore the twelve-value constraint -- which
-- fails while a row holds `scan_interrupted`, so that is a decision once the scanner has
-- run, not a routine:
--   drop index if exists public.files_scan_pending_idx;
--   alter table public.files drop constraint files_scan_failure_check;
--   alter table public.files add constraint files_scan_failure_check check (scan_failure in (
--     'scanner_unavailable', 'scan_timeout', 'malformed_response', 'scanner_error',
--     'object_unreachable', 'object_changed', 'integrity_mismatch', 'over_ceiling',
--     'misconfigured', 'scan_limit_exceeded', 'inspection_incomplete',
--     'identity_insufficient'));

begin;

alter table public.files drop constraint if exists files_scan_failure_check;
alter table public.files add constraint files_scan_failure_check
  check (scan_failure in (
    'scanner_unavailable', 'scan_timeout', 'malformed_response', 'scanner_error',
    'object_unreachable', 'object_changed', 'integrity_mismatch', 'over_ceiling',
    'misconfigured', 'scan_limit_exceeded', 'inspection_incomplete',
    'identity_insufficient', 'scan_interrupted'
  ));

create index if not exists files_scan_pending_idx
  on public.files (created_at, id)
  include (scan_attempts, scan_attempted_at, size_bytes, tenant_id)
  where status = 'ready' and scan_status = 'pending';

commit;
