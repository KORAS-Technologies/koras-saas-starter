#!/usr/bin/env bash
# Provisions the local ZITADEL instance for development.
#
# The instance bootstraps itself from the ZITADEL_FIRSTINSTANCE_* variables in
# local/docker-compose.yml, which create the KORAS organization, an admin human,
# and a machine user whose personal access token is written to
# local/zitadel/machinekey/pat. Those variables apply only when the instance is
# created, so changing them means dropping the zitadel database:
#
#   docker compose -f local/docker-compose.yml stop zitadel
#   docker compose -f local/docker-compose.yml exec -T supabase-db \
#     psql -U postgres -c "drop database if exists zitadel with (force);"
#   docker compose -f local/docker-compose.yml up -d zitadel
#
# The rest -- project, roles, OIDC application, and a grant for the admin -- is
# in provision.py. It used to be here, in shell, parsing JSON with grep, and it
# stopped after creating the project: there was no OIDC application, so nothing
# could sign in locally at all.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ZITADEL_URL="${ZITADEL_URL:-http://localhost:8083}"

echo "Waiting for ZITADEL at ${ZITADEL_URL}..."
for _ in $(seq 1 60); do
  if curl -sf "${ZITADEL_URL}/debug/ready" >/dev/null 2>&1; then break; fi
  sleep 2
done
if ! curl -sf "${ZITADEL_URL}/debug/ready" >/dev/null 2>&1; then
  echo "ZITADEL did not become ready at ${ZITADEL_URL}." >&2
  exit 1
fi

PYTHON=python3
command -v python3 >/dev/null 2>&1 || PYTHON=python
ZITADEL_URL="$ZITADEL_URL" "$PYTHON" "$ROOT/local/zitadel/provision.py"

echo ""
echo "  Console:    ${ZITADEL_URL}/ui/console   (KORAS staff only)"
echo "  Admin user: admin    Password: Password1!"
