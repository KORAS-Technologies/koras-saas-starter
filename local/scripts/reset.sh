#!/usr/bin/env bash
# Tears down the local stack, wipes all volumes, and re-bootstraps.
# DESTRUCTIVE — all local data is lost.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROFILE="${KORAS_PROFILE:-product}"

COMPOSE_FILES="-f $ROOT/local/docker/shared.compose.yml"
if [ "$PROFILE" = "product" ]; then
  COMPOSE_FILES="$COMPOSE_FILES -f $ROOT/local/docker/product.compose.yml"
else
  COMPOSE_FILES="$COMPOSE_FILES -f $ROOT/local/docker/control-plane.compose.yml"
fi

echo "==> Resetting local environment (all data will be lost)..."
docker compose $COMPOSE_FILES down --volumes --remove-orphans
rm -f "$ROOT/.env.local"

echo "--> Re-bootstrapping..."
KORAS_PROFILE="$PROFILE" bash "$ROOT/local/scripts/bootstrap.sh"
