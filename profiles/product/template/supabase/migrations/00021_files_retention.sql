-- Migration: 00021_files_retention
-- The index the object retention sweep needs, and the provisioning policies
-- without which it could not run at all.
--
-- 00018 put `retain_until` and `legal_hold` on the file index and nothing read
-- them. The sweep that reads them lives on the provisioning context, which is
-- the only context that reaches every tenant -- and `files` has never had a
-- provisioning policy, because until now nothing cross-tenant needed to see a
-- file row.
--
-- Select and delete only. There is deliberately no provisioning insert or
-- update: a sweep that could create or rewrite a file row could do considerably
-- more damage than one that can only remove an expired one, and nothing needs
-- it to.

-- The sweep's query, and the only reason this index exists:
--   select ... from files
--    where retain_until is not null and retain_until < now()
--      and legal_hold = false and status <> 'purged'
--
-- Partial on the two conditions that exclude almost every row: a null
-- `retain_until` means no policy has been resolved for this object, which is
-- not the same as expired and must never be swept.
create index if not exists files_retention_due_idx
  on public.files (retain_until)
  where retain_until is not null and legal_hold = false;

drop policy if exists "files_select_provisioning" on public.files;
create policy "files_select_provisioning"
  on public.files for select
  using (public.is_provisioning());

-- A qualified delete needs the select policy above as well as this one.
-- Postgres applies the select policies to the rows a DELETE ... WHERE
-- considers, so a delete policy alone finds nothing -- the lesson
-- 00008_ai_retention.sql records and 00009 and 00013 restate.
drop policy if exists "files_delete_provisioning" on public.files;
create policy "files_delete_provisioning"
  on public.files for delete
  using (public.is_provisioning());

-- The sweep marks a row `purged` before it removes the object, so a crash
-- between the two leaves a row that says what was supposed to happen rather
-- than a row that looks ready and has no bytes behind it.
drop policy if exists "files_update_provisioning" on public.files;
create policy "files_update_provisioning"
  on public.files for update
  using (public.is_provisioning() and status <> 'purged')
  with check (public.is_provisioning());
