#!/usr/bin/env bash
# Runs the extracted "machines are actually running" step against a flyctl that
# reproduces the disagreement which failed a real deployment.
#
#   run-case.sh <step.sh> <initial-json> <lies|honest> <transition:yes|no>
#
# flyctl is a shell function, not a script earlier on PATH. The PATH version was
# tried first and silently lost to the real binary on Windows -- the test called
# Fly's API with the developer's own credentials and failed with `app not
# found`. A function cannot be bypassed by name resolution, so this harness can
# never reach real infrastructure no matter where it runs.
#
# `transition` models what Fly does on its own: a machine in `created` leaves
# that state within seconds. Without it the step would wait for something that
# never happens.
set -uo pipefail

step="$1"; initial="$2"; FAKE_MODE="$3"; transition="$4"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
STATE="$work/state.json"
printf '%s' "$initial" > "$STATE"
echo 0 > "$STATE.tick"

flyctl() {
  case "${1:-} ${2:-}" in
    "machines list")
      local tick; tick=$(( $(cat "$STATE.tick") + 1 )); echo "$tick" > "$STATE.tick"
      # The stale read that defeated the previous version of the step: the list
      # reports `stopped` for a machine Fly still considers `created`.
      if [ "$FAKE_MODE" = "lies" ] && [ "$tick" -le 1 ]; then
        echo '[{"id":"m1","state":"stopped"}]'
      else
        cat "$STATE"
      fi
      ;;
    "machine start")
      local id="$3" real
      real=$(jq -r --arg i "$id" '.[] | select(.id == $i) | .state' "$STATE")
      if [ "$real" = "created" ]; then
        echo "Error: could not start machine $id: failed_precondition:" \
             "unable to start machine from current state: 'created'" >&2
        return 1
      fi
      jq --arg i "$id" 'map(if .id == $i then .state = "started" else . end)' \
        "$STATE" > "$STATE.new" && mv "$STATE.new" "$STATE"
      echo "started $id"
      ;;
    *)
      echo "harness: unhandled flyctl call: $*" >&2; return 2 ;;
  esac
}

if [ "$transition" = "yes" ]; then
  ( sleep 6
    jq 'map(if .state == "created" then .state = "stopped" else . end)' \
      "$STATE" > "$work/next" && mv "$work/next" "$STATE" ) &
fi

# Sourced, so the function is what the step calls.
# shellcheck disable=SC1090
source "$step"
rc=$?
wait
echo "FINAL $(jq -c . "$STATE")"
exit $rc
