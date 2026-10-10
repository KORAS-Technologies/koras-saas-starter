# ADR 0017 — Local ZITADEL credentials: a generated admin password, expiring tokens

**Status.** Accepted for Stage 4.3A, 2026-10-09: decision A14 of the Phase 4.3
specification (v2). New instances only.

**Context.** Every local instance was created with `admin` and ZITADEL's
default password, which ZITADEL also uses anywhere it is not overridden, and
the machine user's personal access token was set to expire in 2100.

**Decision.**

1. **The admin password is generated per instance**: 24 characters from
   `crypto.randomInt`, at least one upper, lower, digit and symbol, symbols
   from `!%*+-.:=?@^_~` only (none that compose, YAML or a shell reinterprets).
   The generator, `provision.py` and `preflight.sh` each refuse the default
   independently. `PasswordChangeRequired` is false: the password is already
   unique, and a forced change would break scripted sign-in tests. The
   username stays `admin`.
2. **The password reaches ZITADEL only through the init steps file**, rendered
   by `stack.mjs` as a compose secret for `start-from-init` and zeroed and
   deleted as soon as initialisation finishes or fails. It is never in a
   container's environment. It is cached owner-only at
   `~/.koras/secrets/<product>/dev/zitadel-admin-password` and escrowed to leg
   1 as `ZITADEL_ADMIN_PASSWORD`. It is not in leg 2: a lost admin password is
   recoverable with the IAM_OWNER machine token; a lost masterkey is not.
   `stack.mjs status --show-admin` is the one place it is printed.
3. **Both personal access tokens expire** -- the IAM_OWNER machine user's and
   the login client's -- at provision time plus 365 days, from one value
   `stack.mjs` computes and passes as `KORAS_ZITADEL_PAT_EXPIRES_AT`. Never
   2100, never empty: an empty expiration date means a token that never
   expires. The state file records both token ids and expiries.
4. **`up` warns 30 days ahead and refuses an expired machine token.**
5. **`stack.mjs rotate-pat [machine|login-client|all]`** creates a new token for
   the same user, writes it atomically where its consumer reads it, verifies
   it (and restarts the login container, which reads its token once), and only
   then deletes the old token by id. Any failure before the delete restores
   the old file and leaves the old token valid. An old token that cannot be
   deleted is reported, and the new one is recorded regardless.

**An expired machine token.** Rotation needs a working IAM_OWNER token, so an
expired one is recovered by a person: sign in to the console as `admin` with
the password from `stack.mjs status --show-admin` (or `stack.mjs recover`,
which restores it from Doppler), create a token for the machine user, write it
to `local/zitadel/machinekey/pat`, then run `stack.mjs rotate-pat machine` to
record it. This is never automated, and never with the default password.

**Legacy instances keep their credentials.** `legacy adopt` warns that an
adopted instance may still accept the default. Its
`--check-default-password` flag does **not** probe: any probe either creates a
session or records a failed attempt, and adopting promises never to change
the instance. A person checks by hand.
