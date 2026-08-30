#!/usr/bin/env bash
# Creates the database role the services connect as. Once per environment.
#
# Row-level security does not apply to a superuser, and does not apply to a role
# holding BYPASSRLS. `force row level security` binds the table *owner* and
# neither of those. A managed Postgres issues a privileged role as its default
# credential, so a DATABASE_URL taken from a dashboard produces a service with
# correct policies, `force` set everywhere, a green policy suite, and no tenant
# isolation at all. See R-032.
#
# So the privileged credential migrates, and a restricted one serves:
#
#     DATABASE_ADMIN_URL   privileged. Runs migrations. Used by CI only.
#     DATABASE_URL           this role. Used by every service.
#
# The names are that way round deliberately. A secret called
# DATABASE_ADMIN_URL is visibly privileged; a plain DATABASE_URL that happens
# to be a superuser is the trap. The default name gets the least privilege.
#
#     bash local/scripts/create-app-role.sh "$PRIVILEGED_DATABASE_URL"
#
# Prints the connection URL to put in Doppler as DATABASE_URL. It is printed
# once and stored nowhere: this script writes no file and keeps no copy.
#
# Idempotent. Re-running rotates the secret and re-applies the grants, which is
# also how to recover from a lost one.
set -euo pipefail

URL="${1:-${DATABASE_ADMIN_URL:-}}"
ROLE="${KORAS_APP_ROLE:-koras_app}"

if [ -z "$URL" ]; then
  echo "usage: $0 <privileged-database-url>   (or set DATABASE_ADMIN_URL)" >&2
  exit 2
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is not installed. It is needed to create the role." >&2
  exit 2
fi

# Generated here rather than asked for, so nobody is tempted to reuse one they
# already have. Reserved URL characters are stripped rather than escaped: the
# value goes into a connection string, and one that needs percent-encoding is
# one somebody will paste wrong.
if command -v openssl >/dev/null 2>&1; then
  GENERATED="$(openssl rand -base64 36 | tr -d '/+=' | cut -c1-32)"
else
  GENERATED="$(head -c 48 /dev/urandom | base64 | tr -d '/+=' | cut -c1-32)"
fi

DB="$(psql -At "$URL" -c 'select current_database()')"
echo "==> Creating ${ROLE} on ${DB}"

# One transaction. A role created without its grants would pass the connection
# check and fail every query, which is a worse state than not having it.
if ! psql -v ON_ERROR_STOP=1 -q "$URL" <<SQL
begin;

do \$block\$
begin
  if not exists (select 1 from pg_roles where rolname = '${ROLE}') then
    -- nosuperuser and nobypassrls are the entire point of this role. Stated
    -- rather than left to the default, so a later edit has to read past them.
    create role ${ROLE} login nosuperuser nobypassrls nocreatedb nocreaterole;
  end if;
end
\$block\$;

alter role ${ROLE} with password '${GENERATED}';

grant connect on database ${DB} to ${ROLE};
grant usage on schema public to ${ROLE};

-- The tables that exist now, and the ones a later migration adds. Without the
-- default privileges every new table is invisible to the service until somebody
-- remembers to grant it, which presents as a missing row rather than as a
-- permission error.
grant select, insert, update, delete on all tables in schema public to ${ROLE};
grant usage, select on all sequences in schema public to ${ROLE};
alter default privileges in schema public
  grant select, insert, update, delete on tables to ${ROLE};
alter default privileges in schema public
  grant usage, select on sequences to ${ROLE};

commit;
SQL
then
  cat >&2 <<'MSG'

x Could not create the role.

  If this is a managed Postgres, the credential it issues may not be permitted
  to create roles at all. Supabase restricts what its `postgres` role may do,
  and this script has been verified against stock Postgres rather than against
  every managed provider.

  If role creation is refused: create the role through the provider's own
  console or API, then re-run this script to apply the grants -- it finds an
  existing role rather than trying to create one.

MSG
  exit 1
fi

# Read back rather than assumed. The entire value of this role is a property of
# it, and asserting that property costs one query.
read -r is_super bypasses <<EOF
$(psql -At -F' ' "$URL" -c "select rolsuper, rolbypassrls from pg_roles where rolname = '${ROLE}'")
EOF

if [ "$is_super" != "f" ] || [ "$bypasses" != "f" ]; then
  echo "x ${ROLE} exists but is superuser=${is_super} bypassrls=${bypasses}." >&2
  echo "  Row-level security would not apply to it. Refusing to report success." >&2
  exit 1
fi

# Rebuilt from the privileged URL so host, port and database match it exactly
# rather than being retyped.
proto="${URL%%://*}"
rest="${URL#*://}"
hostpart="${rest#*@}"

# The username is not only the role, and replacing the whole of it was a bug.
#
# A managed pooler routes to a tenant by the suffix on the username: Supabase's
# Supavisor takes `postgres.abcdefghijklmnop` to mean the role `postgres` on
# project `abcdefghijklmnop`. Swapping in the bare role dropped the suffix with
# it, and the pooler then had nothing to route by:
#
#     FATAL: (ENOIDENTIFIER) no tenant identifier provided
#
# which arrives at connect time, so a product provisioned correctly and
# deployed correctly failed at startup with an error naming neither the URL nor
# this script. Observed on koras-e2e-shop, 2026-08-30, and corrected by hand --
# after which re-running this put the broken value straight back.
#
# A direct host has no suffix and needs none. `${userpart#*.}` returns the whole
# string unchanged when there is no dot, which is what distinguishes the two.
userpart="${rest%%:*}"
suffix="${userpart#*.}"
if [ "$suffix" = "$userpart" ]; then
  qualified="${ROLE}"
else
  qualified="${ROLE}.${suffix}"
fi

cat <<MSG

/ ${ROLE} created, and row-level security applies to it.

  Put this in Doppler as DATABASE_URL for this environment:

    ${proto}://${qualified}:${GENERATED}@${hostpart}

  Keep the privileged URL you passed here as DATABASE_ADMIN_URL. That is what
  runs migrations, and it is the only place it is still needed.

  The generated value is shown once and stored nowhere. Re-run this script to
  rotate it; the grants are re-applied and nothing else changes.

MSG
