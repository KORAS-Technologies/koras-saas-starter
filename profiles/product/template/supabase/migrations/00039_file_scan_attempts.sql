-- Migration: 00039_file_scan_attempts   (secure_files, ADR 0013)
--
-- Semantically identical to Docoris migration 01016_file_scan_attempts, which is where
-- this was proven; a later sync of a product that already carries 01016 must find the
-- two schemas equivalent. docs/SECURE_FILES.md records the mapping.
--
-- Four additive columns on `public.files`: what is needed to say how often a pending
-- object was looked at, when, why it did not get a releasable verdict, and which object
-- a verdict applies to. This layer writes `scan_failure`, `scan_attempts` and
-- `scan_attempted_at` from the upload finalizer (a hold such as `integrity_mismatch` is a
-- reason too); `scan_object_etag` is written by the scanner that follows. This migration
-- changes no existing row's meaning.
--
-- Columns on `files` rather than a table beside it, for the reason 00018 gives: all of it
-- is current state about one row. RLS is therefore inherited from the already
-- enabled-and-forced `files` policies; no policy, grant or index changes here.
--
--   scan_attempts     smallint not null default 0, check >= 0. An operational counter.
--                     0 means "never actually attempted"; it does not mean scanned, and
--                     no existing file is reinterpreted by it.
--   scan_attempted_at timestamptz, null until an attempt is persisted.
--   scan_failure      text, null, closed set below. Why a pending object has not obtained
--                     a releasable verdict. NOT limited to faults: a deterministic hold
--                     (limit, incomplete inspection, no usable identity, a digest that is
--                     not the claim) is a reason too. Recording one never changes `status`
--                     or `scan_status`; the file stays pending.
--   scan_object_etag  text, null. Object identity / concurrency evidence for the object a
--                     verdict applies to. An ETag is NOT a content digest
--                     (`checksum_sha256` is the digest column) and is never compared
--                     with one.
--
-- scan_failure, the twelve values:
--   scanner_unavailable, scan_timeout, malformed_response, scanner_error,
--   object_unreachable, object_changed, integrity_mismatch, over_ceiling,
--   misconfigured, scan_limit_exceeded, inspection_incomplete, identity_insufficient.
-- `over_ceiling` (the object is above the scan size ceiling; no attempt counted) and
-- `scan_limit_exceeded` (the engine hit its own limit) are different causes and stay
-- different. `scan_exhausted` is deliberately absent: it is an audit action, not a state
-- of a file.
--
-- A check constraint, as 00018 does for every other vocabulary here. Adding a reason later
-- is one `drop constraint` and one `add constraint`. No upper bound on `scan_attempts` and
-- no constraint relating the columns to each other.
--
-- Existing rows: every new column takes its default or null, so no row changes status,
-- scan_status or any existing column. No index: an index arrives with the query that needs
-- it (00018's rule).
--
-- Idempotent: `add column if not exists`, and each constraint is dropped before it is added.
--
-- Reversal (this repository's migrations are forward-only): while nothing writes these
-- columns it is lossless --
--   alter table public.files
--     drop column if exists scan_object_etag, drop column if exists scan_failure,
--     drop column if exists scan_attempted_at, drop column if exists scan_attempts;
-- Once the finalizer writes them the values are lost, so that is a decision, not a routine.

begin;

alter table public.files
  add column if not exists scan_attempts smallint not null default 0,
  add column if not exists scan_attempted_at timestamptz,
  add column if not exists scan_failure text,
  add column if not exists scan_object_etag text;

alter table public.files drop constraint if exists files_scan_attempts_check;
alter table public.files add constraint files_scan_attempts_check
  check (scan_attempts >= 0);

alter table public.files drop constraint if exists files_scan_failure_check;
alter table public.files add constraint files_scan_failure_check
  check (scan_failure in (
    'scanner_unavailable', 'scan_timeout', 'malformed_response', 'scanner_error',
    'object_unreachable', 'object_changed', 'integrity_mismatch', 'over_ceiling',
    'misconfigured', 'scan_limit_exceeded', 'inspection_incomplete',
    'identity_insufficient'
  ));

commit;
