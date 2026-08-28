#!/usr/bin/env bash
# Re-register this environment with the KORAS Control Plane.
#
#     bash local/scripts/register-with-control-plane.sh <dev|test|stg|prod>
#
# The contract is `koras-control-plane/docs/PRODUCT_REGISTRATION_CONTRACT.md`,
# and it is authoritative. What follows is why this exists at all, and what it
# can and cannot carry -- the long version is docs/REGISTRATION_LIFECYCLE.md in
# the starter.
#
# `create-koras-app` registers a product once, immediately after `terraform
# apply`, from the outputs of that apply. That is the only moment it knows the
# whole estate, and it was also the last moment anything knew: nothing re-sent
# a reference afterwards. A service added later, an environment provisioned
# later, a rotated ZITADEL project, or a product generated before its Control
# Plane existed (R-001, the documented bootstrap order) all left the registry
# holding the day the project was generated. Reconciliation compares the
# registry against reality, so every one of those became drift nobody could
# explain.
#
# So this runs after each environment deploys, and re-sends what that
# deployment just proved.
#
# -- What makes a partial payload safe ----------------------------------------
#
# Only because the Control Plane's persistence says so, and it was read before
# this was written rather than assumed:
#
#   environments   upserted, never pruned -- sending only `prod` leaves the
#                  other three environments' rows exactly as they were
#   references     upserted, never pruned -- an omitted reference goes stale,
#                  it does not disappear
#   services       *pruned* within the environment -- anything not named here
#                  is deleted, so the list below has to be right
#   product row    every column is overwritten from the request, including
#                  with NULL. `primary_domain`, `starter_version` and
#                  `profile_version` are therefore mandatory here: sending the
#                  request without them would blank three correct values.
#
# That last one is why this script refuses rather than guesses. A registration
# that quietly empties three columns is worse than one that did not run.
#
# -- What this pass cannot carry ----------------------------------------------
#
#   supabase_project_ref   only reachable through DATABASE_URL, which is a
#                          credential. Not read here. Left at whatever
#                          generation-time registration sent.
#   vercel_projects        the project ids are per-application repository
#                          secrets; collecting them into one job means copying
#                          them somewhere they are not today, for a reference
#                          that already survives in the registry.
#
# Both are upsert-only fields, so omitting them ages them rather than losing
# them. A *newly added application* is the one case this pass misses, and it
# misses it visibly: the registry goes on listing the applications it knew.
#
# In exchange it carries one thing generation-time registration cannot.
# `zitadel_client_id` is marked sensitive as a Terraform output, so the
# generator will not read it -- correctly; un-marking an output so a payload
# can carry it is exactly the trade that contract exists to refuse. Here it is
# a plain non-secret setting in Doppler, and the Control Plane's own schema
# lists it as public by nature.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MANIFEST="${ROOT}/.koras/project.yaml"
TFVARS="${ROOT}/infrastructure/terraform/terraform.tfvars"
ENVIRONMENT="${1:-${ENVIRONMENT:-}}"

if [ -z "$ENVIRONMENT" ]; then
  echo "usage: $0 <dev|test|stg|prod>" >&2
  exit 2
fi

case "$ENVIRONMENT" in
  dev|test|stg|prod) ;;
  *)
    echo "Unknown environment '${ENVIRONMENT}'. The Control Plane accepts dev, test, stg, prod." >&2
    exit 2
    ;;
esac

if [ ! -f "$MANIFEST" ]; then
  echo "No .koras/project.yaml. Cannot tell which profile this is; refusing to guess." >&2
  exit 2
fi

# Reads from .koras/project.yaml, which is the authoritative record of what this
# repository is -- not the directory name, not the git remote, not a guess from
# the code.
manifest_value() {
  sed -n "s/^[[:space:]]*$1:[[:space:]]*//p" "$MANIFEST" | head -1 | tr -d '[:space:]"'
}

PROFILE="$(manifest_value profile)"

case "$PROFILE" in
  product)
    ;;
  control-plane)
    # Not a skip for tidiness. The Control Plane is platform infrastructure,
    # not an entry in its own product registry, and registering it would make
    # it a customer of itself -- invariant 2. It is refused at three
    # independent places already (the generator's guard, a validator on the
    # Control Plane's `profile` field, and a database constraint); this is the
    # fourth, and it is the one that earns its keep, because `deploy.yml` is
    # shared by both profiles and this script therefore ships to both.
    echo "Profile is control-plane: it is the registry, not an entry in it. Nothing to register."
    exit 0
    ;;
  *)
    echo "Unrecognised profile '${PROFILE}' in .koras/project.yaml." >&2
    exit 2
    ;;
esac

for tool in jq curl doppler; do
  command -v "$tool" >/dev/null 2>&1 || { echo "$tool is required." >&2; exit 2; }
done

REPOSITORY="${GITHUB_REPOSITORY:-}"
REPOSITORY_NAME="${REPOSITORY##*/}"
if [ -z "$REPOSITORY_NAME" ]; then
  echo "GITHUB_REPOSITORY is not set. It supplies both the repository reference and the" >&2
  echo "Doppler project name, which everything else here is derived from." >&2
  exit 2
fi

DOPPLER_PROJECT="$REPOSITORY_NAME"

# A reference, by name, out of this environment's Doppler config. Never a
# credential: every name passed to this is an identifier the Control Plane's
# own schema lists as public. An absent one comes back empty rather than fatal.
reference() {
  doppler secrets get "$1" --plain \
    --project "$DOPPLER_PROJECT" --config "$ENVIRONMENT" 2>/dev/null \
    | tr -d '[:space:]' || true
}

BASE_URL="$(reference KORAS_CONTROL_PLANE_URL)"

if [ -z "$BASE_URL" ]; then
  # R-001, and the same rule the generator applies at generation time: no
  # Control Plane configured is the documented bootstrap order, not a failure.
  # The first product in a new estate is provisioned before the registry it
  # would register with exists.
  echo "No Control Plane is configured for ${ENVIRONMENT} (KORAS_CONTROL_PLANE_URL is unset)."
  echo "Nothing was registered. This is the expected bootstrap order for the first"
  echo "project in an estate; set the URL and token in Doppler once one is live."
  exit 0
fi

# ...and the other half of that rule. A Control Plane named with nothing to
# authorise the call is a misconfiguration, and a misconfiguration reported as
# nothing-to-do is one nobody fixes.
TOKEN="$(reference KORAS_CONTROL_PLANE_TOKEN)"
if [ -z "$TOKEN" ]; then
  echo "KORAS_CONTROL_PLANE_URL is set for ${ENVIRONMENT} but KORAS_CONTROL_PLANE_TOKEN is not." >&2
  echo "Registration sends a bearer token; store it in Doppler alongside the URL." >&2
  exit 1
fi

case "$BASE_URL" in
  https://*) ;;
  http://localhost*|http://127.0.0.1*) ;;
  *)
    echo "KORAS_CONTROL_PLANE_URL must be https (a loopback address may be http)." >&2
    echo "Registration sends a bearer token in a request header." >&2
    exit 1
    ;;
esac
BASE_URL="${BASE_URL%/}"

# -- Identity -----------------------------------------------------------------
# Written wholesale onto the product row, so an empty one blanks a correct
# value. Missing is a refusal here, never a null on the wire.
CODE="$(manifest_value slug)"
NAME="$(manifest_value name)"
STARTER_VERSION="$(manifest_value starter_version)"
PROFILE_VERSION="$(manifest_value profile_version)"

PRIMARY_DOMAIN=""
if [ -f "$TFVARS" ]; then
  PRIMARY_DOMAIN="$(sed -n 's/^[[:space:]]*primary_domain[[:space:]]*=[[:space:]]*"\(.*\)"[[:space:]]*$/\1/p' "$TFVARS" | head -1)"
fi

missing=""
[ -n "$CODE" ]            || missing="$missing project.slug"
[ -n "$NAME" ]            || missing="$missing project.name"
[ -n "$STARTER_VERSION" ] || missing="$missing generator.starter_version"
[ -n "$PROFILE_VERSION" ] || missing="$missing generator.profile_version"
[ -n "$PRIMARY_DOMAIN" ]  || missing="$missing terraform.tfvars:primary_domain"

if [ -n "$missing" ]; then
  echo "Refusing to register: cannot read$missing." >&2
  echo "" >&2
  echo "Each of these is written wholesale onto the product row, so sending the request" >&2
  echo "without them would replace a correct value with nothing. A registration that" >&2
  echo "quietly empties a column is worse than one that did not run." >&2
  exit 1
fi

# -- What is deployed here ----------------------------------------------------
# The same rule deploy.yml's `discover` job uses, and deliberately so: the
# registry should describe what this pipeline actually deploys rather than what
# the project was generated with. Requiring both files means a half-scaffolded
# directory is not registered as a running service.
#
# This list is *pruned* by the Control Plane, so getting it wrong deletes rows.
services='[]'
if [ -d "${ROOT}/services" ]; then
  services=$(cd "$ROOT" && find services -mindepth 1 -maxdepth 1 -type d \
    -exec test -f '{}/Dockerfile' -a -f '{}/fly.toml' ';' -print \
    | xargs -rn1 basename | sort | jq -R . | jq -sc .)
fi

if [ "$services" = '[]' ]; then
  echo "No deployable service found under services/." >&2
  echo "Registering an empty service list would delete every service row the Control" >&2
  echo "Plane holds for ${ENVIRONMENT}, so this refuses instead." >&2
  exit 1
fi

# Fly names are a convention, not a lookup: deploy.yml deploys to exactly these
# names, so deriving them the same way means the registry names what was
# deployed, by the rule that deployed it.
fly_apps=$(printf '%s' "$services" | jq -c \
  --arg repo "$REPOSITORY_NAME" --arg env "$ENVIRONMENT" \
  'map({key: ., value: ($repo + "-" + . + "-" + $env)}) | from_entries')

# The base URL the Control Plane calls back on. The `verify` job has just proved
# this host is serving and reporting this environment, which is why this runs
# after it rather than beside it.
PLATFORM_API_BASE_URL="https://${REPOSITORY_NAME}-api-${ENVIRONMENT}.fly.dev"

ZITADEL_PROJECT_ID="$(reference ZITADEL_PROJECT_ID)"
ZITADEL_CLIENT_ID="$(reference ZITADEL_CLIENT_ID)"

# `del(.. | nulls)` rather than a null-valued field: the Control Plane
# distinguishes an absent reference from a null one, and absent is what leaves
# the stored value alone.
payload=$(jq -nc \
  --arg code "$CODE" \
  --arg name "$NAME" \
  --arg repository "$REPOSITORY" \
  --arg primary_domain "$PRIMARY_DOMAIN" \
  --arg starter_version "$STARTER_VERSION" \
  --arg profile_version "$PROFILE_VERSION" \
  --arg environment "$ENVIRONMENT" \
  --arg doppler_project "$DOPPLER_PROJECT" \
  --arg zitadel_project_id "$ZITADEL_PROJECT_ID" \
  --arg zitadel_client_id "$ZITADEL_CLIENT_ID" \
  --arg platform_api_base_url "$PLATFORM_API_BASE_URL" \
  --argjson services "$services" \
  --argjson fly_apps "$fly_apps" \
  '{
     code: $code,
     name: $name,
     slug: $code,
     repository: $repository,
     profile: "product",
     primary_domain: $primary_domain,
     starter_version: $starter_version,
     profile_version: $profile_version,
     environments: {
       ($environment): {
         infrastructure: {
           github_repository: $repository,
           doppler_project: $doppler_project,
           doppler_config: $environment,
           zitadel_instance: $environment,
           zitadel_project_id: (if $zitadel_project_id == "" then null else $zitadel_project_id end),
           zitadel_client_id: (if $zitadel_client_id == "" then null else $zitadel_client_id end),
           fly_apps: $fly_apps,
           platform_api_base_url: $platform_api_base_url
         },
         services: $services
       }
     }
   } | del(.. | nulls)')

# The Control Plane rejects secret-shaped field names rather than dropping them,
# which is the right behaviour and a poor place to find out. This is the same
# rule one hop earlier, so a field added here in future fails before it is sent
# rather than after.
if printf '%s' "$payload" | jq -e '
      [paths | map(tostring) | join(".")]
      | map(select(test("secret|token|password|credential|private_key|api_key|access_key"; "i")))
      | length > 0' >/dev/null; then
  echo "The payload has a field whose name looks like a credential. Refusing to send it." >&2
  exit 1
fi

echo "==> Registering ${CODE} (${ENVIRONMENT}) with ${BASE_URL}"
echo "    services:     $(printf '%s' "$services" | jq -r 'join(", ")')"
echo "    platform API: ${PLATFORM_API_BASE_URL}"

# The token is read into a variable and passed through a header. It is never
# echoed, never written to disk, and there is no `set -x` in this script for the
# same reason.
response="$(mktemp)"
trap 'rm -f "$response"' EXIT

# The exit code decides whether a response arrived at all; `%{http_code}` only
# describes one that did. Read separately rather than as
# `$(curl ... || echo 000)`, which appends a second value to whatever curl has
# already printed and produces a status matching none of the cases below --
# turning the one outcome that is meant to be tolerated into a hard failure.
set +e
status=$(curl -sS --max-time 30 -o "$response" -w '%{http_code}' \
  -X POST "${BASE_URL}/api/platform/v1/products" \
  -H 'content-type: application/json' \
  -H "authorization: Bearer ${TOKEN}" \
  --data-binary "$payload")
curl_status=$?
set -e
[ "$curl_status" -ne 0 ] && status='000'

case "$status" in
  200|201)
    # 201 on a re-registration is deliberate on the Control Plane's side rather
    # than a bug: `--provision` is re-runnable, so a second registration is an
    # update and not a conflict.
    echo "OK  Registered. The Control Plane holds this environment's references as of this deployment."
    jq -r '"    id: " + (.id // "?") + "   status: " + (.status // "?")' "$response" 2>/dev/null || true
    ;;
  000)
    # Unreachable is retryable, and a deployment that already succeeded should
    # not be reported as failed because a registry was briefly down. The next
    # deployment of this environment sends the same thing again.
    echo "The Control Plane at ${BASE_URL} could not be reached. Nothing was registered." >&2
    echo "The deployment itself is unaffected; the next one re-registers." >&2
    exit 0
    ;;
  422)
    echo "The Control Plane refused the payload (422)." >&2
    echo "  That is a contract mismatch rather than a credential problem: its request" >&2
    echo "  model forbids unknown fields. See PRODUCT_REGISTRATION_CONTRACT.md." >&2
    cat "$response" >&2
    exit 1
    ;;
  *)
    echo "Registration failed (HTTP ${status})." >&2
    cat "$response" >&2
    exit 1
    ;;
esac
