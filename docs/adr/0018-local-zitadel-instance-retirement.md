# ADR 0018 — Retiring and replacing a local ZITADEL instance

**Status.** Proposed on 2026-10-10. This is a design only: it is not approved
and not implemented. It answers the open item in ADR 0015's *After a reset*
section. No code is written against it until the owner approves it, and
nothing in Stage 4.3A depends on it.

**Context.** ADR 0015 gives each machine at most one escrowed instance per
product, and no way out. Leg 1 is write-once under fixed names
(`ZITADEL_MASTERKEY`, `ZITADEL_ADMIN_PASSWORD`), so a second instance cannot
be escrowed. The state file is the only record of which instance is live,
and it has no state for "finished". After `make reset` the record and the key
are kept and `up` refuses, which is fail-closed but has no next step. The
quick way out is to delete the state file and the Doppler secret by hand.
That destroys the only evidence of which key encrypted which database, and it
is exactly what this lifecycle exists to prevent.

**The timing is favourable.** No real instance has been provisioned (Stage
4.3B is blocked on its four owner inputs as of 2026-10-10), so no escrow
record exists anywhere. The naming can change before the first one is
written, with nothing to migrate.

## Invariants

1. **Immutable identity.** `provision --fresh` assigns an `instanceUid`, a
   random UUIDv4, before it generates anything, along with a generation
   number `g`. `g` increases per product per machine and is never reused.
   Neither value changes for the life of the record. ZITADEL's own
   `instanceId` joins the record once init succeeds and never changes either.
   The tuple (product, machineId, g, instanceUid, masterkeyFingerprint,
   instanceId) identifies an instance. Every escrow record, backup and
   authorization names the whole tuple.
2. **Escrow is append-only and versioned.** Nothing in the tooling deletes or
   overwrites an escrow record. Retiring adds a record and removes none.
3. **Nothing destructive without verified recoverability.** A database is
   destroyed only when a backup of it has been restored somewhere else, has
   started with the escrowed key, and has answered with the recorded
   `instanceId`.
4. **Nothing destructive without a person.** A destructive step needs an
   authorization bound to a plan hash, given interactively, and refused in a
   non-interactive shell. No flag, environment variable or CI path bypasses
   it.
5. **Fail closed and resumable.** Every step is idempotent, records a
   checkpoint, and re-verifies what it depends on immediately before acting.
   An interrupted retirement is finished or aborted, never inferred.

## Versioned escrow records

**Leg 1 (Doppler, `dev_local_<machineId>`).** Each record is write-once and
read back after writing, as today. Only the names change:

| Name | Value | Written |
|------|-------|---------|
| `ZITADEL_MASTERKEY_G<g>` | the key | at provision |
| `ZITADEL_ADMIN_PASSWORD_G<g>` | the password | at provision |
| `ZITADEL_ESCROW_G<g>` | JSON: instanceUid, fingerprints, createdAt, zitadelVersion | at provision |
| `ZITADEL_INSTANCE_G<g>` | JSON: instanceId, issuer, initCompletedAt | once init succeeds |
| `ZITADEL_RETIRED_G<g>` | JSON: retiredAt, reason, planHash, evidence digests, authorizedBy | at retirement |

The active generation is the highest `g` that has an `ESCROW` record and no
`RETIRED` record. It has to agree with the local state's `g`. If it does not,
every command refuses and names both values. There is no mutable index to
corrupt. The `escrow` class in both manifests and in `doppler-check.sh`
becomes a name pattern,
`^ZITADEL_(MASTERKEY|ADMIN_PASSWORD|ESCROW|INSTANCE|RETIRED)_G[0-9]+$`,
allowed in `dev_local_*` only.

**Leg 2 (OpenPGP backup).** The artifact name gains the generation and the
UID: `zitadel-masterkey.<product>.<machineId>.g<g>.<instanceUid>.gpg`. The
sidecar carries the full tuple. Retirement writes a second, write-once
sidecar beside it, `….retired.json`, and edits neither the artifact nor the
first sidecar. Database backups (below) follow the same convention as
`zitadel-db.…gpg`.

**State.** State moves to schema 3, adding `instanceUid`, `generation` and a
phase `retiring`, with a `retirement` object that holds the plan hash and
step checkpoints. A retired record moves atomically to
`~/.koras/state/<product>/retired/g<g>-<instanceUid>.json` and is never
deleted by tooling. The retired key and password caches move to
`~/.koras/secrets/<product>/dev/retired/g<g>/` with the same owner-only
checks. Their eventual deletion is a separate, manual act, and this design
does not automate it.

## The workflow

`stack.mjs retire` runs in steps. Each step records a checkpoint in state and
can be resumed with `retire --resume`.

| # | Step | Destructive | Gate |
|---|------|-------------|------|
| 0 | **plan** (`retire --plan`) | no | Read-only. Prints the tuple, the escrow evidence and exactly what would be destroyed, and writes a plan file whose SHA-256 is the **plan hash**. |
| 1 | **verify escrow** | no | Leg 1: every `_G<g>` record is read back and matched to the recorded fingerprints. Leg 2: the artifact is on both volumes, its digest matches the sidecar, and it is structurally addressed to the pinned recipient. Any mismatch refuses. |
| 2 | **back up** | no | Stop ZITADEL. Dump the `zitadel` database with Postgres's own dump tool to a 0600 temporary file, encrypt it to the pinned recovery key, and write it once to both backup locations with a sidecar (digest, tuple, dump digest). |
| 3 | **rehearse the restore** | no | In a throwaway compose project with no named volumes and no published ports: an empty Postgres, then the dump restored into it, then ZITADEL `start`, never `start-from-init`, with the escrowed key. Pass only if `/admin/v1/instances/me` returns the recorded `instanceId`. Tear everything down and zero and delete the plaintext dump. Record the evidence digest. |
| 4 | **authorize** | — | Interactive TTY only. Show the plan, then require the person to type the instance's `instanceUid` and the first 12 characters of the plan hash. Refuse when stdin is not a TTY, when `CI` is set, or when the plan hash no longer matches freshly observed state. Records `authorizedBy` (OS user, git identity) and the time. |
| 5 | **mark retired** | no (append) | Write `ZITADEL_RETIRED_G<g>` and read it back. Write the leg-2 retired sidecar. From here there is no abort, only forward. |
| 6 | **destroy** | **yes** | Re-observe and compare with the plan hash (TOCTOU guard), then drop the instance's database through `reset.sh`'s existing guards. Only the database named in the plan is touched, and other volumes stay untouched. Optional: `retire --keep-database` skips this step. |
| 7 | **archive the record** | no | Move the state and caches to `retired/`. `provision --fresh` is now permitted again. |

**Replacement** is then an ordinary `provision --fresh`. It refuses unless
there is no active state and the highest generation is retired. It allocates
`g + 1` and a new `instanceUid`, and escrows under the new names before any
instance exists, exactly as ADR 0015 point 5 requires.

**Abort.** `retire --abort` is allowed before step 5 only. It restores phase
`ready`, deletes no backup taken so far (those are append-only too) and
leaves `up` working again. While a record is `retiring`, `up` refuses.

**After a reset that already happened.** The database is gone, so steps 2
and 3 cannot run. `retire --database-absent` replaces them with a
verification that the volume really is absent. It records the retirement
reason as `database destroyed before retirement`, keeps all escrow, and
still requires step 4. **Proposed alongside it:** `reset.sh` refuses to
delete the volume of an active secure instance, and names `stack.mjs retire`
instead. That is the change that stops this path recurring.

**Legacy instances** are out of scope. They have no escrow and are left by
building a new secure instance, which this design makes possible.

## Tests the implementation would owe

Every one runs against the fake estate, plus one CI case on real containers,
and each named assertion is mutation-checked.

- **T-R1:** `retire --plan` writes nothing anywhere: not to Doppler, state,
  volumes or backups.
- **T-R2:** a leg-1 or leg-2 mismatch at step 1 refuses, with nothing
  written.
- **T-R3:** a restore rehearsal against a dump from a different instance, or
  with a different key, fails at step 3, and nothing destructive follows.
- **T-R4:** step 4 refuses without a TTY, under `CI=true`, with a wrong UID,
  with a stale plan hash, or after the state changed between plan and
  authorization.
- **T-R5:** an interruption after each step resumes to the same end state,
  and no record is written twice.
- **T-R6:** `provision --fresh` after retirement writes only `_G<g+1>` names
  and never touches a `_G<g>` record. Provisioning while generation `g` is
  unretired refuses.
- **T-R7:** `doppler-check` fails on any `_G<n>` record outside `dev_local_*`.
- **T-R8 (CI, real containers):** provision, retire with the database
  destroyed, provision again, and sign in on generation 2. Recovering
  generation 1's key from leg 2 still matches its retired record.

## Questions for the owner

1. **Human authorization strength.** The design asks for a typed
   confirmation on a TTY. The stronger alternative is a detached signature
   from the offline recovery key over the plan hash, which makes the owner,
   not the developer, the authority for destroying a database. That fits a
   shared estate and is heavy for a laptop.
2. **Where database backups go.** This is the same approved external
   destination that Stage 4.3B is blocked on, or a separate one.
3. **Retention of retired records and caches.** The proposal keeps them
   indefinitely and deletes them only manually. A retention period would
   need its own authorized deletion step.
4. **Doppler access scope.** Branch configs share their environment's access
   control. Whether `dev_local_*` escrow belongs in a separate project per
   product, with per-developer access, should be settled before generation 2
   exists anywhere (manual case T-E5).

**Consequences, if approved.** A machine can hold any number of instances
over time with exactly one active. Every escrowed key stays attributable to
the instance and database it encrypted. A local database is never destroyed
without a proven, restorable copy and a person's explicit consent. The cost
is one more schema version, a pattern in place of two fixed secret names,
and a restore rehearsal that needs Docker for a few minutes.
