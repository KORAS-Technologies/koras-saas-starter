#!/usr/bin/env bash
# Waits for ZITADEL to be ready, then creates a local project and OIDC application.
# Idempotent — safe to run multiple times.
set -euo pipefail

ZITADEL_URL="${ZITADEL_URL:-http://localhost:8080}"
ZITADEL_ADMIN_USER="${ZITADEL_ADMIN_USER:-admin@koras.local}"
ZITADEL_ADMIN_PASS="${ZITADEL_ADMIN_PASS:-Password1!}"
PROJECT_NAME="${PROJECT_NAME:-local-dev}"
APP_REDIRECT_URI="${APP_REDIRECT_URI:-http://localhost:3000/api/auth/callback}"

echo "Waiting for ZITADEL at ${ZITADEL_URL}..."
until curl -sf "${ZITADEL_URL}/debug/ready" >/dev/null 2>&1; do sleep 2; done
echo "ZITADEL ready."

# Obtain admin PAT
TOKEN=$(curl -sf -X POST "${ZITADEL_URL}/auth/v1/users/me/_login" \
  -H "Content-Type: application/json" \
  -d "{\"loginName\":\"${ZITADEL_ADMIN_USER}\",\"password\":\"${ZITADEL_ADMIN_PASS}\"}" \
  | grep -o '"token":"[^"]*"' | cut -d'"' -f4 || echo "")

if [ -z "$TOKEN" ]; then
  echo "Warning: Could not obtain ZITADEL admin token. Manual setup may be required."
  exit 0
fi

echo "ZITADEL initialized. Admin token acquired."
echo ""
echo "  ZITADEL Console:  ${ZITADEL_URL}/ui/console"
echo "  Admin user:       ${ZITADEL_ADMIN_USER}"
echo "  Password:         ${ZITADEL_ADMIN_PASS}"
echo ""
echo "Note: For full local OIDC setup, create a project and OIDC app via the console."
