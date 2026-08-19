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
# This script then creates the project the Control Plane grants to customer
# organizations. It is idempotent: an existing project is reused.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ZITADEL_URL="${ZITADEL_URL:-http://localhost:8080}"
# Defaults to the directory name, so the template needs no interpolation.
PROJECT_NAME="${PROJECT_NAME:-$(basename "$ROOT")}"
PAT_FILE="$ROOT/local/zitadel/machinekey/pat"

echo "Waiting for ZITADEL at ${ZITADEL_URL}..."
until curl -sf "${ZITADEL_URL}/debug/ready" >/dev/null 2>&1; do sleep 2; done
echo "ZITADEL ready."

if [ ! -s "$PAT_FILE" ]; then
  echo "Note: no access token at $PAT_FILE."
  echo "      The instance predates the first-instance bootstrap. Drop the zitadel"
  echo "      database and restart the container to reprovision it; see the header"
  echo "      of this script."
  exit 0
fi

PAT="$(tr -d '[:space:]' < "$PAT_FILE")"

api() {
  # $1 method, $2 path, $3 optional JSON body
  curl -sf -X "$1" "${ZITADEL_URL}$2" \
    -H "Authorization: Bearer ${PAT}" \
    -H "Content-Type: application/json" \
    ${3:+-d "$3"}
}

# Reuse the project if it exists. Creating a second one with the same name is
# accepted by ZITADEL and would leave the Control Plane granting the wrong one.
EXISTING="$(api POST /management/v1/projects/_search \
  "{\"queries\":[{\"nameQuery\":{\"name\":\"${PROJECT_NAME}\",\"method\":\"TEXT_QUERY_METHOD_EQUALS\"}}]}" \
  | grep -o '"id":"[0-9]*"' | head -1 | cut -d'"' -f4 || true)"

if [ -n "$EXISTING" ]; then
  PROJECT_ID="$EXISTING"
  echo "Project ${PROJECT_NAME} already exists (${PROJECT_ID})."
else
  PROJECT_ID="$(api POST /management/v1/projects "{\"name\":\"${PROJECT_NAME}\"}" \
    | grep -o '"id":"[0-9]*"' | head -1 | cut -d'"' -f4 || true)"
  if [ -z "$PROJECT_ID" ]; then
    echo "Error: could not create the ZITADEL project." >&2
    exit 1
  fi
  echo "Created project ${PROJECT_NAME} (${PROJECT_ID})."
fi

echo ""
echo "ZITADEL provisioned."
echo ""
echo "  Console:      ${ZITADEL_URL}/ui/console   (KORAS staff only -- never linked from the portal)"
echo "  Admin user:   admin"
echo "  Password:     Password1!"
echo "  Project ID:   ${PROJECT_ID}"
echo ""
echo "  Set these in .env.local:"
echo "    ZITADEL_PROJECT_ID=${PROJECT_ID}"
echo "    ZITADEL_MACHINE_TOKEN=\$(cat local/zitadel/machinekey/pat)"
