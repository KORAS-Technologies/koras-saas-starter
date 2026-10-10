#!/usr/bin/env bash
# Read-only preflight for the local stack: warns, never changes anything.
#
# Checks three things that otherwise surface as confusing failures halfway
# through `make dev` or `make bootstrap`, or not at all:
#
#   1. Missing configuration -- local/.env (resolved ports), .env.local,
#      certificates, the ZITADEL machine PAT and provisioned.env.
#   2. Secrets -- the local ZITADEL instance (ADRs 0015-0017): a base compose
#      file that would start ZITADEL on an environment key or hand it a
#      password, a cached masterkey or admin password that is ZITADEL's public
#      default, and .env.local values still holding a `<...>` template
#      placeholder, a key, or a too-short SESSION_SECRET.
#   3. Occupied ports -- every KORAS_PORT_* in local/.env that something other
#      than this project's own running containers is listening on.
#
# It never starts, stops or removes anything, never writes a file, and never
# prints a secret value -- only the names of settings and the ports. Exit 0
# with warnings, so it can run in front of `make dev`; `--strict` exits 1 when
# there is any warning, for CI or a deliberate check. An ERROR exits 1 always:
# those are the findings that would start a secure instance unsafely, and
# `make dev` stops on them.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT/local/docker-compose.yml"
PORTS_ENV="$ROOT/local/.env"
ENV_LOCAL="$ROOT/.env.local"

STRICT=0
for arg in "$@"; do
  case "$arg" in
    --strict) STRICT=1 ;;
    -h|--help)
      echo "Usage: preflight.sh [--strict]   (read-only; --strict exits 1 on any warning)"
      exit 0
      ;;
    *) echo "Unknown argument: $arg (see --help)" >&2; exit 2 ;;
  esac
done

WARNINGS=0
ERRORS=0
error() {
  ERRORS=$((ERRORS + 1))
  echo "  ERROR $1"
  [ -n "${2:-}" ] && echo "        $2"
  return 0
}
warn() {
  WARNINGS=$((WARNINGS + 1))
  echo "  WARN  $1"
  [ -n "${2:-}" ] && echo "        $2"
  return 0
}
ok() { echo "  ok    $1"; }

# Fingerprints, not values, of ZITADEL's public placeholder masterkey and its
# default admin password: neither value appears in any file a generated project
# carries except the legacy-recovery override, which is the one place the
# placeholder may be used. A masterkey encrypts an instance's signing keys and
# secrets at rest and cannot be changed afterwards, so an instance created on
# the placeholder is readable by anyone who has its database.
PLACEHOLDER_FINGERPRINT='d67cc271c12ad6f95c1b10db7acaf1e69fa8453ef84c898df920faf5d4364f3e'
DEFAULT_PASSWORD_FINGERPRINT='1d707811988069ca760826861d6d63a10e8c3b7f171c4441a6472ea58c11711b'

# From stdin: given a path with a backslash in it, GNU sha256sum escapes the
# name and prefixes its output line with one, which no fingerprint matches.
sha256_of_file() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum < "$1" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 < "$1" | cut -d' ' -f1
  fi
}

echo "Preflight (read-only): $ROOT"

# ── 1. Configuration ─────────────────────────────────────────────────────────
echo "Configuration:"
PROJECT=""
if [ -f "$COMPOSE_FILE" ]; then
  PROJECT="$(sed -nE 's/^name:[[:space:]]*["'\'']?([A-Za-z0-9_.-]+)["'\'']?[[:space:]]*$/\1/p' "$COMPOSE_FILE" | head -n1)"
  if [ -n "$PROJECT" ]; then
    ok "local/docker-compose.yml (compose project '${PROJECT}')"
  else
    warn "local/docker-compose.yml has no top-level 'name:'" \
      "The compose project would be named after a directory, and its volumes with it."
  fi
else
  warn "local/docker-compose.yml is missing" "Nothing can start without it."
fi

if [ -f "$PORTS_ENV" ]; then
  ok "local/.env (resolved host ports)"
else
  warn "local/.env is missing: host ports have not been resolved" \
    "Run 'make ports' (or 'make bootstrap'). Until then compose falls back to template defaults."
fi

if [ -f "$ENV_LOCAL" ]; then
  ok ".env.local"
else
  warn ".env.local is missing" "Run 'make bootstrap'; apps and services refuse to start without it."
fi

if compgen -G "$ROOT/local/certs/*.pem" >/dev/null; then
  ok "local/certs (mkcert certificates)"
else
  warn "local/certs has no certificates" "The proxy cannot serve https://*.localhost. 'make bootstrap' generates them."
fi

if [ -s "$ROOT/local/zitadel/machinekey/pat" ]; then
  ok "local/zitadel/machinekey/pat (machine user PAT present; not read)"
else
  warn "local/zitadel/machinekey/pat is missing or empty" \
    "ZITADEL writes it only when the instance is first created. If the instance already exists, provision.py cannot run against it -- see local/zitadel/init.sh."
fi

if [ -f "$ROOT/local/zitadel/provisioned.env" ]; then
  ok "local/zitadel/provisioned.env"
else
  warn "local/zitadel/provisioned.env is missing" "ZITADEL has not been provisioned on this machine ('make bootstrap')."
fi

# ── 2. Secrets ───────────────────────────────────────────────────────────────
echo "Secrets (names only, values are never printed):"
KORAS_DIR="${KORAS_HOME:-$HOME/.koras}"
STATE_FILE="$KORAS_DIR/state/${PROJECT:-unknown}/zitadel.json"
MODE=""
if [ -n "$PROJECT" ] && [ -f "$STATE_FILE" ]; then
  MODE="$(sed -nE 's/^[[:space:]]*"mode":[[:space:]]*"([a-z-]+)".*/\1/p' "$STATE_FILE" | head -n1)"
  case "$MODE" in
    secure) ok "local ZITADEL instance recorded (secure)" ;;
    legacy-recovery) warn "the local ZITADEL instance is in legacy-recovery mode" \
      "It runs on the public placeholder key until it is replaced by a new secure instance (ADR 0015)." ;;
    *) error "the ZITADEL state file has an unknown mode: ${MODE:-none}" "Nothing will start against it." ;;
  esac
  if [ "$MODE" = "secure" ] && grep -qE '"status":[[:space:]]*"unescrowed"' "$STATE_FILE"; then
    warn "the local ZITADEL masterkey is not escrowed on both legs" "Run 'node local/scripts/stack.mjs escrow'; 'make dev' refuses until it is."
  fi
else
  warn "no local ZITADEL instance is recorded" "'make bootstrap' provisions one: node local/scripts/stack.mjs provision --fresh."
fi
# Comment lines are not configuration: the base file's own comments name what
# it must never do.
uncommented() { grep -vE '^[[:space:]]*#' "$1" || true; }
if [ -f "$COMPOSE_FILE" ]; then
  # The base file starts ZITADEL from a key *file* and never initialises it.
  # An environment key is how the placeholder used to reach it.
  if uncommented "$COMPOSE_FILE" | grep -qE 'masterkeyFromEnv|ZITADEL_MASTERKEY:'; then
    error "local/docker-compose.yml starts ZITADEL on an environment masterkey" \
      "The base file must pass --masterkeyFile only. Do NOT change the key of an existing instance; legacy instances use local/docker-compose.legacy-zitadel.yml."
  fi
  if uncommented "$COMPOSE_FILE" | grep -q 'start-from-init'; then
    error "local/docker-compose.yml can initialise ZITADEL" "Only local/docker-compose.init.yml, applied by stack.mjs provision, may say start-from-init."
  fi
fi
# A password reaches ZITADEL only through the init steps file stack.mjs
# renders and deletes. One in a compose file or config.yaml is in the clear.
for file in "$COMPOSE_FILE" "$ROOT/local/docker-compose.init.yml" "$ROOT/local/zitadel/config.yaml"; do
  [ -f "$file" ] || continue
  if uncommented "$file" | grep -qE 'ZITADEL_FIRSTINSTANCE_ORG_HUMAN_PASSWORD:|^[[:space:]]+Password:'; then
    error "${file#"$ROOT/"} sets a ZITADEL admin password" "Remove it; every instance gets a generated password (ADR 0017)."
  fi
done
if [ "$MODE" = "secure" ]; then
  SECRETS_DIR="$KORAS_DIR/secrets/${PROJECT}/dev"
  if [ -f "$SECRETS_DIR/zitadel-masterkey" ] && [ "$(sha256_of_file "$SECRETS_DIR/zitadel-masterkey")" = "$PLACEHOLDER_FINGERPRINT" ]; then
    error "the cached ZITADEL masterkey is the public placeholder" "A secure instance never runs on it. It was not changed."
  fi
  if [ -f "$SECRETS_DIR/zitadel-admin-password" ] && [ "$(sha256_of_file "$SECRETS_DIR/zitadel-admin-password")" = "$DEFAULT_PASSWORD_FINGERPRINT" ]; then
    error "the cached ZITADEL admin password is ZITADEL's default" "Every instance gets a generated one (ADR 0017)."
  fi
fi
if [ -f "$ENV_LOCAL" ]; then
  if grep -qE '^ZITADEL_MASTERKEY=' "$ENV_LOCAL"; then
    warn ".env.local sets ZITADEL_MASTERKEY" \
      "Nothing reads it there -- the key is a file under ~/.koras/secrets -- and a copy of a key does not belong in an app env file. Remove the line."
  fi
  placeholders="$(grep -E '^[A-Z0-9_]+=.*<[^>]+>' "$ENV_LOCAL" | cut -d= -f1 | tr '\n' ' ' || true)"
  if [ -n "$placeholders" ]; then
    warn ".env.local still has template placeholders: ${placeholders}" \
      "Fill them from provisioned.env or Doppler; a '<...>' value reaches the app as a literal string."
  fi
  session_len="$( { grep -E '^SESSION_SECRET=' "$ENV_LOCAL" || true; } | tail -n1 | cut -d= -f2- | tr -d '\r' | wc -c | tr -d ' ')"
  if grep -qE '^SESSION_SECRET=' "$ENV_LOCAL" && [ "$((session_len - 1))" -lt 32 ]; then
    warn "SESSION_SECRET in .env.local is shorter than 32 characters"
  fi
fi

# ── 3. Occupied ports ────────────────────────────────────────────────────────
echo "Ports (from local/.env):"
if [ -f "$PORTS_ENV" ]; then
  # Host ports this project's own running containers publish. A port they hold
  # is the stack running, not a conflict. Read-only `docker ps`; if docker is
  # not answering, every listener is reported and the docker problem with it.
  own_ports=" "
  if [ -n "$PROJECT" ] && command -v docker >/dev/null 2>&1; then
    if published="$(docker ps --filter "label=com.docker.compose.project=${PROJECT}" --format '{{.Ports}}' 2>/dev/null)"; then
      # `|| true`: no published port is a normal answer, and under pipefail a
      # grep that matches nothing would otherwise end the script right here.
      own_ports=" $( { printf '%s\n' "$published" | grep -oE ':[0-9]+->' | grep -oE '[0-9]+' || true; } | sort -u | tr '\n' ' ')"
    else
      warn "docker is not answering ('docker ps' failed)" "Is Docker Desktop running?"
    fi
  fi

  listening() {
    # A connect to loopback either succeeds or is refused immediately; nothing
    # here waits on a timeout, and nothing is sent.
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
  }

  while IFS= read -r line; do
    name="${line%%=*}"
    port="${line#*=}"
    port="${port%$'\r'}"
    case "$port" in ''|*[!0-9]*) continue ;; esac
    if listening "$port"; then
      case "$own_ports" in
        *" $port "*) ok "${name}=${port} (held by this stack's containers)" ;;
        *) warn "${name}=${port} is already in use by another process" \
             "Free it, or run 'make ports' to re-resolve -- but if ${name} is KORAS_PORT_ZITADEL on an existing instance, moving it changes the issuer every client was registered against." ;;
      esac
    fi
  done < <(grep -E '^KORAS_PORT_[A-Z0-9_]+=' "$PORTS_ENV" || true)
else
  echo "  skip  no local/.env, so no ports to check"
fi

echo ""
if [ "$ERRORS" -gt 0 ]; then
  echo "Preflight: ${ERRORS} error(s), ${WARNINGS} warning(s). Nothing was changed."
  exit 1
fi
if [ "$WARNINGS" -eq 0 ]; then
  echo "Preflight: no warnings."
else
  echo "Preflight: ${WARNINGS} warning(s). Nothing was changed."
fi
if [ "$STRICT" -eq 1 ] && [ "$WARNINGS" -gt 0 ]; then
  exit 1
fi
exit 0
