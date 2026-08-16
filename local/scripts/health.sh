#!/usr/bin/env bash
# Polls all local services until healthy or times out.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TIMEOUT="${HEALTH_TIMEOUT:-120}"
INTERVAL=3
elapsed=0

declare -A checks=(
  ["Supabase DB"]="http://localhost:54322"
  ["ZITADEL"]="http://localhost:8080/debug/ready"
  ["Redis"]="redis://localhost:6379"
  ["Mailpit"]="http://localhost:8025"
  ["Grafana"]="http://localhost:3333/api/health"
)

echo "==> Health check (timeout: ${TIMEOUT}s)"

for name in "${!checks[@]}"; do
  url="${checks[$name]}"
  elapsed=0
  printf "%-20s" "${name}..."
  while true; do
    if [[ "$url" == redis://* ]]; then
      if redis-cli -h localhost -p 6379 ping 2>/dev/null | grep -q PONG; then
        echo "OK"
        break
      fi
    else
      if curl -sf --max-time 2 "$url" >/dev/null 2>&1; then
        echo "OK"
        break
      fi
    fi
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
    if [ $elapsed -ge $TIMEOUT ]; then
      echo "TIMEOUT"
      echo "Error: ${name} did not become healthy within ${TIMEOUT}s." >&2
      exit 1
    fi
  done
done

echo ""
echo "All services healthy."
echo ""
echo "  App:           https://app.localhost"
echo "  Admin:         https://admin.localhost"
echo "  API:           https://api.localhost"
echo "  ZITADEL:       http://localhost:8080/ui/console"
echo "  Grafana:       http://localhost:3333"
echo "  Mailpit:       http://localhost:8025"
