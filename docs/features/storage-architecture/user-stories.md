# SAG-F1 — User stories

Every story is classified against what the repository actually contains on
2026-09-16, before any of it was accepted as work to do:

| Class | Meaning |
|-------|---------|
| `EXISTING` | Already built and shipped. The story documents it; it is not work |
| `EXTEND` | Something is there and this changes or completes it |
| `NEW` | Nothing like it exists |
| `NOT REQUIRED` | Proposed, examined, and deliberately not done — with the reason |

Status vocabulary is `docs/features/README.md`.

## Summary

| ID | Title | Class | Status |
|----|-------|-------|--------|
| STORAGE-001 | Storage provider abstraction | `EXTEND` | Built |
| STORAGE-002 | Storage metadata registry | `EXTEND` | Built |
| STORAGE-003 | Tenant-isolated object storage | `EXISTING` | Built |
| STORAGE-004 | Configurable storage providers | `EXISTING` | Built |
| STORAGE-005 | Storage quotas | `EXTEND` | Built |
| STORAGE-006 | Object lifecycle | `NEW` | Planned |
| STORAGE-007 | File versioning | `NOT REQUIRED` | Closed |
| STORAGE-008 | Secure signed URLs | `EXISTING` | Built |
| STORAGE-009 | Daily backup | `NEW` | Blocked |
| STORAGE-010 | Cross-provider backup | `NEW` | Blocked |
| STORAGE-011 | Backup integrity verification | `NEW` | Blocked |
| STORAGE-012 | Object restore | `NEW` | Blocked |
| STORAGE-013 | Snapshot restore | `NEW` | Blocked |
| STORAGE-014 | Storage usage metrics | `NOT REQUIRED` | Closed |
| STORAGE-015 | Storage administration contracts | `NEW` | Planned |
| STORAGE-016 | Storage configuration inheritance | `NEW` | Planned |
| STORAGE-017 | Object integrity at upload | `NEW` | Built |
| STORAGE-018 | Malware scan seam and quarantine | `NEW` | Built |
| STORAGE-019 | Bucket/index reconciliation | `NEW` | Built |
| STORAGE-020 | Multi-consumer upload hooks | `EXTEND` | Built |

Seventeen of the twenty were proposed in the original request; STORAGE-017
through STORAGE-020 are stories the request did not name and the work needed.

---

## STORAGE-001 — Storage provider abstraction

**Class** `EXTEND` · **Status** Built · **Agents** `solution-architect`, `backend-specialist`, `architecture-reviewer`

*As a* product developer, *I want* one interface to a bucket, *so that* which
provider serves a customer is a configuration decision rather than a code one.

**Why EXTEND, not NEW.** The `ObjectStore` protocol and its S3 implementation
existed from 2026-09-08 with five operations. A second abstraction over the same
five would have been the duplication this repository's review rules reject. What
was missing was listing, copying and digests.

- **Dependencies** none
- **Technical** additive with defaults, so no implementation breaks. Deliberately
  no `move`: copy-then-delete at the call site is two audit events and one
  visible failure between them
- **Security** `list` is a sweep primitive and is never reachable from a tenant route
- **Config** none
- **AC** STORAGE-001-AC01..03
- **Tests** `python-packages/koras-storage/tests/test_storage.py`
- **Docs** `docs/STORAGE_ARCHITECTURE.md`, ADR 0004

## STORAGE-002 — Storage metadata registry

**Class** `EXTEND` · **Status** Built · **Agents** `data-architect`, `database-specialist`, `migration-upgrade`

*As a* platform engineer, *I want* one row per object recording what is true
about it, *so that* governance has something to act on.

**Why EXTEND.** `public.files` existed. A separate object table would have
described the same objects twice and had to be kept in agreement.

- **Dependencies** none
- **Technical** `00018_files_governance.sql`. No `deleted_at`: this schema has
  never had one, and deletion is a state plus a date
- **Tenancy** new columns ride the existing policies; asserted, not assumed
- **AC** STORAGE-002-AC01..02
- **Tests** `supabase/tests/170_files_governance_isolation.sql`

## STORAGE-003 — Tenant-isolated object storage

**Class** `EXISTING` · **Status** Built · **Agents** `security-architect`, `security-test`

*As a* customer, *I want* my files invisible to every other customer, *so that*
using a shared product is not a disclosure.

**Why EXISTING.** Forced row-level security, a tenant-prefixed API-minted key
and a fail-closed session guard were all in place from 2026-09-08. This story
records the property and the test that proves it.

- **AC** STORAGE-003-AC01..03
- **Tests** `supabase/tests/050_files_isolation.sql`, `170_files_governance_isolation.sql`

## STORAGE-004 — Configurable storage providers

**Class** `EXISTING` · **Status** Built

*As a* customer with a data-residency requirement, *I want* my files in a bucket
I nominate, *so that* I can use the product at all.

**Why EXISTING.** The Control Plane's storage policy, read with the customer's
own token and cached for a minute, has selected the provider since 2026-09-08.
Unsupported providers are refused with 503 and a reason rather than quietly
written to the default.

- **AC** STORAGE-004-AC01..02

## STORAGE-005 — Storage quotas

**Class** `EXTEND` · **Status** Built · **Agents** `backend-specialist`, `unit-test`

*As a* platform, *I want* a plan's storage ceiling enforced, *so that* a
customer cannot consume unbounded storage on a plan that does not include it.

**Why EXTEND.** The 402 and the entitlement existed. The ceiling was advisory:
checked at ticket issue only, so two concurrent tickets could each pass and
jointly exceed it.

- **Technical** re-checked at confirmation; a breach removes the row and leaves
  the object for reconciliation, which is the existing size-mismatch idiom
- **Deviation** the plan said quarantine. Deleting the row matches the existing
  path and avoids giving `quarantined` two meanings; the cost is that a customer
  whose quota filled mid-upload loses that upload, because no retry-confirm route exists
- **AC** STORAGE-005-AC01..02

## STORAGE-006 — Object lifecycle

**Class** `NEW` · **Status** Planned · **Agents** `data-architect`, `workflow-specialist`, `privacy-compliance-reviewer`

*As a* compliance officer, *I want* objects to move through retention states and
be purged on schedule, *so that* we keep what we must and not what we must not.

- **Dependencies** STORAGE-002 (built), legal hold (AUDIT-010)
- **Technical** HOT/WARM/COLD/ARCHIVE/PURGE as Koras states. No provider in
  scope offers tiering, so COLD is metadata and ARCHIVE is a copy
- **Security** a tenant may lengthen retention and never shorten it below the
  platform floor
- **AC** STORAGE-006-AC01..03 · **Docs** `docs/RETENTION_POLICY.md`

## STORAGE-007 — File versioning

**Class** `NOT REQUIRED` · **Status** Closed 2026-09-15

Examined and declined. `version` is modelled as a column and left inert.
Implementing it adds a dimension to every listing, every quota calculation and
every key, for no requirement any product has stated. The column exists so that
adding it later is not a migration against every row.

## STORAGE-008 — Secure signed URLs

**Class** `EXISTING` · **Status** Built

*As a* customer, *I want* the bytes to move directly between my browser and the
bucket, *so that* large files are fast and the product never holds them.

**Why EXISTING.** Since 2026-09-08. `ContentType` and `ContentLength` are in the
upload signature, so a client cannot substitute a different type; downloads
force an attachment disposition.

- **AC** STORAGE-008-AC01..03

## STORAGE-009 — Daily backup

**Class** `NEW` · **Status** Blocked · **Agents** `workflow-specialist`, `devops-cicd`, `observability-sre`

*As an* operator, *I want* every object copied daily to a second location, *so
that* a provider incident is recoverable.

- **Blocked on** who creates the backup bucket. Terraform creates none, and
  `STORAGE_BUCKET` is `supplied` for that reason
- **AC** STORAGE-009-AC01..03 · **Docs** `docs/BACKUP_AND_RESTORE.md`, ADR 0006

## STORAGE-010 — Cross-provider backup

**Class** `NEW` · **Status** Blocked

*As an* operator, *I want* the copy to land with a different provider where
configured, *so that* one provider's failure is not total.

- **Blocked on** STORAGE-009, a second credential and a second bill

## STORAGE-011 — Backup integrity verification

**Class** `NEW` · **Status** Blocked

*As an* operator, *I want* a backup to count only when its digest matches, *so
that* "backed up" means something.

- **Dependencies** STORAGE-017 (built — this is why digests came first)
- **AC** STORAGE-011-AC01..02

## STORAGE-012 — Object restore

**Class** `NEW` · **Status** Blocked · **Agents** `backend-specialist`, `security-architect`, `security-reviewer`, `manual-qa`

*As a* customer administrator, *I want* a deleted or corrupted file restored,
*so that* a mistake is not permanent.

- **Technical** reuses the AI foundation's destructive-action approval rather
  than a second approval flow. Non-overwriting by default
- **Security** an unresolved plan refuses — export semantics, not upload semantics
- **AC** STORAGE-012-AC01..04

## STORAGE-013 — Snapshot restore

**Class** `NEW` · **Status** Blocked

*As an* operator, *I want* a tenant's whole scope restored from a run, *so that*
an incident has a recovery path.

- **Note** operator work with a runbook, not a button in the product

## STORAGE-014 — Storage usage metrics

**Class** `NOT REQUIRED` · **Status** Closed 2026-09-16

Not required *as metrics*. This repository has no metric API — observability is
tracing-only — so a gauge convention would be new framework rather than new
usage. Byte and object counts are answered by queries against the index and
reported through the platform contract (STORAGE-015). Reopen if a counter
convention is introduced.

## STORAGE-015 — Storage administration contracts

**Class** `NEW` · **Status** Planned · **Agents** `solution-architect`, `integration-specialist`

*As* KORAS staff, *I want* usage, quota, provider and backup state per product,
*so that* the console can show an estate view.

- **Technical** counts only on the private contract, machine identity only.
  Defines the contract; **does not modify the Control Plane**
- **Docs** `docs/features/storage-architecture/integration-contracts.md`

## STORAGE-016 — Storage configuration inheritance

**Class** `NEW` · **Status** Planned

*As a* product owner, *I want* platform, product and tenant settings to layer
predictably, *so that* a tenant can tighten and never loosen.

- **AC** STORAGE-016-AC01..02 · **Docs** `configuration.md`

## STORAGE-017 — Object integrity at upload

**Class** `NEW` · **Status** Built · **Agents** `backend-specialist`, `frontend-specialist`, `e2e-test`

*As an* operator, *I want* a digest recorded for every object, *so that* a copy
can later be compared with its original.

**Not in the original story list, and the prerequisite for three that were.**

- **Technical** the browser hashes before the PUT; the API records the claim and
  marks it verified only where the provider's digest agrees. Two columns
- **Honesty constraint** a client-asserted digest is evidence, not proof, and
  the API response distinguishes them
- **AC** STORAGE-017-AC01..04

## STORAGE-018 — Malware scan seam and quarantine

**Class** `NEW` · **Status** Built · **Agents** `backend-specialist`, `security-reviewer`, `security-test`

*As a* security administrator, *I want* infected files withheld, *so that* the
product is not a distribution channel.

- **Scope** the seam and the enforcement. **No scanner is integrated**
- **Technical** only `infected` is withheld; refusing `pending` would break every
  product without a scanner
- **AC** STORAGE-018-AC01..03

## STORAGE-019 — Bucket/index reconciliation

**Class** `NEW` · **Status** Built · **Agents** `workflow-specialist`, `observability-sre`

*As an* operator, *I want* to know where the bucket and the index disagree, *so
that* leaks and lost rows are findable.

- **Technical** reports and deletes nothing. A partial listing reports no
  orphans. Reconciles the platform bucket only; a row it cannot see is
  *unverifiable*, not *missing*
- **AC** STORAGE-019-AC01..04

## STORAGE-020 — Multi-consumer upload hooks

**Class** `EXTEND` · **Status** Built

*As a* product developer, *I want* to register an interest in uploads, *so that*
a scanner and an indexer can both run.

**Why EXTEND.** A single-slot mutable record existed; the second registrant
would have replaced the first silently.

- **AC** STORAGE-020-AC01..03
