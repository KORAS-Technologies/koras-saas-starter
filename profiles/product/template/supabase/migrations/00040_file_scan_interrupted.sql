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
--
-- Operating notes (secure_files migrations 00039-00042 share them):
--   * Forward-only. There is no down migration; the "Reversal" notes are for a person to decide
--     on, not for a tool to run.
--   * Deploy order is MIGRATE THEN DEPLOY: a secure_files release assumes these columns,
--     indexes and the trigger exist, and a schema that is ahead of the code is harmless to
--     the code that does not know about it.
--   * `lock_timeout` is set for the transaction: if `files` is held by a long transaction the
--     migration gives up with an error instead of queuing behind it and stalling every writer.
--     The ledger row is written only after a migration succeeds and the statements are
--     idempotent, so the next `migrate` simply retries.
--   * This migration re-adds the THIRTEEN-value `scan_failure` constraint (00039's twelve plus
--     `scan_interrupted`). A product that has widened that constraint with reasons of its own
--     must reconcile before applying it: `drop constraint` then `add constraint` here replaces
--     the whole list, so a product-added word would make the new constraint fail on existing
--     rows, or be silently refused afterwards. Add the product's words in a later migration,
--     and carry them in the sync record.
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

-- The constraint swap takes ACCESS EXCLUSIVE and validates every row; the index build takes a
-- SHARE lock. Give up rather than queue behind a long transaction.
set local lock_timeout = '5s';

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
