#!/usr/bin/env bash
# Runs verify-private-service.sh against a flyctl that cannot reach anything.
# A shell function, exported: it beats any binary on PATH, so this can never
# touch real infrastructure whatever is installed.
#
#   FAKE_IPS        what `flyctl ips list --json` prints
#   FAKE_MACHINES   what `flyctl machines list --json` prints
#   CALLS           every call, one line each
set -uo pipefail

flyctl() {
  echo "flyctl $*" >> "$CALLS"
  case "${1:-} ${2:-}" in
    "ips list") printf '%s' "${FAKE_IPS:-[]}" ;;
    "machines list") printf '%s' "${FAKE_MACHINES:-[]}" ;;
    *) echo "harness: unhandled flyctl call: $*" >&2; return 2 ;;
  esac
}
export -f flyctl

exec bash "$SCRIPT" "$@"
