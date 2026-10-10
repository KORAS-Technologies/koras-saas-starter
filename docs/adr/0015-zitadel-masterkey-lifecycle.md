# ADR 0015 — The local ZITADEL masterkey: generated, cached, escrowed twice, never rotated

**Status.** Accepted for Stage 4.3A, 2026-10-09: decisions A2 (as amended), A3
and A4 of the Phase 4.3 specification (v2), approved by the owner. Built in
`koras-saas-starter` only; no product, volume, instance or Doppler config was
touched. Adoption by existing products is Stage 4.5.

**Context.** Every generated project started ZITADEL with
`start-from-init --masterkeyFromEnv` and the key ZITADEL's own documentation
prints, `MasterkeyNeedsToHave32Characters`. The masterkey encrypts an
instance's signing keys and secrets at rest and cannot be changed once the
instance exists, so every local instance in the estate was readable by anyone
holding its database, and could not be fixed in place. The same file
re-initialised on every start, held the default admin password, and published
ZITADEL on every interface.

**Decision.**

1. **One door.** `local/scripts/stack.mjs` (from
   `profiles/_shared/template/local/scripts/stack.mjs.hbs`) is the only thing
   that starts ZITADEL. `make dev`, `pnpm stack:up` and bootstrap call it. The
   base compose file takes the key as a compose *secret file* named by
   `${KORAS_ZITADEL_MASTERKEY_FILE:?…}`, and the container users the same way,
   so a bare `docker compose up` fails before anything starts. Scripts that
   only exec, stop or tear down source `local/scripts/compose-env.sh`, which
   points the key at an empty file ZITADEL refuses.
2. **Generated on the machine.** 32 characters of `[A-Za-z0-9]` from
   `crypto.randomInt`, written with `O_CREAT|O_EXCL` and no trailing newline
   (v4.17.1 reads `--masterkeyFile` byte for byte) to
   `~/.koras/secrets/<product>/dev/zitadel-masterkey`: mode 0600 in a 0700
   directory, or on Windows an ACL of exactly one principal. Read back only
   after the permissions, the size (exactly 32 bytes), the placeholder and the
   recorded fingerprint are checked. A missing key is a refusal; nothing falls
   back.
3. **Escrowed twice, before the instance exists.** Leg 1: write-once to a
   per-machine Doppler branch config `dev_local_<machineId>`, with the
   developer's own login, read back and compared; an existing different value
   is never overwritten. Leg 2: an OpenPGP public-key backup to the owner's
   recovery key, pinned by full fingerprint in
   `~/.koras/recovery-recipient.json`, written to `~/.koras/escrow-backup/` and
   copied to `KORAS_ESCROW_BACKUP_DIR` on a different volume, verified
   structurally (one session-key packet, to the pinned key; the ciphertext
   digest in its sidecar). Escrow is `escrowed` only when both legs are done.
   Symmetric encryption was rejected: its passphrase would live beside the
   backup.
4. **`escrow`, a fifth settings class.** `ZITADEL_MASTERKEY` and
   `ZITADEL_ADMIN_PASSWORD` are `escrow` in both manifests: allowed in a
   `dev_local_*` config and nowhere else. `doppler-check.sh` fails the `dev`,
   `stg` and `prd` roots and every other branch holding one, so the DEV deploy
   contract is unchanged. `doppler-bootstrap.sh` and `config-typecheck.sh`
   skip the class.
5. **Fail closed (A3).** `provision --fresh` refuses before generating anything
   when either leg cannot be written, unless `--offline` is given; an offline
   instance is recorded `unescrowed`, `provision.py` refuses it, and `up`
   refuses it until `stack.mjs escrow` completes both legs.
6. **A state file outside the repository.**
   `~/.koras/state/<product>/zitadel.json`, schema 2, written atomically,
   records the mode, issuer and login ports, instance id, key fingerprint,
   escrow evidence and token expiries. `up` refuses an unrecorded database, a
   moved port, a different running instance id, or a mismatched key, and
   stops ZITADEL on a post-start mismatch. It never initialises.
7. **Legacy recovery (A4).** An instance created on the placeholder is
   recorded with `legacy adopt --instance-id <id> --issuer <url>` and started
   only through `local/docker-compose.legacy-zitadel.yml` -- the one file in a
   generated project that contains the placeholder -- and only when the shell
   also sets `KORAS_ZITADEL_MODE=legacy-recovery`. `start`, never
   `start-from-init`; loopback only; pinned to the recorded instance id; no
   login container; no rotation command. Leaving legacy means a new secure
   instance.
8. **Never root.** On Linux both containers run as the host user, so the
   owner-only key file and the token directories need no widening; elsewhere
   each image's own non-root user. The official compose's `user: "0"` is not
   used. A Linux shell running as root is refused.

**Two departures from the specification's text, and why.**

- The state file is written *immediately after* the secrets are generated,
  not after escrow (§3.6 step 4). In the specified order an interruption
  between generating and recording leaves a cached key nothing mentions; in
  this one every interruption leaves a record, and `provision --resume`
  finishes from it -- re-running `start-from-init` with the same key, which is
  ZITADEL's own way of completing a half-initialised setup.
- The placeholder and the default password are refused by **fingerprint**
  (`sha256`) in `masterkey.mjs`, `credentials.mjs`, `provision.py` and
  `preflight.sh`, so that neither value appears in any rendered file but the
  legacy override (T-U3, T-U16).

**After a reset.** `make reset` deletes the database volume and leaves the
key cache, the state file and both escrow legs in place, as the rollback
section of the specification requires. `up` then refuses
(`INSTANCE_DB_MISSING`) rather than initialise over the record, and
`provision --fresh` refuses while the state exists. Provisioning a second
instance on the same machine collides with leg 1's write-once rule, because
the Doppler secret name is fixed. Recorded on 2026-10-09 as open: the
specification defines no retirement procedure for an escrowed key, and
choosing one -- per-instance secret names, or archiving the old record -- is
the owner's decision, not this stage's. ADR 0018 proposes a retirement and
replacement workflow (2026-10-10, design only, awaiting approval).

**Consequences.** A new product's local identity provider is no longer
readable by whoever holds its database, cannot be re-initialised by accident,
and survives losing the machine. Starting the stack needs Node, as it already
did for the applications. Existing products are untouched until 4.5. A8 (a
port registry) replaces `resolvePorts()` in `stack.mjs` and nothing else;
A10 (the `koras local` CLI) imports the modules' exports and replaces each
script's `main()`.
