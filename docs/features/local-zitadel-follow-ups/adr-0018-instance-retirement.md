# ADR 0018, instance retirement and versioned escrow

**Status:** ADR 0018 is Proposed. **Gate:** nothing is built until the owner
approves it. **Must land before Stage 4.3B provisions anything**, because no
escrow record exists anywhere today (2026-10-10). Changing the secret names now
costs no migration; after the first real escrow, it costs one.

## Decisions the owner must make first
1. **Authorization strength.** Is a typed confirmation on a TTY enough, or must
   a detached signature from the offline recovery key cover the plan hash?
2. **Where database backups go.** The same external destination Stage 4.3B
   awaits, or a separate one?
3. **Retention.** Keep retired records and caches indefinitely, or for a fixed
   period behind an authorized deletion step?
4. **Doppler scope.** Branch config in the product project, or a separate
   escrow project per product? T-E5's result informs this.

## Slices, each a separate PR into `develop`
| # | Slice | Contents | Exit evidence |
|---|-------|----------|---------------|
| A | Identity and naming | State schema 3 (`instanceUid`, `generation`, phase `retiring`). Generation-suffixed leg-1 names. Leg-2 artifact and sidecar names carry `g` and the UID. `doppler-check` and both manifests match the new name pattern. Schema 2 is refused with a clear message (no v2 record exists to migrate). | Unit tests, mutation-checked. A `doppler-check` case for a `_G<n>` record outside `dev_local_*` (T-R7). |
| B | Plan and verify | `retire --plan`, which writes nothing, and step 1, which verifies both escrow legs. | T-R1, T-R2 |
| C | Backup and restore rehearsal | Database dump, encrypted to the pinned key, written once to both locations. Then a throwaway compose project with no named volumes and no published ports, ZITADEL `start` with the escrowed key, and an `instanceId` match. | T-R3, plus a CI case on real containers |
| D | Authorization, mark retired, destroy, archive | TTY gate bound to the plan hash, a TOCTOU re-check, the `RETIRED` record, the volume drop through `reset.sh`'s guards, and the move to `retired/`. `reset.sh` refuses to drop an active secure instance. | T-R4, T-R5 |
| E | Replacement | `provision --fresh` allocates `g+1` and never touches a `_G<g>` record. `--database-absent` covers the reset-already-happened path. | T-R6, plus T-R8 in CI: provision, retire, provision again, sign in, recover generation 1 from leg 2 |

## Guardrails
- Tooling never deletes or overwrites an escrow record.
- No flag, environment variable or CI path bypasses step 4.
- Independent security review and QA review per slice. A slice with an open
  Critical or High finding does not merge.
- T-E4, T-E5 and T-E6 stay mandatory before any real provisioning, and ADR
  0018's slices do not replace them.
