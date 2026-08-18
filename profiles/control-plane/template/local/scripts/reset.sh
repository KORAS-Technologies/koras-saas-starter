#!/usr/bin/env bash
# Tears down the local stack, wipes all volumes, and re-bootstraps.
# DESTRUCTIVE — all local data is lost.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROFILE="${KORAS_PROFILE:-product}"

# One rendered compose file per project — the profile decided what went into it
# at generation time, so there is nothing to layer here.
COMPOSE_FILES="-f $ROOT/local/docker-compose.yml"

echo "==> Resetting local environment (all data will be lost)..."
docker compose $COMPOSE_FILES down --volumes --remove-orphans
rm -f "$ROOT/.env.local"

echo "--> Re-bootstrapping..."
KORAS_PROFILE="$PROFILE" bash "$ROOT/local/scripts/bootstrap.sh"
