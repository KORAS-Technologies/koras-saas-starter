#!/usr/bin/env bash
# Does the connection this service will use actually have row-level security
# applied to it?
#
# `alter table ... force row level security` binds the table's *owner* to its
# policies. It does nothing to a superuser, and nothing to a role holding
# BYPASSRLS -- both bypass unconditionally, forced or not. Measured:
#
#     connecting role        force   rows visible (2 tenants, context set to 1)
#     superuser              ON      2   <- bypassed
#     non-superuser owner    ON      1   <- isolated
#     non-superuser owner    OFF     2   <- bypassed
#
# A managed Postgres commonly issues a superuser as its default connection
# role, and a DATABASE_URL copied from a dashboard is usually that role. Such a
# deployment has correct policies, `force` on every table, a green policy suite,
# and no isolation whatsoever.
#
# The API checks this at startup and refuses to serve. That is the right place
# and it is late: the release is already out, and the failure presents as a
# service that will not boot rather than as a configuration that was wrong
# before anyone shipped it. This runs before the deploy, against the same
# credential, so it is answered while it is still cheap.
#
#     bash local/scripts/check-rls-connection.sh "$DATABASE_URL"
#
# Reads the profile from .koras/project.yaml, which is the authoritative record
# of what this repository is -- not the directory name and not a guess.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MANIFEST="${ROOT}/.koras/project.yaml"
URL="${1:-${DATABASE_URL:-}}"

if [ -z "$URL" ]; then
  echo "usage: $0 <database-url>   (or set DATABASE_URL)" >&2
  exit 2
fi

if [ ! -f "$MANIFEST" ]; then
  echo "No .koras/project.yaml. Cannot tell which profile this is; refusing to guess." >&2
  exit 2
fi

PROFILE="$(sed -n 's/^[[:space:]]*profile:[[:space:]]*//p' "$MANIFEST" | head -1 | tr -d '[:space:]')"

case "$PROFILE" in
  product)
    ;;
  control-plane)
    # Not an oversight. The Control Plane has no tenant model and no policies:
    # its tables carry RLS as a deny-by-default backstop and the service role is
    # *meant* to bypass it. Asserting the product's rule here would refuse a
    # deployment that is correct.
    echo "Profile is control-plane: its service role bypasses RLS by design. Nothing to check."
    exit 0
    ;;
  *)
    echo "Unrecognised profile '${PROFILE}' in .koras/project.yaml." >&2
    exit 2
    ;;
esac

echo "==> Checking whether ${PROFILE} connects as a role RLS applies to"

# -A -t: unaligned and tuples-only, so the result is the value and nothing else.
read -r user is_super bypasses <<EOF
$(psql -v ON_ERROR_STOP=1 -At -F' ' "$URL" -c \
  "select current_user, coalesce(rolsuper,false), coalesce(rolbypassrls,false)
   from pg_roles where rolname = current_user")
EOF

if [ "$is_super" = "t" ] || [ "$bypasses" = "t" ]; then
  reason="a superuser"
  [ "$is_super" = "t" ] || reason="granted BYPASSRLS"

  cat >&2 <<MSG

✗ This connection bypasses row-level security.

  Role:      ${user}
  Why:       it is ${reason}
  Effect:    every tenant policy is inert on this connection. Queries can
             return other tenants' rows, and no test of the policies will
             show it, because the policies themselves are correct.

  Fix:       point DATABASE_URL at a role that is neither a superuser nor
             holds BYPASSRLS, and grant it only the table privileges the
             service needs. Keep the privileged role for migrations.

MSG
  exit 1
fi

echo "✓ ${user} is neither a superuser nor BYPASSRLS: policies apply to it."
