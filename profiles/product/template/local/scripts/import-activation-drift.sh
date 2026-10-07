#!/usr/bin/env bash
# A deployed service must not hold IMPORTS_ENABLED unless the secret store holds it too.
#
#   bash local/scripts/import-activation-drift.sh <fly-app> <doppler-project> <doppler-config>
#
# Why: the deploy imports the Doppler config into Fly and never removes a secret,
# so a value set by hand with `fly secrets set` survives every deploy and Doppler
# stops being the authority for whether data import is on. The policy is
# local/config/import-activation.yaml. This is the Fly-side half of the
# check, in bash because the per-service deploy job has no Python environment
# and installing one per matrix entry is more risk than this needs.
#
# Reads names only: Fly never returns a value, and the Doppler value is fetched
# only to learn whether it exists and is discarded. Nothing is printed but the
# app name and the setting name. Changes nothing. Unknown is a failure: an
# unreadable app or an unexpected Doppler error is never reported as clean.
set -eu
set +x

app="${1:?fly app}"
project="${2:?doppler project}"
config="${3:?doppler config}"
setting="IMPORTS_ENABLED"

fail() { echo "import-activation-drift: $*" >&2; exit 1; }

fly_json=$(flyctl secrets list --app "$app" --json) || fail "could not list secrets for $app"
# Fail closed on anything but a well-formed array: a jq error is "unreadable", never "name absent".
holds=$(printf '%s' "$fly_json" | jq -r --arg n "$setting" '
  if type == "array"
  then ([.[] | (.name // .Name) | strings] | index($n) != null)
  else error("unexpected shape") end') || fail "secrets listing for $app is not readable JSON; cannot rule out drift"
case "$holds" in
  true) fly_holds=1 ;;
  false) fly_holds=0 ;;
  *) fail "secrets listing for $app gave no usable answer; cannot rule out drift" ;;
esac

if [ "$fly_holds" -eq 0 ]; then
  echo "$app holds no $setting; nothing to drift."
  exit 0
fi

# Fly holds it. Doppler must too.
err=$(mktemp)
trap 'rm -f "$err"' EXIT
if doppler secrets get "$setting" --plain --project "$project" --config "$config" >/dev/null 2>"$err"; then
  echo "$app holds $setting and Doppler ($project/$config) holds it too."
  exit 0
fi
if grep -qi "could not find requested secret" "$err"; then
  fail "DRIFT: $app holds $setting but Doppler ($project/$config) does not. Doppler is the authority: add it there through a reviewed change to local/config/import-activation.yaml, or unset it on the app."
fi
fail "could not read $setting from Doppler ($project/$config); cannot rule out drift"
