-- Whether a file's text reached the assistant's index, and if not, why.
--
-- Indexing runs after the upload's response, and until now its outcome went
-- to the log alone -- which on a busy service is gone within minutes, and
-- the question "why can't the assistant see my invoice" had no answer but
-- a guess. Two columns on the file row: when it was indexed, and a short
-- note when it was not. Both are written by the API on the tenant session
-- under the policies the table already has; nothing else changes.

alter table public.files
  add column if not exists indexed_at timestamptz,
  add column if not exists index_note text;
