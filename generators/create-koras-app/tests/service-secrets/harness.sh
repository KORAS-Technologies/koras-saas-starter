#!/usr/bin/env bash
# Runs service-secrets.sh against a doppler and a flyctl that cannot reach
# anything. Both are shell FUNCTIONS, exported to the child: a function beats a
# binary on PATH under every name resolution, so this harness can never call the
# real services whatever the machine has installed (the same reason
# fly/run-case.sh does it this way).
#
#   FAKE_DOPPLER_JSON / FAKE_DOPPLER_ENV   what `doppler secrets download` prints
#   FAKE_FLY_SECRETS                       what `flyctl secrets list --json` prints
#   CALLS                                  every call, one line each
#   IMPORTED                               what was piped into `flyctl secrets import`
set -uo pipefail

doppler() {
  echo "doppler $*" >> "$CALLS"
  case "$*" in
    *"--format json"*) printf '%s' "${FAKE_DOPPLER_JSON:-}" ;;
    *"--format env-no-quotes"*) printf '%s' "${FAKE_DOPPLER_ENV:-}" ;;
  esac
}
flyctl() {
  echo "flyctl $*" >> "$CALLS"
  case "${1:-} ${2:-}" in
    "secrets list") printf '%s' "${FAKE_FLY_SECRETS:-[]}" ;;
    "secrets import") cat > "$IMPORTED" ;;
    *) echo "harness: unhandled flyctl call: $*" >&2; return 2 ;;
  esac
}
export -f doppler flyctl

exec bash "$SCRIPT" "$@"
