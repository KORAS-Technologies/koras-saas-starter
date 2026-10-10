# R-046, hardening the factory's own identity stack

**Problem.** The factory's root stack, which `make dev` starts in the starter
itself, runs ZITADEL with:
- `start-from-init`;
- `ZITADEL_MASTERKEY: ${ZITADEL_MASTERKEY:-MasterkeyNeedsToHave32Characters}`;
- the default admin password, in `local/zitadel/config.yaml` and
  `local/zitadel/init.sh`;
- port `8080` published on every interface, along with Postgres, Redis, mail,
  Loki, Tempo, Grafana and the proxy.

It started that way through `Makefile`, `local/scripts/bootstrap.sh` and
`local/scripts/health.sh`.

## First decision (owner): retire it or migrate it
- **Retire.** If nothing needs the factory to run ZITADEL itself, delete
  `local/docker/shared.compose.yml`'s identity services and `local/zitadel/`.
  Point developers at a generated project for local identity work. Smallest
  change, and the recommendation if no current workflow depends on it.
- **Migrate.** Render the factory's local stack from the same `stack.mjs` the
  templates use, so it inherits ADRs 0015 to 0017: a generated key, escrow,
  a generated password and expiring tokens.

## In either case
1. Remove every `:-` default on a secret, so a missing value is refused.
2. Bind every published port to `127.0.0.1` (see `loopback-local-services.md`).
3. Remove the placeholder value from `local/config/.env.local.example`.
4. Add a test that scans the factory's own `local/` tree for the placeholder
   and default-password fingerprints, as T-U3 and T-U16 do for templates.

**Out of scope, and not to be touched:** any existing factory database volume.
A developer who has one is told to recreate it. The tooling never does it for
them.

**Exit.** No file outside the legacy-recovery template contains either
value. The factory's `make dev` either does not start ZITADEL, or starts it
only through `stack.mjs`.
