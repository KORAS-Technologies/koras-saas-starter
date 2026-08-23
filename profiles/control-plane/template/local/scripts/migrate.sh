#!/usr/bin/env bash
# Applies the database schema to the local Supabase database.
#
# Migrations run in filename order. They are applied
# through `docker compose exec` rather than a host psql, so the script works on
# a machine that has no Postgres client installed — which is most of them.
#
# The applied set is tracked in schema_migrations, so re-running this script is
# a no-op. That ledger is what makes it safe, not per-file idempotency: 00001
# creates tables without `if not exists` and fails outright on a second run.
# Write new migrations to be re-runnable anyway where it is cheap -- a
# half-applied migration is recovered by hand, and the hand doing it has the
# ledger to edit either way.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE="docker compose -f ${ROOT}/local/docker-compose.yml"
DB="${POSTGRES_DB:-postgres}"
USER="${POSTGRES_USER:-postgres}"

# Two ways in. By default the schema is applied through the local Compose stack,
# which needs no Postgres client on the host. Set MIGRATE_DATABASE_URL to point a
# host psql at any reachable database instead -- that is how CI applies the
# schema to its service container, and how a deployed environment will be
# migrated later.
if [ -n "${MIGRATE_DATABASE_URL:-}" ]; then
  psql_exec() {
    psql -v ON_ERROR_STOP=1 "$MIGRATE_DATABASE_URL" "$@"
  }
else
  psql_exec() {
    $COMPOSE exec -T supabase-db psql -v ON_ERROR_STOP=1 -U "$USER" -d "$DB" "$@"
  }
fi

echo "==> Applying database schema to the local database"

# Ledger of what has already run, so `make bootstrap` stays re-runnable.
psql_exec --quiet -c "
  create table if not exists public.schema_migrations (
    version     text primary key,
    applied_at  timestamptz not null default now()
  );
" >/dev/null

applied() {
  psql_exec -tAc "select 1 from public.schema_migrations where version = '$1'" | grep -q 1
}

apply_file() {
  local file="$1" version="$2"
  if applied "$version"; then
    echo "    skip     $version (already applied)"
    return 0
  fi
  echo "    apply    $version"
  psql_exec --quiet < "$file"
  psql_exec --quiet -c \
    "insert into public.schema_migrations (version) values ('$version')" >/dev/null
}

shopt -s nullglob

for file in "$ROOT"/supabase/migrations/*.sql; do
  apply_file "$file" "$(basename "$file" .sql)"
done

# Policies are NOT applied from supabase/policies/. They ship as numbered
# migrations, so they are ordered and versioned like any other schema change.
#
# Applying them afterwards from a directory re-ran them on top of the migrations
# that had just corrected them. An existing database looked fine, because it had
# applied the directory first; only a clean bootstrap inverted the order, and
# that is the case least likely to be noticed and the one that becomes
# production. It restored a cross-organization read in the Control Plane.
# See supabase/policies/README.md.

echo ""
echo "Schema up to date."
