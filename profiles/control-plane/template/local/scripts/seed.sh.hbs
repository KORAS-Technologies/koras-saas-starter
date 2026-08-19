#!/usr/bin/env bash
# Seeds the local database with development fixtures.
#
# Runs through `docker compose exec` rather than a host psql. The host port is
# resolved per machine by local/scripts/ports.sh, so a literal port aimed at
# localhost can land on a different project's database when two KORAS stacks
# run at once -- and this way no Postgres client is needed on the host.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE="docker compose -f ${ROOT}/local/docker-compose.yml"
DB="${POSTGRES_DB:-postgres}"
USER="${POSTGRES_USER:-postgres}"

echo "==> Seeding local database..."

shopt -s nullglob
seed_files=("$ROOT"/supabase/seed/*.sql)

if [ ${#seed_files[@]} -eq 0 ]; then
  echo "    No seed files in supabase/seed/ -- nothing to apply."
  exit 0
fi

for seed_file in "${seed_files[@]}"; do
  echo "    Applying: $(basename "$seed_file")"
  $COMPOSE exec -T supabase-db \
    psql -v ON_ERROR_STOP=1 -U "$USER" -d "$DB" --quiet < "$seed_file"
done

echo ""
echo "Seed complete."
