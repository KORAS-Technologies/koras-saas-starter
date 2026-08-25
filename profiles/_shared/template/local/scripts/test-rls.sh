#!/usr/bin/env bash
# Runs the row-level security suite against a database that has the schema.
#
# Two ways in, matching migrate.sh: through the local Compose stack by default,
# or against any reachable database by setting RLS_DATABASE_URL -- which is how
# CI points it at a service container.
#
# The suite has to run as a role that is neither superuser nor the owner of the
# tables, because those are exactly the roles RLS does not apply to. Running it
# as the owner would pass every assertion while proving nothing, so the role is
# created here rather than assumed, and the script fails if it cannot be.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE="docker compose -f ${ROOT}/local/docker-compose.yml"
DB="${POSTGRES_DB:-postgres}"
USER="${POSTGRES_USER:-postgres}"
TEST_ROLE="koras_rls_test"

# The role the service actually connects as, when it is known. The structural
# suite checks that it is neither a superuser nor BYPASSRLS -- `force` binds the
# table owner and does nothing to either of those, so a deployment can have
# correct policies, force set everywhere, and no isolation at all. Unset, that
# check is skipped rather than guessed at.
APP_ROLE="${RLS_APP_ROLE:-}"
PSQL_VARS=()
if [ -n "$APP_ROLE" ]; then
  PSQL_VARS=(-v "app_role=$APP_ROLE")
fi

if [ -n "${RLS_DATABASE_URL:-}" ]; then
  psql_exec() { psql -v ON_ERROR_STOP=1 "$RLS_DATABASE_URL" "$@"; }
else
  psql_exec() { $COMPOSE exec -T supabase-db psql -v ON_ERROR_STOP=1 -U "$USER" -d "$DB" "$@"; }
fi

echo "==> Preparing the unprivileged role the suite runs as"

# nologin: it exists to be SET ROLE'd into, never to connect. nobypassrls is
# the default and is stated anyway -- it is the single property the whole suite
# depends on, and a future edit that grants this role something should have to
# read past it.
psql_exec --quiet -c "
  do \$\$
  begin
    if not exists (select 1 from pg_roles where rolname = '${TEST_ROLE}') then
      create role ${TEST_ROLE} nologin nobypassrls;
    end if;
  end
  \$\$;
  grant usage on schema public to ${TEST_ROLE};
  grant select, insert, update, delete on all tables in schema public to ${TEST_ROLE};
"

echo "==> Running the row-level security suite"

shopt -s nullglob
tests=("${ROOT}"/supabase/tests/*.sql)
if [ ${#tests[@]} -eq 0 ]; then
  echo "No tests found in supabase/tests/." >&2
  exit 1
fi

for file in "${tests[@]}"; do
  echo "--> $(basename "$file")"
  if [ -n "${RLS_DATABASE_URL:-}" ]; then
    psql -v ON_ERROR_STOP=1 "${PSQL_VARS[@]}" "$RLS_DATABASE_URL" -f "$file"
  else
    $COMPOSE exec -T supabase-db psql -v ON_ERROR_STOP=1 "${PSQL_VARS[@]}" -U "$USER" -d "$DB" < "$file"
  fi
done

echo "==> Row-level security suite passed"
