-- Migration: 00041_file_scan_due_indexes   (secure_files, ADR 0013)
--
-- Semantically identical to Docoris migration 01018_file_scan_due_indexes, where this was
-- proven; a later sync of a product that already carries 01018 must find the two schemas
-- equivalent. docs/SECURE_FILES.md records the mapping.
--
-- The reconciliation sweep selects ready, pending files that are due for another attempt.
-- 00040 gave it an index on `(created_at, id)`, which cannot serve that: a file's due time is
-- not its creation time once it has been attempted, so every page computed the due time for
-- the whole pending set and sorted it. That cost grows with the pending population, every
-- five minutes, for ever (files that no scanner will ever clear stay pending and stay in the
-- set).
--
-- The due time is
--
--   never attempted:  created_at + 1260 s            (the 16 minute upload window + 5 min)
--   attempted:        scan_attempted_at + least(720 s * 2^(attempts - 1), 3600 s)
--
-- and this migration indexes that expression itself, in UTC, so the sweep reads the next few
-- due rows from the front of an index instead of sorting the pending set. Two partial
-- indexes, both on `status = 'ready' and scan_status = 'pending'` and
-- `size_bytes <= 104857600` (the fixed 100 MiB scan ceiling, which is what the clamd service
-- is configured for: a larger file is held `over_ceiling` for ever and would otherwise be
-- stepped over on every run):
--
--   files_scan_due_idx         (due, id)             the oldest due file overall, which
--                                                    names the tenant served first
--   files_scan_due_tenant_idx  (tenant_id, due, id)  tenants that have a due file, and
--                                                    one tenant's next due files
--
-- The expression is written to be IMMUTABLE (an index requires it): `AT TIME ZONE 'UTC'` and
-- `make_interval`, never `timestamptz + interval`, which is only stable. The sweep
-- (`koras_worker.tasks.scan_sweep.due_expression`) builds its queries from the same text with
-- the same inlined constants -- an expression index is used only for the same expression --
-- and a test compares the two and asks the planner. 1260 is `SCAN_READ_DELAY_SECONDS + 300`;
-- changing the upload window or the back-off is a new migration, not an edit of this one.
--
-- 00040's `files_scan_pending_idx` is dropped: nothing reads it any more.
--
-- No row changes. No policy or grant changes: RLS is inherited from `files`.
--
-- Reversal (forward-only):
--   drop index if exists public.files_scan_due_tenant_idx, public.files_scan_due_idx;
--   create index if not exists files_scan_pending_idx
--     on public.files (created_at, id)
--     include (scan_attempts, scan_attempted_at, size_bytes, tenant_id)
--     where status = 'ready' and scan_status = 'pending';

begin;

-- The index builds take a SHARE lock on `files`. Give up rather than queue behind a long
-- transaction and stall every writer; the deploy fails visibly and is retried.
set local lock_timeout = '5s';

drop index if exists public.files_scan_pending_idx;

create index if not exists files_scan_due_idx
  on public.files (
    (case when scan_attempted_at is null then (created_at at time zone 'UTC') + make_interval(secs => 1260) else (scan_attempted_at at time zone 'UTC') + make_interval(secs => least(720 * power(2, least(greatest(scan_attempts - 1, 0), 10)), 3600)) end),
    id
  )
  where status = 'ready' and scan_status = 'pending' and size_bytes <= 104857600;

create index if not exists files_scan_due_tenant_idx
  on public.files (
    tenant_id,
    (case when scan_attempted_at is null then (created_at at time zone 'UTC') + make_interval(secs => 1260) else (scan_attempted_at at time zone 'UTC') + make_interval(secs => least(720 * power(2, least(greatest(scan_attempts - 1, 0), 10)), 3600)) end),
    id
  )
  where status = 'ready' and scan_status = 'pending' and size_bytes <= 104857600;

commit;
