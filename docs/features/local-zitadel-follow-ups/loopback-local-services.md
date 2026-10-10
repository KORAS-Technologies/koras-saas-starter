# Loopback-only PostgreSQL and other local services

**Problem (security review, Medium, pre-existing).** Both profiles publish
`supabase-db` as `"${KORAS_PORT_SUPABASE_DB}:5432"` on every interface, with
`postgres/postgres`. That database holds ZITADEL's event store, so anyone on
the same network can read password hashes and sessions, or write events, for
example to grant IAM_OWNER. ZITADEL and the login are already on
`127.0.0.1`. The following also listen on every interface:

| Profile | Services |
|---------|----------|
| product | redis, storage (9000/9001), otel-collector (4317/4318), proxy (80/443) |
| control-plane | the same, plus mail (1025/8025) |

## Steps
1. Prefix every published port in both templates with `127.0.0.1:`.
   `supabase-db` comes first, because it backs the identity provider.
2. **Check the connection strings, which is the real risk.** `bootstrap.sh`
   writes `postgresql://postgres:postgres@localhost:...`. On a host where
   `localhost` resolves to `::1` first, a client that tries IPv6 first is
   refused by a socket bound only to IPv4 loopback. Write `127.0.0.1` in every
   generated `DATABASE_URL`, Redis URL and S3 endpoint, or bind both
   `127.0.0.1` and `[::1]`. Test on Docker Desktop for Windows and macOS, and
   on Linux.
3. Add a generator test that every `ports:` entry in both templates starts
   with `127.0.0.1:`, unless an allowlist entry gives the reason. That catches
   the next service added.
4. In CI, run `ss -ltn` (or `docker port`) after `stack.mjs up` in
   `local-zitadel-secure`, and assert that no published port is bound to
   `0.0.0.0` or `::`.
5. Existing products adopt this through their own sync. Their volumes are not
   touched: rebinding a port needs only a container recreate, never a volume
   reset.

**Exit.** CI shows every published port on loopback, and the full product and
Control Plane browser suites stay green.

## Status, 2026-10-10: steps 1 to 3 built, step 4 left

**Step 1.** Every `ports:` entry in both profiles' `local/docker-compose.yml.hbs`
is `"127.0.0.1:${KORAS_PORT_<NAME>:-<default>}:<container>"`: `supabase-db`,
`redis`, `mail`, `storage` (product), `otel-collector` and `proxy`, beside
ZITADEL and the login, which already were. Only the address changed. No port
number, `ZITADEL_EXTERNALDOMAIN`, issuer, `loginBaseUri` or masterkey setting
changed, so an existing instance keeps its issuer. The plan left open whether
the address could be overridden. It cannot: the address is a fixed
`127.0.0.1`, with no variable to override it, because an override is a
way to put the identity provider's database back on every interface. The
shared `docker-compose.init.yml` and `docker-compose.legacy-zitadel.yml`
publish no ports.

**Step 2.** Generated `DATABASE_URL`, `REDIS_URL` and
`OTEL_EXPORTER_OTLP_ENDPOINT` (in both profiles' `bootstrap.sh` and
`.env.local.example`), plus `STORAGE_ENDPOINT` and `SMTP_HOST` in
`.env.local.example`, now name `127.0.0.1` rather than `localhost`. ZITADEL
URLs (`ZITADEL_DOMAIN`, the issuer, the login URLs) stay on `localhost`,
because the instance's external domain is `localhost` and a different host
would be a different issuer. `health.sh` still curls `localhost`. curl falls
back from `::1` to `127.0.0.1`, and ZITADEL on `localhost` was already
loopback-only before this change, so that path had already worked on
`127.0.0.1` alone. The Docker Desktop for macOS and Linux runs the plan asks
for have not been done as of 2026-10-10.

**Step 3.** `generators/create-koras-app/tests/local-loopback-ports.test.ts`
renders the default product, the three product component rows Generator
Integration builds, and the default Control Plane. It parses every rendered
compose file as YAML, in both the short and the long port syntax, and fails on
any port whose host address is missing or is not `127.0.0.1`, unless an
`ALLOWED` entry with a reason covers it. `ALLOWED` is empty. The test was
mutation-checked: removing the address from the product's `supabase-db` and
putting `0.0.0.0` on the Control Plane's `redis` failed every case naming
them. `docker compose config` on a freshly generated product and Control Plane
reports `host_ip: 127.0.0.1` on all 12 and all 10 published ports.

**Step 4 is left, as of 2026-10-10.** The `ss -ltn` assertion belongs in the
`local-zitadel-secure` job of `generator-integration.yml`, which this change
did not touch. Until it lands, the rendered files are checked and the running
sockets are not.

**Step 5.** `docoris` and `lexveria` were not modified. They adopt this by
syncing the three files per profile. A `docker compose up` after the sync
recreates the containers whose ports changed, and leaves volumes alone.
Their existing `.env.local` keeps `localhost` URLs until `bootstrap.sh`
rewrites the three keys it owns. A client that tries `::1` first and does
not fall back to IPv4 would then be refused, so those keys should be
rewritten during the sync.

The factory's own root stack, `local/docker/*.compose.yml`, still publishes
on every interface as of 2026-10-10, including ZITADEL on 8080. It is in
scope for `r046-factory-identity.md` step 2, which waits on the owner's R-046
decision, so this change does not touch it.
