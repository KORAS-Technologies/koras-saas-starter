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

**The password fingerprint, and CodeQL `js/insufficient-password-hash`.**
Decided 2026-10-10. CodeQL raises two high alerts on PR #66. Alert 12 is on
`fingerprint()` in `local/zitadel/state.mjs`. Alert 11 is on the test helper
that hashes ZITADEL's public default in `local-zitadel-secure.test.ts`. The
unsalted `sha256` is kept. The disposition covers these two alerts and these
two call paths only. No rule is excluded and no query is suppressed.

Why it is not a password hash:

- **It authenticates nothing.** ZITADEL verifies the admin password with its
  own hash, and the plaintext reaches ZITADEL only through the steps file
  (point 2). The fingerprint is compared in exactly four places. `stack.mjs`
  compares it on `provision --resume` and `recover`, to check that the cached
  or escrowed copy is the one this instance was created with.
  `credentials.mjs` and `preflight.sh` compare it with the fingerprint of
  ZITADEL's public default, to refuse that default. `provision.py` refuses a
  state that records the default's fingerprint.
- **The input is not guessable.** `crypto.randomInt` is a CSPRNG and samples
  without modulo bias. It draws 24 characters from a 75-symbol alphabet with
  one of each class guaranteed, which is at least 141 bits; 149.5 bits is the
  ceiling. A slow hash protects low-entropy input by making each guess
  expensive. At 2^141, even the fastest hash leaves the search out of reach,
  so scrypt would add cost and dependencies and no protection.
- **It sits where the plaintext already sits.** The fingerprint is in the
  0600 state file beside the 0600 plaintext cache, and leg 1 holds the
  plaintext itself. `status` prints the masterkey's fingerprint and never the
  password's.
- **Alert 11 hashes a public constant**, to check the denylist value. It is
  test code, and the value is ZITADEL's documented default.

**What keeps this true.** Two tests in `local-zitadel-secure.test.ts` fail if
the generator's length or alphabet takes the bound below 128 bits, or if
anything the stack logs carries the password fingerprint. Both were
mutation-checked on 2026-10-10. A comment on `fingerprint()` limits it to
generated values and public constants. If any of these conditions stops
holding, the alerts are real and this disposition is withdrawn. That would
happen if `fingerprint()` is used on a password a person chose, if the
fingerprint leaves the owner-only state file, or if the generator is
weakened. The remedy then is a slow, salted KDF.

**Dismissal.** Each alert is dismissed individually, by a person, citing this
section: alert 12 as "false positive" and alert 11 as "used in tests".

**Legacy instances keep their credentials.** `legacy adopt` warns that an
adopted instance may still accept the default. Its
`--check-default-password` flag does **not** probe: any probe either creates a
session or records a failed attempt, and adopting promises never to change
the instance. A person checks by hand.
