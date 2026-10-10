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
