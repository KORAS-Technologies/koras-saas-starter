-- Migration: 00042_file_derived_content_withdrawal
--
-- `secure_files` (ADR 0013), the release layer. Docoris 01019 (OD-10 S2): the same
-- semantics. What the assistant derived from a file's content -- its chunks and
-- embeddings -- must not outlive the file's right to be released.
--
-- When a `ready` + `clean` file stops being so (`scan_status` leaves `clean`, or
-- `status` leaves `ready`), and in the SAME statement, its rows in
-- `public.ai_knowledge_chunks` are deleted and its index state (`indexed_at`,
-- `index_note`) is cleared. A late `clean -> infected` verdict, a future
-- `clean -> pending` on replaced bytes, and an archive all do this, whichever
-- module writes them: the scanner is not edited and cannot forget it. The purge
-- and the verdict are one transaction, so neither can exist without the other.
--
-- Why a BEFORE UPDATE row trigger:
--   * it can clear `indexed_at`/`index_note` on the row being written, with no
--     second UPDATE (which would re-enter the trigger and the scanner's guards);
--   * it fires after the writer holds the row's lock (the scanner takes
--     `select ... for update` first), which is what the indexer's share lock
--     serialises against (core/knowledge.py `_WRITE_GUARD`);
--   * the WHEN clause makes it fire for nothing else: every `files` write that
--     keeps a file clean, or touches a file that was never clean, is unaffected.
--
-- Why SECURITY DEFINER, with a pinned search_path: the delete must not depend on
-- the writer's tenant binding or on its table privileges. `tenant_id` is named
-- explicitly, so it can only ever remove the chunks of the row's own tenant. It
-- takes no argument and returns the row; it is not callable as a function.
--
-- A product generated with `secure_files` and without `ai` has no
-- `ai_knowledge_chunks`: the delete is skipped there (`to_regclass`), and the trigger
-- still clears the two index columns, which exist on `files` in every product. That is
-- the one difference from 01019, which only ever ran where the table exists.
--
-- The function's OWNER must bypass row-level security (a superuser, or a role with
-- BYPASSRLS such as Supabase's `postgres`). `files` and `ai_knowledge_chunks` have RLS
-- forced, and a SECURITY DEFINER function runs as its owner: an owner that does not bypass
-- RLS would delete only the rows the *writer's* tenant binding allows, i.e. nothing, and the
-- withdrawal would silently do nothing. The migrate role creates the function, so it is the
-- owner; `supabase/tests/360_file_derived_content_withdrawal.sql` fails loudly if the owner
-- cannot bypass RLS.
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
--
-- What it does not do: it does not write `scan_status`; it adds no column, no index and
-- no policy. A file that is deleted still has its chunks removed by the Files route
-- (`before_delete`).

begin;

-- Replacing the function is instant; the two triggers below take a SHARE ROW EXCLUSIVE lock on
-- `files`. Give up rather than queue behind a long transaction.
set local lock_timeout = '5s';

create or replace function public.withdraw_file_derived_content()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
begin
  if to_regclass('public.ai_knowledge_chunks') is not null then
    delete from public.ai_knowledge_chunks
     where tenant_id = old.tenant_id
       and resource_type = 'file'
       and resource_id = old.id::text;
  end if;
  if tg_op = 'DELETE' then
    return old;
  end if;
  new.indexed_at := null;
  new.index_note := null;
  return new;
end;
$$;

revoke all on function public.withdraw_file_derived_content() from public;
-- Supabase's default privileges also grant EXECUTE to these three. A trigger function
-- cannot be called as a function, so this is hygiene, not a control.
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    revoke all on function public.withdraw_file_derived_content() from anon;
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    revoke all on function public.withdraw_file_derived_content() from authenticated;
  end if;
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    revoke all on function public.withdraw_file_derived_content() from service_role;
  end if;
end $$;

comment on function public.withdraw_file_derived_content() is
  'secure_files: deletes a file''s chunks and clears its index state in the statement that '
  'ends its releasable state (ready + clean). Trigger function; see 00042.';

drop trigger if exists files_withdraw_derived_content on public.files;
create trigger files_withdraw_derived_content
  before update on public.files
  for each row
  when (
    old.status = 'ready' and old.scan_status = 'clean'
    and not (new.status = 'ready' and new.scan_status = 'clean')
  )
  execute function public.withdraw_file_derived_content();

-- A row-DELETE of a file ends its right to be released as completely as a verdict
-- does, and `ai_knowledge_chunks` has no foreign key to `files`. The Files route and
-- the assistant's delete tool remove the chunks first, but that order can race an
-- index write that holds the file's share lock: the chunks the indexer commits after
-- the route's delete would be orphaned. The BEFORE DELETE trigger runs with the row
-- lock held, so it serialises with the indexer's share lock and removes them last.
drop trigger if exists files_withdraw_derived_content_on_delete on public.files;
create trigger files_withdraw_derived_content_on_delete
  before delete on public.files
  for each row
  execute function public.withdraw_file_derived_content();

commit;
