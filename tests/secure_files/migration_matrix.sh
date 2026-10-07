#!/usr/bin/env bash
# The secure_files migration matrix (ADR 0013), run against a real PostgreSQL.
#
#   A  fresh product generated WITH secure_files: every migration applies through the
#      product's own `local/scripts/migrate.sh`, the secure objects exist, and the
#      row-level security suites pass.
#   B  fresh DEFAULT product: the same path, and none of the objects migrations
#      00039-00042 create exist, nor do the files that carry the capability.
#   C  upgrade: a default product generated from the commit BEFORE this branch is
#      migrated and given realistic legacy file rows; then the secure product's own
#      migrate script applies exactly 00039-00042. Nothing is lost, the re-run is
#      idempotent, no legacy row is releasable under the secure rule, row-level security
#      is still forced and the suites still pass.
#   D  a secure product generated WITHOUT the assistant, which later enables `ai`: the
#      assistant's own migrations (00006-00012, numbered BEFORE 00042) are applied AFTER 00042
#      has been in force, and the withdrawal trigger -- which skipped the chunk delete while
#      `ai_knowledge_chunks` did not exist -- must start deleting the moment the table does.
#
# Inputs (environment):
#   SECURE_DIR    a product generated with `--with secure_files,clamd,worker`
#   DEFAULT_DIR   a default product generated from this commit
#   BASELINE_DIR  a default product generated from the merge-base with develop
#   PGHOST PGPORT PGUSER and the libpq password variable: an administrative connection
#
# Every assertion prints what it checks. Any failure exits non-zero; nothing is skipped.
set -euo pipefail

: "${SECURE_DIR:?}" "${DEFAULT_DIR:?}" "${BASELINE_DIR:?}"
# The product the upgrade moves to. It is generated with the same components as the baseline
# plus secure_files, so the only migrations it adds are 00039-00042.
UPGRADE_DIR="${UPGRADE_DIR:-$SECURE_DIR}"
export PGHOST="${PGHOST:-localhost}" PGUSER="${PGUSER:-postgres}" PGPORT="${PGPORT:-5432}"
WORK="${RUNNER_TEMP:-/tmp}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAILED=0

# The credential travels in the environment (libpq reads it); a URL never carries it.
url() { echo "postgresql://${PGUSER}@${PGHOST}:${PGPORT}/$1"; }
sql() { local db="$1"; shift; psql -X -v ON_ERROR_STOP=1 -q -tA -d "$db" "$@"; }
newdb() { sql postgres -c "drop database if exists $1" -c "create database $1"; }

check() { # check <db> <description> <boolean sql>
  local got
  got="$(sql "$1" -c "$3")"
  if [ "$got" = "t" ]; then echo "  ok    $2"; else echo "::error::FAILED: $2 (got '$got')"; FAILED=1; fi
}

migrate() { # migrate <db> <product dir>
  MIGRATE_DATABASE_URL="$(url "$1")" bash "$2/local/scripts/migrate.sh" >"$WORK/migrate.out" 2>&1 \
    || { cat "$WORK/migrate.out"; echo "::error::migrate.sh failed for $2"; exit 1; }
  cat "$WORK/migrate.out"
}

rls_suites() { # rls_suites <db> <product dir>
  sql "$1" <<'SQL'
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'koras_rls_test') then
    create role koras_rls_test nologin nobypassrls;
  end if;
end
$$;
grant usage on schema public to koras_rls_test;
grant select, insert, update, delete on all tables in schema public to koras_rls_test;
SQL
  local count=0
  for file in "$2"/supabase/tests/*.sql; do
    echo "  --> $(basename "$file")"
    psql -X -v ON_ERROR_STOP=1 -v app_role=koras_rls_test -q -d "$1" -f "$file" >/dev/null
    count=$((count + 1))
  done
  [ "$count" -gt 0 ] || { echo "::error::no RLS suites found in $2"; exit 1; }
  echo "  ok    $count row-level security suites passed on $1"
}

SECURE_MIGRATIONS=(00039_file_scan_attempts 00040_file_scan_interrupted 00041_file_scan_due_indexes 00042_file_derived_content_withdrawal)

secure_objects_present() { # <db> <label>
  local db="$1"
  check "$db" "$2: files has scan_attempts, scan_attempted_at, scan_failure, scan_object_etag" \
    "select count(*) = 4 from information_schema.columns where table_schema = 'public' and table_name = 'files' and column_name in ('scan_attempts','scan_attempted_at','scan_failure','scan_object_etag')"
  check "$db" "$2: scan_attempts is smallint not null default 0" \
    "select data_type = 'smallint' and is_nullable = 'NO' and column_default = '0' from information_schema.columns where table_schema = 'public' and table_name = 'files' and column_name = 'scan_attempts'"
  check "$db" "$2: scan_failure check holds the thirteen reasons including scan_interrupted" \
    "select pg_get_constraintdef(oid) like '%scan_interrupted%' and pg_get_constraintdef(oid) like '%identity_insufficient%' from pg_constraint where conname = 'files_scan_failure_check' and conrelid = 'public.files'::regclass"
  check "$db" "$2: files_scan_attempts_check exists" \
    "select count(*) = 1 from pg_constraint where conname = 'files_scan_attempts_check' and conrelid = 'public.files'::regclass"
  check "$db" "$2: the two due-time indexes exist and are partial" \
    "select count(*) = 2 from pg_indexes where schemaname = 'public' and tablename = 'files' and indexname in ('files_scan_due_idx','files_scan_due_tenant_idx') and indexdef like '% WHERE %'"
  check "$db" "$2: the superseded 00040 index is gone" \
    "select count(*) = 0 from pg_indexes where schemaname = 'public' and indexname = 'files_scan_pending_idx'"
  check "$db" "$2: the withdrawal function is security definer with a pinned search_path" \
    "select prosecdef and array_to_string(proconfig, ',') like 'search_path=%' from pg_proc where oid = 'public.withdraw_file_derived_content()'::regprocedure"
  check "$db" "$2: the withdrawal function is not executable by public" \
    "select not has_function_privilege('public', 'public.withdraw_file_derived_content()', 'execute')"
  check "$db" "$2: both withdrawal triggers exist on files" \
    "select count(*) = 2 from pg_trigger where tgrelid = 'public.files'::regclass and tgname in ('files_withdraw_derived_content','files_withdraw_derived_content_on_delete') and not tgisinternal"
  check "$db" "$2: row-level security is enabled and forced on files" \
    "select relrowsecurity and relforcerowsecurity from pg_class where oid = 'public.files'::regclass"
  check "$db" "$2: files still has policies" \
    "select count(*) >= 3 from pg_policies where schemaname = 'public' and tablename = 'files'"
}

secure_objects_absent() { # <db> <label>
  local db="$1"
  check "$db" "$2: files has none of the secure scan columns" \
    "select count(*) = 0 from information_schema.columns where table_schema = 'public' and table_name = 'files' and column_name in ('scan_attempts','scan_attempted_at','scan_failure','scan_object_etag')"
  check "$db" "$2: no secure constraint or index exists" \
    "select (select count(*) from pg_constraint where conname in ('files_scan_attempts_check','files_scan_failure_check')) + (select count(*) from pg_indexes where indexname in ('files_scan_due_idx','files_scan_due_tenant_idx','files_scan_pending_idx')) = 0"
  check "$db" "$2: no withdrawal function or trigger exists" \
    "select (select count(*) from pg_proc where proname = 'withdraw_file_derived_content') + (select count(*) from pg_trigger where tgname like 'files_withdraw_derived_content%') = 0"
  check "$db" "$2: the migration ledger names none of 00039-00042" \
    "select count(*) = 0 from public.schema_migrations where version ~ '^0003[9]_|^0004[0-2]_'"
  check "$db" "$2: row-level security is still enabled and forced on files" \
    "select relrowsecurity and relforcerowsecurity from pg_class where oid = 'public.files'::regclass"
}

echo "=== A. fresh product WITH secure_files"
newdb koras_matrix_a
migrate koras_matrix_a "$SECURE_DIR"
check koras_matrix_a "A: the ledger holds all four secure migrations" \
  "select count(*) = 4 from public.schema_migrations where version in ('${SECURE_MIGRATIONS[0]}','${SECURE_MIGRATIONS[1]}','${SECURE_MIGRATIONS[2]}','${SECURE_MIGRATIONS[3]}')"
secure_objects_present koras_matrix_a A
echo "  --> migrate.sh again is a no-op (the ledger)"
if migrate koras_matrix_a "$SECURE_DIR" | grep -q "already applied"; then
  echo "  ok    A: re-run skipped every migration"
else
  echo "::error::A: the re-run did not skip by ledger"; FAILED=1
fi
echo "  --> the four files applied directly a second time are idempotent"
for m in "${SECURE_MIGRATIONS[@]}"; do sql koras_matrix_a -f "$SECURE_DIR/supabase/migrations/$m.sql" >/dev/null; done
secure_objects_present koras_matrix_a "A (re-applied)"
rls_suites koras_matrix_a "$SECURE_DIR"

echo "=== B. fresh DEFAULT product"
newdb koras_matrix_b
migrate koras_matrix_b "$DEFAULT_DIR"
secure_objects_absent koras_matrix_b B
for f in services/api/koras_api/core/upload_window.py services/api/koras_api/core/finalize_jobs.py \
         services/worker/koras_worker/scanning services/worker/koras_worker/uploads \
         docs/SECURE_FILES.md supabase/migrations/00039_file_scan_attempts.sql \
         supabase/migrations/00042_file_derived_content_withdrawal.sql; do
  if [ -e "$DEFAULT_DIR/$f" ]; then echo "::error::the default product carries $f"; FAILED=1; else echo "  ok    B: no $f"; fi
done
if grep -q '^SECURE_FILES = False$' "$DEFAULT_DIR/services/api/koras_api/core/secure_files.py"; then
  echo "  ok    B: SECURE_FILES is False"
else
  echo "::error::SECURE_FILES is not False in the default product"; FAILED=1
fi
if grep -q '^SECURE_FILES = True$' "$SECURE_DIR/services/api/koras_api/core/secure_files.py"; then
  echo "  ok    A: SECURE_FILES is True"
else
  echo "::error::SECURE_FILES is not True in the secure product"; FAILED=1
fi
rls_suites koras_matrix_b "$DEFAULT_DIR"

echo "=== C. upgrade a default product from the commit before this branch"
newdb koras_matrix_c
migrate koras_matrix_c "$BASELINE_DIR"
secure_objects_absent koras_matrix_c "C (baseline)"

T1=00000000-0000-4c0c-8000-000000000001
T2=00000000-0000-4c0c-8000-000000000002
sql koras_matrix_c <<SQL
insert into public.tenants (id, slug, name, zitadel_org_id, status, owner_email) values
  ('$T1', 'upgrade-one', 'Upgrade one', 'upgrade-one-org', 'active', 'one@example.com'),
  ('$T2', 'upgrade-two', 'Upgrade two', 'upgrade-two-org', 'active', 'two@example.com');
-- Legacy-shaped rows: the keys a default product wrote (with and without a category
-- segment), every scan_status, a digest the client claimed, one never confirmed.
insert into public.files (id, tenant_id, storage_key, name, size_bytes, content_type, category,
                          status, uploaded_by, scan_status, checksum_sha256, indexed_at, index_note, ready_at)
values
  ('00000000-0000-4c0c-8000-0000000000a1', '$T1', 'tenants/$T1/documents/00000000-0000-4c0c-8000-0000000000a1/clean.pdf',
   'clean.pdf', 100, 'application/pdf', 'documents', 'ready', 'u1', 'clean', repeat('a', 64), now(), '2 chunk(s)', now()),
  ('00000000-0000-4c0c-8000-0000000000a2', '$T1', 'tenants/$T1/documents/00000000-0000-4c0c-8000-0000000000a2/pending.pdf',
   'pending.pdf', 100, 'application/pdf', 'documents', 'ready', 'u1', 'pending', null, null, null, now()),
  ('00000000-0000-4c0c-8000-0000000000a3', '$T1', 'tenants/$T1/documents/00000000-0000-4c0c-8000-0000000000a3/skipped.pdf',
   'skipped.pdf', 100, 'application/pdf', 'documents', 'ready', 'u1', 'skipped', null, null, null, now()),
  ('00000000-0000-4c0c-8000-0000000000a4', '$T1', 'tenants/$T1/documents/00000000-0000-4c0c-8000-0000000000a4/infected.pdf',
   'infected.pdf', 100, 'application/pdf', 'documents', 'quarantined', 'u1', 'infected', null, null, null, now()),
  ('00000000-0000-4c0c-8000-0000000000a5', '$T1', 'tenants/$T1/00000000-0000-4c0c-8000-0000000000a5/oldest-shape.pdf',
   'oldest-shape.pdf', 100, 'application/pdf', 'documents', 'ready', 'u1', 'clean', null, null, null, now()),
  ('00000000-0000-4c0c-8000-0000000000a6', '$T1', 'tenants/$T1/imports/00000000-0000-4c0c-8000-0000000000a6/never-confirmed.csv',
   'never-confirmed.csv', 10, 'text/csv', 'imports', 'pending', 'u1', 'pending', null, null, null, null),
  ('00000000-0000-4c0c-8000-0000000000b1', '$T2', 'tenants/$T2/documents/00000000-0000-4c0c-8000-0000000000b1/other.pdf',
   'other.pdf', 100, 'application/pdf', 'documents', 'ready', 'u2', 'clean', repeat('b', 64), null, null, now());
SQL
HAS_CHUNKS="$(sql koras_matrix_c -c "select to_regclass('public.ai_knowledge_chunks') is not null")"
if [ "$HAS_CHUNKS" = "t" ]; then
  sql koras_matrix_c <<SQL
insert into public.ai_knowledge_chunks (tenant_id, document_id, resource_type, resource_id, title, chunk_index, content, embedding)
select '$T1', 'file:00000000-0000-4c0c-8000-0000000000a1', 'file', '00000000-0000-4c0c-8000-0000000000a1',
       'clean.pdf', i, 'legacy chunk ' || i, array_fill(0::real, array[1536])::vector
from generate_series(0, 1) i;
SQL
fi

# What every legacy row looked like before: the baseline's own columns, in a stable order.
BASE_COLS="$(sql koras_matrix_c -c "select string_agg(quote_ident(column_name), ', ' order by ordinal_position) from information_schema.columns where table_schema = 'public' and table_name = 'files'")"
fingerprint() {
  sql koras_matrix_c -c "select md5(string_agg(t::text, '|' order by id)) from (select $BASE_COLS from public.files) t"
}
BEFORE="$(fingerprint)"
ROWS_BEFORE="$(sql koras_matrix_c -c "select count(*) from public.files")"
chunk_count() {
  if [ "$HAS_CHUNKS" = "t" ]; then
    sql koras_matrix_c -c "select count(*) from public.ai_knowledge_chunks"
  else
    echo 0
  fi
}
CHUNKS_BEFORE="$(chunk_count)"
echo "  seeded $ROWS_BEFORE legacy files and $CHUNKS_BEFORE chunks"

echo "  --> the secure product's own migrate.sh upgrades the baseline schema"
migrate koras_matrix_c "$UPGRADE_DIR" | tee "$WORK/upgrade.out"
APPLIED="$(grep -E '^ +apply ' "$WORK/upgrade.out" | awk '{print $2}' | tr '\n' ' ')"
if [ "$APPLIED" = "${SECURE_MIGRATIONS[*]} " ]; then
  echo "  ok    C: exactly 00039-00042 were applied ($APPLIED)"
else
  echo "::error::C: the upgrade applied '$APPLIED', not exactly the four secure migrations"; FAILED=1
fi

secure_objects_present koras_matrix_c "C (upgraded)"
check koras_matrix_c "C: no legacy row was lost" "select count(*) = $ROWS_BEFORE from public.files"
if [ "$(fingerprint)" = "$BEFORE" ]; then
  echo "  ok    C: every baseline column of every legacy row is unchanged"
else
  echo "::error::C: a legacy row changed in the upgrade"; FAILED=1
fi
if [ "$(chunk_count)" = "$CHUNKS_BEFORE" ]; then
  echo "  ok    C: no chunk was lost ($CHUNKS_BEFORE before and after)"
else
  echo "::error::C: the chunk count changed in the upgrade"; FAILED=1
fi
check koras_matrix_c "C: the new columns took their defaults (attempts 0, no failure, no etag)" \
  "select bool_and(scan_attempts = 0 and scan_failure is null and scan_object_etag is null and scan_attempted_at is null) from public.files"

echo "  --> idempotent: the four files applied again leave the data and the fingerprint alone"
for m in "${SECURE_MIGRATIONS[@]}"; do sql koras_matrix_c -f "$UPGRADE_DIR/supabase/migrations/$m.sql" >/dev/null; done
if [ "$(fingerprint)" = "$BEFORE" ]; then
  echo "  ok    C: re-applied, fingerprint unchanged"
else
  echo "::error::C: re-applying changed data"; FAILED=1
fi
secure_objects_present koras_matrix_c "C (re-applied)"

echo "  --> no legacy row is releasable under the secure rule"
RELEASABLE_SQL="$(python3 "$HERE/release_rule.py" sql "$SECURE_DIR")"
check koras_matrix_c "C: RELEASABLE_SQL selects no upgraded row (clean legacy rows included)" \
  "select count(*) = 0 from public.files f where $RELEASABLE_SQL"
check koras_matrix_c "C: legacy clean rows are still 'clean' (nothing was rewritten to look releasable)" \
  "select count(*) = 3 from public.files where scan_status = 'clean'"
python3 "$HERE/release_rule.py" rows "$SECURE_DIR" "$DEFAULT_DIR" koras_matrix_c || FAILED=1

check koras_matrix_c "C: row-level security is forced on every table that has it enabled" \
  "select count(*) = 0 from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'public' and c.relkind = 'r' and c.relrowsecurity and not c.relforcerowsecurity"
check koras_matrix_c "C: files is among them" \
  "select relrowsecurity and relforcerowsecurity from pg_class where oid = 'public.files'::regclass"

if [ "$HAS_CHUNKS" = "t" ]; then
  echo "  --> the withdrawal trigger acts on a legacy clean, indexed file once its verdict changes"
  RESULT="$(sql koras_matrix_c <<'SQL' | grep -E '^[tf]$' | head -1
begin;
update public.files set scan_status = 'infected', status = 'quarantined'
 where id = '00000000-0000-4c0c-8000-0000000000a1';
select (select count(*) from public.ai_knowledge_chunks where resource_id = '00000000-0000-4c0c-8000-0000000000a1') = 0
   and (select indexed_at is null and index_note is null from public.files where id = '00000000-0000-4c0c-8000-0000000000a1');
rollback;
SQL
)"
  if [ "$RESULT" = "t" ]; then
    echo "  ok    C: the trigger withdrew the chunks and the index state"
  else
    echo "::error::C: the withdrawal trigger did not act on an upgraded legacy row"; FAILED=1
  fi
fi

rls_suites koras_matrix_c "$UPGRADE_DIR"

echo "=== D. a secure product enables the assistant LATER (00010 applied after 00042)"
newdb koras_matrix_d
migrate koras_matrix_d "$SECURE_DIR"
check koras_matrix_d "D: before: the product has 00042 and no assistant tables" \
  "select to_regclass('public.ai_knowledge_chunks') is null and exists (select 1 from public.schema_migrations where version = '00042_file_derived_content_withdrawal') and not exists (select 1 from public.schema_migrations where version = '00010_ai_knowledge')"

T3=00000000-0000-4c0d-8000-000000000001
F3=00000000-0000-4c0d-8000-0000000000a1
sql koras_matrix_d <<SQL
insert into public.tenants (id, slug, name, zitadel_org_id, status, owner_email)
values ('$T3', 'later-ai', 'Later ai', 'later-ai-org', 'active', 'later@example.com');
insert into public.files (id, tenant_id, storage_key, name, size_bytes, content_type, category,
                          status, uploaded_by, scan_status, scan_object_etag, indexed_at, index_note, ready_at)
values ('$F3', '$T3', 'tenants/$T3/documents/$F3/final/00000000-0000-4000-8000-000000000001/clean.pdf',
        'clean.pdf', 100, 'application/pdf', 'documents', 'ready', 'u3', 'clean', 'etag-d', now(), '1 chunk(s)', now());
SQL

echo "  --> with no chunk table the trigger still clears the index state and does not fail"
RESULT="$(sql koras_matrix_d <<SQL | grep -E '^[tf]$' | head -1
begin;
update public.files set scan_status = 'infected', status = 'quarantined' where id = '$F3';
select indexed_at is null and index_note is null and scan_status = 'infected' from public.files where id = '$F3';
rollback;
SQL
)"
if [ "$RESULT" = "t" ]; then echo "  ok    D: a verdict leaving clean cleared the index state with no chunk table"; else
  echo "::error::D: the withdrawal trigger failed or did nothing before the assistant existed"; FAILED=1; fi

echo "  --> enabling the assistant: the assistant product's own migrate.sh applies what is missing"
migrate koras_matrix_d "$UPGRADE_DIR" | tee "$WORK/later-ai.out"
check koras_matrix_d "D: 00010 was applied after 00042 and the chunk table now exists" \
  "select to_regclass('public.ai_knowledge_chunks') is not null and exists (select 1 from public.schema_migrations where version = '00010_ai_knowledge') and (select applied_at from public.schema_migrations where version = '00010_ai_knowledge') > (select applied_at from public.schema_migrations where version = '00042_file_derived_content_withdrawal')"
check koras_matrix_d "D: none of 00039-00042 was applied a second time" \
  "select count(*) = 4 from public.schema_migrations where version in ('${SECURE_MIGRATIONS[0]}','${SECURE_MIGRATIONS[1]}','${SECURE_MIGRATIONS[2]}','${SECURE_MIGRATIONS[3]}')"
secure_objects_present koras_matrix_d "D (after the assistant was enabled)"

echo "  --> the same trigger now deletes the file's chunks, on a verdict and on a row delete"
CHUNK_INSERT="insert into public.ai_knowledge_chunks (tenant_id, document_id, resource_type, resource_id, title, chunk_index, content, embedding)
select '$T3', 'file:$F3', 'file', '$F3', 'clean.pdf', i, 'late chunk ' || i, array_fill(0::real, array[1536])::vector from generate_series(0, 1) i;"
RESULT="$(sql koras_matrix_d <<SQL | grep -E '^[tf]$' | head -1
begin;
$CHUNK_INSERT
update public.files set scan_status = 'infected', status = 'quarantined' where id = '$F3';
select (select count(*) from public.ai_knowledge_chunks where resource_id = '$F3') = 0
   and (select indexed_at is null and index_note is null from public.files where id = '$F3');
rollback;
SQL
)"
if [ "$RESULT" = "t" ]; then echo "  ok    D: the verdict withdrew the chunks and the index state"; else
  echo "::error::D: the trigger did not delete chunks of a table created after it"; FAILED=1; fi
RESULT="$(sql koras_matrix_d <<SQL | grep -E '^[tf]$' | head -1
begin;
$CHUNK_INSERT
delete from public.files where id = '$F3';
select (select count(*) from public.ai_knowledge_chunks where resource_id = '$F3') = 0;
rollback;
SQL
)"
if [ "$RESULT" = "t" ]; then echo "  ok    D: deleting the row removed its chunks"; else
  echo "::error::D: the delete trigger did not remove chunks of a table created after it"; FAILED=1; fi
RESULT="$(sql koras_matrix_d <<SQL | grep -E '^[tf]$' | head -1
begin;
$CHUNK_INSERT
update public.files set name = 'renamed.pdf' where id = '$F3';
select (select count(*) from public.ai_knowledge_chunks where resource_id = '$F3') = 2
   and (select indexed_at is not null from public.files where id = '$F3');
rollback;
SQL
)"
if [ "$RESULT" = "t" ]; then echo "  ok    D: an unrelated write kept the chunks and the index state"; else
  echo "::error::D: an unrelated write to a clean file withdrew its chunks"; FAILED=1; fi

rls_suites koras_matrix_d "$UPGRADE_DIR"

if [ "$FAILED" -ne 0 ]; then echo "::error::the migration matrix has failures"; exit 1; fi
echo "The migration matrix passed: A fresh secure, B fresh default, C upgrade, D assistant enabled later."
