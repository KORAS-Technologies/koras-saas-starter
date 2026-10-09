#!/usr/bin/env bash
# Read-only preflight for the local stack: warns, never changes anything.
#
# Checks three things that otherwise surface as confusing failures halfway
# through `make dev` or `make bootstrap`, or not at all:
#
#   1. Missing configuration -- local/.env (resolved ports), .env.local,
#      certificates, the ZITADEL machine PAT and provisioned.env.
#   2. Placeholder secrets -- the public ZITADEL masterkey, and .env.local
#      values still holding a `<...>` template placeholder or a too-short
#      SESSION_SECRET.
#   3. Occupied ports -- every KORAS_PORT_* in local/.env that something other
#      than this project's own running containers is listening on.
#
# It never starts, stops or removes anything, never writes a file, and never
# prints a secret value -- only the names of settings and the ports. Exit 0
# with warnings, so it can run in front of `make dev`; `--strict` exits 1 when
# there is any warning, for CI or a deliberate check.
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
warn() {
  WARNINGS=$((WARNINGS + 1))
  echo "  WARN  $1"
  [ -n "${2:-}" ] && echo "        $2"
  return 0
}
ok() { echo "  ok    $1"; }

# The masterkey ZITADEL's own documentation uses. It encrypts the instance's
# signing keys and secrets at rest, so an instance created with it is readable
# by anyone who has the database. It cannot be rotated on an existing instance:
# changing it makes that instance's encrypted data unreadable.
PLACEHOLDER_MASTERKEY='MasterkeyNeedsToHave32Characters'

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

# ── 2. Placeholder secrets ───────────────────────────────────────────────────
echo "Secrets (names only, values are never printed):"
if [ -f "$COMPOSE_FILE" ] && grep -q "$PLACEHOLDER_MASTERKEY" "$COMPOSE_FILE"; then
  warn "local/docker-compose.yml starts ZITADEL with the public placeholder masterkey" \
    "Any instance it creates is decryptable by anyone with the database. Do NOT change the key on an existing instance -- it cannot be rotated, and the instance's encrypted data would become unreadable. Moving to a per-machine key means a new instance."
fi
if [ -f "$ENV_LOCAL" ]; then
  if grep -qE "^ZITADEL_MASTERKEY=${PLACEHOLDER_MASTERKEY}[[:space:]]*$" "$ENV_LOCAL"; then
    warn ".env.local sets ZITADEL_MASTERKEY to the public placeholder" \
      "Compose does not read .env.local, so this value has no effect -- but it is a copy of a key, and keys do not belong in an app env file."
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
if [ "$WARNINGS" -eq 0 ]; then
  echo "Preflight: no warnings."
else
  echo "Preflight: ${WARNINGS} warning(s). Nothing was changed."
fi
if [ "$STRICT" -eq 1 ] && [ "$WARNINGS" -gt 0 ]; then
  exit 1
fi
exit 0
