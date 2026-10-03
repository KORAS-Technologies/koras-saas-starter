#!/usr/bin/env bash
# After a deploy: a service declared `network: private` is checked for what
# makes it private, and that it is actually working.
#
#   verify-private-service.sh <service> <app> [services-dir]
#
# A public service (including every service with no descriptor) is skipped with
# a message and exit 0, so the workflow calls this for every service and names
# none of them.
#
# Checks, all of which must hold:
#   - the app has no public IP address. Only Fly's own private (6PN) address is
#     permitted; any other address, or a type this script does not recognise,
#     fails. Fail closed: an unrecognised address is not assumed harmless.
#   - at least one machine exists and every machine is started.
#   - every machine reports at least one health check, and all are passing.
#
# Needs FLY_API_TOKEN. Prints no secret and reads none.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
svc="${1:?service}"; app="${2:?app}"; root="${3:-services}"
timeout_s="${VERIFY_PRIVATE_TIMEOUT:-300}"

network=$(bash "$here/service-descriptor.sh" network "$svc" "$root")
if [ "$network" != "private" ]; then
  echo "$svc is $network; no private-service checks apply."
  exit 0
fi

fail() { echo "verify-private-service: $app: $*" >&2; exit 1; }

# --- No public address -------------------------------------------------------
ips=$(flyctl ips list --app "$app" --json) || fail "could not list IP addresses"
public=$(printf '%s' "$ips" | jq -c '[.[]? | select((.Type // .type) != "private_v6")]')
if [ "$public" != "[]" ]; then
  {
    echo "$app is declared private and has a public address:"
    printf '%s' "$public" | jq -r '.[] | "  \(.Type // .type) \(.Address // .address)"'
    echo "Release it:  flyctl ips release <address> --app $app"
    echo "and check fly.toml has no [http_service] or [[services]]."
  } >&2
  exit 1
fi
echo "$app has no public address."

# --- Running and healthy -----------------------------------------------------
deadline=$(( $(date +%s) + timeout_s ))
while :; do
  machines=$(flyctl machines list --app "$app" --json) || fail "could not list machines"
  problem=$(printf '%s' "$machines" | jq -r '
    if length == 0 then "no machines exist"
    else
      [ .[] |
        if .state != "started" then "\(.id) is \(.state)"
        elif ((.checks // []) | length) == 0 then "\(.id) reports no health check"
        elif ((.checks // []) | any(.status != "passing")) then "\(.id) has a failing check"
        else empty end
      ] | first // empty
    end' | tr -d '\r')
  [ -z "$problem" ] && break
  if [ "$(date +%s)" -ge "$deadline" ]; then
    fail "not healthy after ${timeout_s}s: $problem"
  fi
  sleep 5
done
echo "$app: machines started, health checks passing, no public address."
