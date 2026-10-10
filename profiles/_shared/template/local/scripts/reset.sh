#!/usr/bin/env bash
# Tears down the local stack, deletes its volumes, and re-bootstraps.
#
# DESTRUCTIVE -- every local database, queue and object-storage volume of this
# project's compose stack is deleted permanently, with no undo. That includes
# the local ZITADEL database: its organizations, users, OIDC applications and
# the instance itself, so every client id, client secret and token issued by it
# stops working.
#
# This is the only reset entry point: `make reset` and `pnpm stack:reset` both
# call it. Every guard below fails closed -- when it cannot prove the reset is
# local, confirmed and scoped to this checkout, it refuses. Do not remove or
# weaken any of them to make the script faster. Ported from Docoris D-018
# (docs/RISKS.md there), which found the unguarded `down --volumes` this
# replaces.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# Compose needs stack.mjs's values even to exec or stop; none is a secret.
[ -f "$ROOT/local/scripts/compose-env.sh" ] && . "$ROOT/local/scripts/compose-env.sh"
PROFILE="${KORAS_PROFILE:-product}"
ENV_LOCAL="$ROOT/.env.local"
COMPOSE_FILE="$ROOT/local/docker-compose.yml"

# One rendered compose file per project -- the profile decided what went into it
# at generation time, so there is nothing to layer here.
COMPOSE_FILES="-f $COMPOSE_FILE"

# ── Argument parsing ─────────────────────────────────────────────────────────
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force|--yes|-y)
      FORCE=1
      ;;
    -h|--help)
      cat <<'USAGE'
Usage: reset.sh [--force|--yes]

DESTRUCTIVE. Tears down this project's local Docker stack, deletes every one of
its volumes (database -- including the local ZITADEL instance -- queue, object
storage) and re-bootstraps from scratch. .env.local is moved aside, not
deleted.

Before doing anything it refuses to run unless:
  1. this is the main checkout, not a linked git worktree -- worktrees share
     the compose project name, so a reset there would delete the main
     checkout's volumes;
  2. the compose project name can be read from local/docker-compose.yml;
  3. every endpoint configured in .env.local, DOCKER_HOST (if set), and the
     active docker context all look local (localhost / 127.0.0.0/8 / ::1 /
     *.localhost). If the active docker context cannot be determined, that
     also refuses rather than assuming it is local;
  4. the volumes it would delete can be listed, and are listed to you; and
  5. you confirm: interactively by typing the project name, or
     non-interactively with --force / --yes / -y. With neither, a
     non-interactive run (no TTY) refuses rather than hanging or guessing.

Options:
  --force, --yes, -y   Skip the interactive confirmation prompt (guards 1-4
                       still apply).
  -h, --help           Show this help and exit.
USAGE
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg (see --help)" >&2
      exit 1
      ;;
  esac
done

refuse() {
  echo "Refusing to reset: $1" >&2
  echo "$2" >&2
  exit 1
}

# ── Guard 1: the main checkout, never a linked worktree ──────────────────────
#
# The compose file sets a fixed `name:`, so every worktree of this repository
# drives the same compose project and the same volumes as the main checkout. A
# reset from a feature worktree would delete the main checkout's databases. A
# directory that is not a git repository at all cannot be a worktree, and
# proceeds to the other guards.
if command -v git >/dev/null 2>&1 \
    && git_dir="$(git -C "$ROOT" rev-parse --absolute-git-dir 2>/dev/null)"; then
  common_dir="$(cd "$ROOT" && cd "$(git rev-parse --git-common-dir)" && pwd -P)"
  git_dir="$(cd "$git_dir" && pwd -P)"
  if [ "$git_dir" != "$common_dir" ]; then
    refuse "${ROOT} is a linked git worktree." \
      "Its compose project is the main checkout's, so this would delete the main checkout's volumes. Reset from the main checkout, deliberately."
  fi
fi

# ── Guard 2: know exactly which compose project this is ──────────────────────
[ -f "$COMPOSE_FILE" ] || refuse "${COMPOSE_FILE} does not exist." \
  "reset.sh only resets the stack that file defines."
PROJECT="$(sed -nE 's/^name:[[:space:]]*["'\'']?([A-Za-z0-9_.-]+)["'\'']?[[:space:]]*$/\1/p' "$COMPOSE_FILE" | head -n1)"
[ -n "$PROJECT" ] || refuse "no top-level 'name:' in ${COMPOSE_FILE}." \
  "Without it the compose project name is derived from a directory name, and reset.sh cannot tell which volumes it would delete."

# ── Guard 3: every configured endpoint must look local ──────────────────────
#
# `docker compose down --volumes` is scoped to whatever this shell's
# environment actually points at. A shell that has sourced a deployed
# environment's variables -- a copy-paste from Doppler, a forgotten `export`
# left over from another terminal -- would otherwise run exactly the same
# irreversible command against something that is not this developer's laptop.
#
# The whole host is anchored, never merely searched for a substring, because
# "localhost.attacker.example" and "127.0.0.1.attacker.example" are ordinary
# registrable domains that a substring check would wave through. `*.localhost`
# is reserved as loopback by RFC 6761 and is what .env.local.example uses.
LOOPBACK_HOST_RE='^(localhost|127\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|\[?::1\]?|[a-z0-9]([a-z0-9-]*[a-z0-9])?\.localhost)$'

# Extracts the host from a URL, or returns a bare hostname unchanged
# (SMTP_HOST is not a URL). Strips scheme, credentials, path and port.
host_of() {
  local value="$1"
  value="${value#*://}"
  value="${value%%/*}"
  value="${value##*@}"
  case "$value" in
    \[*) printf '%s\n' "${value%%]*}]" ;;   # IPv6 literal -- keep the brackets, drop any :port
    *) printf '%s\n' "${value%%:*}" ;;
  esac
}

check_local_endpoint() {
  local name="$1" value="$2" host host_lc
  [ -z "$value" ] && return 0
  host="$(host_of "$value")"
  host_lc="$(printf '%s' "$host" | tr '[:upper:]' '[:lower:]')"
  if ! [[ "$host_lc" =~ $LOOPBACK_HOST_RE ]]; then
    refuse "${name} does not look local (host '${host}' is not localhost/127.0.0.0/8/::1/*.localhost)." \
      "This script only tears down the LOCAL docker stack. If this really is your local environment, fix ${name} in ${ENV_LOCAL}; otherwise this shell has a non-local value loaded and reset.sh will not run against it."
  fi
}

# CORS_ORIGINS is a JSON array of URLs, not a single endpoint -- every element's
# host is checked individually.
check_local_endpoint_list() {
  local name="$1" value="$2" item stripped
  [ -z "$value" ] && return 0
  stripped="${value#\[}"
  stripped="${stripped%\]}"
  local IFS=','
  local -a items=($stripped)
  for item in "${items[@]}"; do
    item="${item//\"/}"
    item="${item#"${item%%[![:space:]]*}"}"
    item="${item%"${item##*[![:space:]]}"}"
    [ -z "$item" ] && continue
    check_local_endpoint "$name" "$item"
  done
}

if [ -f "$ENV_LOCAL" ]; then
  # Every endpoint-shaped setting, by name, rather than a hand-kept list that
  # has to be re-enumerated whenever .env.local.example gains one. Read from the
  # file, never sourced: this only needs to look at the values. The AI provider
  # keys are credentials, not endpoints, and do not match these suffixes.
  while IFS= read -r line; do
    name="${line%%=*}"
    value="${line#*=}"
    value="${value%$'\r'}"
    case "$name" in
      CORS_ORIGINS) check_local_endpoint_list "$name" "$value" ;;
      *) check_local_endpoint "$name" "$value" ;;
    esac
  done < <(grep -E '^[A-Z0-9_]*(_URL|_URI|_HOST|_DOMAIN|_ENDPOINT|_ORIGINS)=' "$ENV_LOCAL" || true)
else
  echo "==> No ${ENV_LOCAL} found; nothing to check there before re-bootstrapping."
fi

# DOCKER_HOST decides which daemon `docker compose` talks to. A unix:// or
# npipe:// socket (or unset, the default) is local by construction.
if [ -n "${DOCKER_HOST:-}" ]; then
  case "$DOCKER_HOST" in
    unix://*|npipe://*) : ;;
    *) check_local_endpoint "DOCKER_HOST" "$DOCKER_HOST" ;;
  esac
fi

# `docker context` is a second way to point every docker invocation at a
# remote daemon, and it is invisible in DOCKER_HOST. Fail closed: if the active
# context cannot be determined, refuse rather than skip the check.
if ! context_name="$(docker context show 2>/dev/null)" || [ -z "$context_name" ]; then
  refuse "could not determine the active docker context (docker context show failed or returned nothing)." \
    "reset.sh cannot verify docker is pointed at your local daemon without this, so it refuses rather than guessing."
fi
# Docker Desktop's contexts (`desktop-linux`, `desktop-windows`) are not
# `default`, so they are inspected like any other rather than trusted by name.
if [ "$context_name" != "default" ]; then
  if ! context_host="$(docker context inspect "$context_name" --format '{{.Endpoints.docker.Host}}' 2>/dev/null)" || [ -z "$context_host" ]; then
    refuse "could not inspect the active docker context '${context_name}' to verify it is local." \
      "reset.sh refuses when it cannot verify the active docker context points at a local daemon."
  fi
  case "$context_host" in
    unix://*|npipe://*) : ;;
    *) check_local_endpoint "docker context '${context_name}'" "$context_host" ;;
  esac
fi

# ── Guard 4: show what would be deleted ──────────────────────────────────────
#
# Read-only. A confirmation is only informed if it names what it confirms, and
# if the list cannot be produced the daemon is not answering the way this
# script assumes -- which is a reason to stop, not to proceed.
if ! volumes="$(docker volume ls --filter "label=com.docker.compose.project=${PROJECT}" --format '{{.Name}}' 2>/dev/null)"; then
  refuse "could not list the volumes of compose project '${PROJECT}'." \
    "reset.sh will not delete what it cannot first show you."
fi
echo "Compose project: ${PROJECT}"
if [ -n "$volumes" ]; then
  echo "Volumes that will be PERMANENTLY deleted:"
  printf '  %s\n' $volumes
else
  echo "No volumes currently exist for '${PROJECT}'."
fi

# ── Guard 5: explicit confirmation ───────────────────────────────────────────
#
# No flag and no TTY must refuse, not hang and not guess. The word to type is
# the project name rather than a fixed "reset", so muscle memory from another
# project's prompt does not confirm this one.
if [ "$FORCE" -ne 1 ]; then
  if [ -t 0 ]; then
    read -r -p "Type the project name (${PROJECT}) to delete these volumes: " confirmation
    if [ "$confirmation" != "$PROJECT" ]; then
      echo "Aborted: confirmation not given." >&2
      exit 1
    fi
  else
    refuse "no --force/--yes given and this shell has no TTY to confirm on." \
      "reset.sh is destructive and never proceeds unattended without an explicit flag. Re-run with --force (or --yes) if this is intentional."
  fi
fi

echo "==> Resetting local environment (all data will be lost)..."
docker compose $COMPOSE_FILES down --volumes --remove-orphans

# Moved aside, never deleted: it can hold hand-entered values -- SESSION_SECRET,
# provider keys -- that nothing regenerates. Bootstrap writes a fresh one.
if [ -f "$ENV_LOCAL" ]; then
  kept="$ENV_LOCAL.pre-reset-$(date +%Y%m%d-%H%M%S)"
  mv "$ENV_LOCAL" "$kept"
  echo "--> Kept the previous .env.local as ${kept}"
fi

echo "--> Re-bootstrapping..."
KORAS_PROFILE="$PROFILE" bash "$ROOT/local/scripts/bootstrap.sh"
