#!/usr/bin/env bash
# Full local environment bootstrap.
# Safe to re-run — idempotent where possible.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROFILE="${KORAS_PROFILE:-product}"

echo "==> Bootstrapping KORAS local environment (profile: ${PROFILE})"
echo ""

# 1. Node dependencies
echo "--> Installing Node dependencies..."
cd "$ROOT" && pnpm install

# 2. Python dependencies
echo "--> Installing Python dependencies..."
cd "$ROOT" && uv sync

# 3. TLS certificates
if [ ! -f "$ROOT/local/certs/app.localhost.pem" ]; then
  echo "--> Generating TLS certificates..."
  bash "$ROOT/local/certs/generate.sh"
else
  echo "--> TLS certificates already present, skipping."
fi

# 4. Pull Docker images
echo "--> Pulling Docker images..."
# One rendered compose file per project — the profile decided what went into it
# at generation time, so there is nothing to layer here.
COMPOSE_FILES="-f $ROOT/local/docker-compose.yml"
docker compose $COMPOSE_FILES pull --quiet

# 5. Start infrastructure services (not app services)
echo "--> Starting infrastructure services..."
docker compose $COMPOSE_FILES up -d supabase-db zitadel redis mail

# 6. Wait for Supabase DB
echo "--> Waiting for Supabase DB..."
until docker compose $COMPOSE_FILES exec -T supabase-db pg_isready -U postgres >/dev/null 2>&1; do
  sleep 2
done
echo "    Supabase DB ready."

# 7. Wait for ZITADEL
echo "--> Waiting for ZITADEL..."
until curl -sf "http://localhost:8080/debug/ready" >/dev/null 2>&1; do
  sleep 3
done
echo "    ZITADEL ready."

# 8. Initialize ZITADEL
echo "--> Initializing ZITADEL..."
ZITADEL_URL=http://localhost:8080 bash "$ROOT/local/zitadel/init.sh"

# 9. Copy .env.local.example if .env.local is missing
if [ ! -f "$ROOT/.env.local" ]; then
  echo "--> Creating .env.local from example..."
  cp "$ROOT/local/config/.env.local.example" "$ROOT/.env.local"
  echo "    Edit .env.local and populate secrets from Doppler before running services."
fi

echo ""
echo "==> Bootstrap complete."
echo "    Run: make dev"
