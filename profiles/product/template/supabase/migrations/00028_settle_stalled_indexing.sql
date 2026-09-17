-- Files that have been "Indexing…" since before anything indexed them.
--
-- The Files page reads three states from two columns: `indexed_at` set means
-- searchable, `index_note` set means it was tried and did not work, and
-- neither means the attempt is still in flight. That third state is the
-- honest one *while an upload is being read* -- which takes seconds.
--
-- It is not honest a week later. On the dev estate on 2026-09-17 every one of
-- nine files had both columns null and the oldest had been "Indexing…" since
-- 9 September: they were uploaded before the assistant's hook existed, so no
-- attempt was ever scheduled and no outcome was ever recorded. A fresh upload
-- the same afternoon was indexed in eight seconds, which is what proved the
-- feature works and the rows were simply stranded.
--
-- A row with no outcome and an upload older than an hour was never going to
-- get one. Saying so is the whole change: `index_note` becomes a sentence, the
-- page reads "Not searchable" with the reason behind it, and the customer stops
-- being told that something is in progress.
--
-- Bounded by the hour so that a genuine in-flight upload is never overwritten,
-- and idempotent: run it twice and the second finds nothing, because the first
-- filled the column it selects on.
--
-- This settles the rows that exist. `FilesPanel` stops the state becoming
-- permanent again, by reading a long-untouched pending as unknown rather than
-- as progress.

update public.files
   set index_note = 'this file was uploaded before the assistant indexed uploads, so it was never read'
 where indexed_at is null
   and index_note is null
   and created_at < now() - interval '1 hour';
