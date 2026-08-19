#!/usr/bin/env bash
# Applies the database schema to the local Supabase database.
#
# Migrations run in filename order. They are applied
# through `docker compose exec` rather than a host psql, so the script works on
# a machine that has no Postgres client installed — which is most of them.
#
# Idempotent by convention: every migration is expected to be re-runnable, and
# the applied set is tracked in schema_migrations so re-running is a no-op.
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

# Policies are applied after the migrations, once every table exists. They are
# versioned in the same ledger under a policies/ prefix.
#
# Ordering matters and is easy to get wrong: anything defined BOTH here and in a
# migration is applied twice, with this directory winning. If a migration is
# ever used to correct a policy, that correction must not also live here, or a
# fresh database will silently end up with the older version -- while an
# existing database looks fine, because it applied them in the other order.
for file in "$ROOT"/supabase/policies/*.sql; do
  apply_file "$file" "policies/$(basename "$file" .sql)"
done

echo ""
echo "Schema up to date."
