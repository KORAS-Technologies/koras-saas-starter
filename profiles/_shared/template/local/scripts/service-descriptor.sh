#!/usr/bin/env bash
# Reads services/<service>/service.yaml: the one place a service says where it
# deploys, what secrets it may hold, and whether it is reachable from outside.
#
#   service-descriptor.sh eligible <env> [services-dir]   JSON array of the service
#                                                         directories to deploy there
#   service-descriptor.sh policy   <service> [services-dir]   {"policy":..,"allowlist":[..]}
#   service-descriptor.sh network  <service> [services-dir]   public | private
#   service-descriptor.sh validate [services-dir]             every descriptor, or fail
#
# The Terraform Fly module reads the same files and applies the same rules; the
# starter's tests run both over one corpus and require identical answers. If a
# rule changes here it changes there in the same commit.
#
# A service with NO descriptor is the legacy case and must keep its legacy
# behaviour exactly: every environment, secrets inherited, public. A descriptor
# is only ever read, never required, and none is added to a service for
# consistency's sake.
#
# Strict on purpose. An unknown key, an unknown policy, an empty list, a wrong
# type and a misspelled environment all FAIL. A permissive reader turns a typo
# into a service deployed where it must not be, or holding secrets it must not
# have, and nothing downstream could tell.
set -euo pipefail

# The environment mapping is immutable (ADR required to change it).
VALID_ENVS='["dev","test","stg","prod"]'

fail() { echo "service-descriptor: $*" >&2; exit 1; }

need_jq() {
  command -v jq >/dev/null 2>&1 || fail "jq is required"
}

# yq is needed ONLY to read a descriptor that exists. A product with none -- every
# product that does not opt in -- never reaches this, so its deploy does not
# depend on yq being installed, exactly as it did not before descriptors.
need_yq() {
  command -v yq >/dev/null 2>&1 || fail "yq (mikefarah, v4) is required to read a service descriptor"
  # The Python tool of the same name has different syntax and would parse
  # these files into something else without complaint.
  yq --version 2>&1 | grep -q 'mikefarah' || fail "yq is not mikefarah/yq v4"
}

# The structural rules, in one place. Input: the parsed document. Output: the
# normalised descriptor, or an error message on stderr and a non-zero exit.
read -r -d '' NORMALISE <<'JQ' || true
def bad($m): error($m);
def is_env: type == "string" and (. as $e | $valid | index($e) != null);

if type != "object" then bad("not a mapping") else . end
| (keys - ["schema_version","environments","secrets","network"]) as $unknown
| if ($unknown | length) > 0 then bad("unknown key(s): " + ($unknown | join(", "))) else . end
| if (.schema_version | type) != "number" or .schema_version != 1 then bad("schema_version must be the number 1") else . end

| (if has("environments") then
    (.environments
     | if type != "array" then bad("environments must be a list")
       elif length == 0 then bad("environments must not be empty")
       elif any(.[]; is_env | not) then bad("environments may only name: " + ($valid | join(", ")))
       elif (unique | length) != length then bad("environments has duplicates")
       else . end)
  else null end) as $envs

| (if has("secrets") then
    (.secrets
     | if type != "object" then bad("secrets must be a mapping") else . end
     | (keys - ["policy","allowlist"]) as $u
     | if ($u | length) > 0 then bad("unknown secrets key(s): " + ($u | join(", "))) else . end
     | if (.policy | type) != "string" then bad("secrets.policy is required and must be a string") else . end
     | .policy as $p
     | if (["inherit","none","allowlist"] | index($p)) == null
       then bad("unknown secrets.policy: " + $p) else . end
     | if .policy == "allowlist" then
         (.allowlist
          | if type != "array" then bad("secrets.allowlist must be a list")
            elif length == 0 then bad("secrets.allowlist must not be empty; use policy none for no secrets")
            elif any(.[]; (type != "string") or (test("^[A-Z][A-Z0-9_]*$") | not)) then bad("secrets.allowlist entries must be exact names matching [A-Z][A-Z0-9_]*")
            elif any(.[]; startswith("DOPPLER_")) then bad("secrets.allowlist must not name DOPPLER_* variables")
            elif (unique | length) != length then bad("secrets.allowlist has duplicates")
            else {policy: "allowlist", allowlist: .} end)
       else
         (if has("allowlist") then bad("secrets.allowlist is only valid with policy allowlist") else {policy: .policy, allowlist: []} end)
       end)
  else {policy: "inherit", allowlist: []} end) as $sec

| (if has("network") then
    (.network | if . == "public" or . == "private" then . else bad("network must be public or private") end)
  else "public" end) as $net

| {environments: $envs, policy: $sec.policy, allowlist: $sec.allowlist, network: $net}
JQ

# One service's normalised descriptor, as JSON. Errors go to stderr.
descriptor() {
  local dir="$1" file="$1/service.yaml" parsed
  if [ ! -f "$file" ]; then
    # Legacy: no descriptor, no change in behaviour.
    echo '{"environments":null,"policy":"inherit","allowlist":[],"network":"public"}'
    return 0
  fi
  need_yq
  if ! parsed=$(yq -o=json '.' "$file" 2>&1 | tr -d '\r'); then
    echo "service-descriptor: $file: not valid YAML" >&2
    return 1
  fi
  # `yq` exits 0 on some malformed input and prints nothing useful; jq then
  # sees non-JSON, which is also a failure here.
  if ! printf '%s' "$parsed" | jq -c --argjson valid "$VALID_ENVS" "$NORMALISE" 2>/tmp/sd.$$; then
    echo "service-descriptor: $file: $(tr -d '\n' </tmp/sd.$$)" >&2
    rm -f /tmp/sd.$$
    return 1
  fi
  rm -f /tmp/sd.$$
}

check_env() {
  printf '%s' "$VALID_ENVS" | jq -e --arg e "$1" 'index($e) != null' >/dev/null \
    || fail "unknown environment: $1"
}

cmd="${1:-}"; shift || true
need_jq
case "$cmd" in
  eligible)
    env="${1:-}"; root="${2:-services}"
    [ -n "$env" ] || fail "usage: eligible <env> [services-dir]"
    check_env "$env"
    out='[]'
    if [ -d "$root" ]; then
      # A service is a directory that can actually be deployed. Requiring both
      # files means a half-scaffolded directory is skipped here rather than
      # failing three jobs later. Unchanged from before descriptors existed.
      while IFS= read -r name; do
        [ -n "$name" ] || continue
        d=$(descriptor "$root/$name") || exit 1
        if printf '%s' "$d" | jq -e --arg e "$env" '.environments == null or (.environments | index($e) != null)' >/dev/null; then
          out=$(printf '%s' "$out" | jq -c --arg n "$name" '. + [$n]' | tr -d '\r')
        fi
      done < <(find "$root" -mindepth 1 -maxdepth 1 -type d \
                 -exec test -f '{}/Dockerfile' -a -f '{}/fly.toml' ';' -print \
                 | xargs -rn1 basename | sort)
    fi
    printf '%s\n' "$out"
    ;;
  policy)
    svc="${1:-}"; root="${2:-services}"
    [ -n "$svc" ] || fail "usage: policy <service> [services-dir]"
    descriptor "$root/$svc" | jq -c '{policy, allowlist}'
    ;;
  network)
    svc="${1:-}"; root="${2:-services}"
    [ -n "$svc" ] || fail "usage: network <service> [services-dir]"
    descriptor "$root/$svc" | jq -r '.network' | tr -d '\r'
    ;;
  validate)
    root="${1:-services}"
    [ -d "$root" ] || exit 0
    for d in "$root"/*/; do
      [ -f "${d}service.yaml" ] || continue
      descriptor "${d%/}" >/dev/null || exit 1
    done
    echo "descriptors valid"
    ;;
  *) fail "usage: service-descriptor.sh eligible|policy|network|validate ..." ;;
esac
