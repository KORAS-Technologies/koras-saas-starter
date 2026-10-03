#!/usr/bin/env bash
# Applies one service's secret policy to its Fly app.
#
#   service-secrets.sh apply  <service> <app> <doppler-project> <doppler-config> [services-dir]
#   service-secrets.sh verify <service> <app> [services-dir]
#
# The policy comes from services/<service>/service.yaml via service-descriptor.sh
# -- the workflow names no service and holds no per-service condition. Needs
# DOPPLER_TOKEN and FLY_API_TOKEN in the environment for `apply`, and
# FLY_API_TOKEN for `verify`.
#
#   inherit    (the default, and what every service without a descriptor gets)
#              the environment's whole Doppler config is imported, exactly as it
#              always was.
#   none       nothing is imported, and the app must hold no secret at all.
#   allowlist  only the named secrets are imported; every one must exist in
#              Doppler, and the app must hold nothing else.
#
# What this does NOT do is remove a secret. A `none` or `allowlist` service that
# already holds something it should not FAILS, naming it, and an operator runs
# `flyctl secrets unset`. Deleting from a shared pipeline is destructive and
# irreversible -- Fly never returns a value, so an unset secret cannot be
# restored from the app -- and a deploy that quietly clears things is one
# nobody can reason about. Failing loudly is safe to repeat: run it twice and
# it says the same thing twice.
#
# No secret value is printed, ever. Doppler's output goes to a pipe and
# nowhere else, and xtrace is forced off.
set -eu
set +x

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
descriptor="$here/service-descriptor.sh"

fail() { echo "service-secrets: $*" >&2; exit 1; }

mode="${1:-}"; shift || true

# Names of the secrets the app currently holds, one per line. Fly returns
# names and digests, never values.
held_names() {
  local app="$1" json
  json=$(flyctl secrets list --app "$app" --json) || fail "could not list secrets for $app"
  printf '%s' "$json" | jq -r '.[]?.name // .[]?.Name // empty' | tr -d '\r' | LC_ALL=C sort
}

# Fails if the app holds any secret outside the permitted names (stdin, one per
# line; empty means none are permitted).
refuse_unpermitted() {
  local app="$1" policy="$2" permitted="$3" extra
  extra=$(comm -23 <(held_names "$app") <(printf '%s\n' "$permitted" | sed '/^$/d' | LC_ALL=C sort))
  if [ -n "$extra" ]; then
    {
      echo "$app holds secret(s) its policy ($policy) does not permit:"
      printf '  %s\n' $extra
      echo "Nothing was removed. Review them, then unset each by name:"
      echo "  flyctl secrets unset <NAME> --app $app"
    } >&2
    exit 1
  fi
}

case "$mode" in
  apply)
    svc="${1:?service}"; app="${2:?app}"; project="${3:?doppler project}"; config="${4:?doppler config}"
    root="${5:-services}"
    pol=$("$descriptor" policy "$svc" "$root") || exit 1
    policy=$(printf '%s' "$pol" | jq -r .policy | tr -d '\r')

    case "$policy" in
      inherit)
        # The pre-descriptor behaviour, unchanged. --no-file keeps the values
        # on the pipe; DOPPLER_* is the CLI's own context and is dropped;
        # env-no-quotes because `env` renders a JSON value in a form flyctl
        # mangles. No pipefail, as before.
        doppler secrets download --no-file --format env-no-quotes \
          --project "$project" --config "$config" \
          | grep -v "^DOPPLER_" \
          | flyctl secrets import --stage --app "$app"
        ;;
      none)
        echo "Policy none for $svc: importing no secrets."
        refuse_unpermitted "$app" none ""
        ;;
      allowlist)
        names=$(printf '%s' "$pol" | jq -r '.allowlist[]' | tr -d '\r')
        all=$(doppler secrets download --no-file --format json \
                --project "$project" --config "$config") \
          || fail "could not read the Doppler config for $svc"

        # Exact names, looked up by key. No pattern is ever applied to a name.
        missing=""
        while IFS= read -r n; do
          printf '%s' "$all" | jq -e --arg n "$n" 'has($n) and (.[$n] | type == "string") and (.[$n] | length > 0)' >/dev/null \
            || missing="$missing $n"
        done <<< "$names"
        [ -z "$missing" ] || fail "$svc requests secret(s) missing or empty in Doppler config $config:$missing"

        # dotenv has no safe encoding for these, and a silently altered
        # credential is worse than a refused deploy.
        printf '%s' "$all" | jq -e --argjson names "$(printf '%s' "$pol" | jq -c .allowlist)" '
          [ $names[] as $n | .[$n] | (test("[\r\n]") or test("^[\"'"'"']")) ] | any | not' >/dev/null \
          || fail "an allowlisted value for $svc contains a line break or starts with a quote; it cannot be imported safely"

        refuse_unpermitted "$app" allowlist "$names"

        printf '%s' "$all" | jq -r --argjson names "$(printf '%s' "$pol" | jq -c .allowlist)" \
          '. as $a | $names[] | "\(.)=\($a[.])"' \
          | tr -d '\r' \
          | flyctl secrets import --stage --app "$app"
        echo "Imported $(printf '%s\n' "$names" | wc -l | tr -d ' ') allowlisted secret(s) for $svc."
        ;;
      *) fail "unknown policy: $policy" ;;
    esac
    ;;

  verify)
    svc="${1:?service}"; app="${2:?app}"; root="${3:-services}"
    pol=$("$descriptor" policy "$svc" "$root") || exit 1
    policy=$(printf '%s' "$pol" | jq -r .policy | tr -d '\r')
    case "$policy" in
      inherit) echo "Policy inherit for $svc: nothing to verify." ;;
      none)
        refuse_unpermitted "$app" none ""
        echo "$app holds no secrets, as policy none requires."
        ;;
      allowlist)
        refuse_unpermitted "$app" allowlist "$(printf '%s' "$pol" | jq -r '.allowlist[]' | tr -d '\r')"
        echo "$app holds only allowlisted secrets."
        ;;
      *) fail "unknown policy: $policy" ;;
    esac
    ;;

  *) fail "usage: service-secrets.sh apply|verify ..." ;;
esac
