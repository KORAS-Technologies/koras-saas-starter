# SAG-F2 — User stories

Classified against what the repository actually contains on 2026-09-16.
Vocabulary is `docs/features/README.md`.

## Summary

| ID | Title | Class | Status |
|----|-------|-------|--------|
| AUDIT-001 | Canonical audit event model | `EXISTING` | Built |
| AUDIT-002 | Audit event publisher | `EXISTING` | Built |
| AUDIT-003 | Audit ingestion | `NOT REQUIRED` | Closed |
| AUDIT-004 | Tenant-isolated audit storage | `EXTEND` | Built |
| AUDIT-005 | Audit search | `NEW` | Planned |
| AUDIT-006 | Audit filtering | `NEW` | Planned |
| AUDIT-007 | Audit retention policies | `EXTEND` | Built |
| AUDIT-008 | Audit archival | `NEW` | Planned |
| AUDIT-009 | Audit purge | `EXTEND` | Built |
| AUDIT-010 | Legal / compliance hold | `NEW` | Planned |
| AUDIT-011 | Audit export | `NEW` | Planned |
| AUDIT-012 | Audit export jobs | `EXTEND` | Planned |
| AUDIT-013 | Customer audit viewer contract | `NEW` | Planned |
| AUDIT-014 | Control Plane audit contract | `EXISTING` | Built |
| AUDIT-015 | Audit RBAC | `EXTEND` | Planned |
| AUDIT-016 | Audit integrity | `EXISTING` | Built |
| AUDIT-017 | Audit observability | `NOT REQUIRED` | Closed |
| AUDIT-018 | Audit configuration inheritance | `NEW` | Planned |
| AUDIT-019 | Audit action registry | `NEW` | Built |
| AUDIT-020 | Audit event classification | `NEW` | Built |
| AUDIT-021 | Storage operations recorded | `NEW` | Built |

AUDIT-019 to AUDIT-021 were not in the original list and are the work that was
actually done.

---

## AUDIT-001 — Canonical audit event model

**Class** `EXISTING` · **Status** Built

*As a* developer, *I want* one event shape, *so that* every module records the
same way and a reader learns it once.

**Why EXISTING.** `koras-audit` has carried the envelope since the AI foundation
and both profiles share it. `audit-event-model.md` documents it.

- **AC** AUDIT-001-AC01..03

## AUDIT-002 — Audit event publisher

**Class** `EXISTING` · **Status** Built

*As a* route, *I want* to emit events and have them written once the answer is
decided, *so that* a refusal is recorded as firmly as a success.

**Why EXISTING.** `SqlAuditSink` buffers and flushes; it refuses a cross-tenant
event and rebinds the tenant after its commit.

- **AC** AUDIT-002-AC01..03

## AUDIT-003 — Audit ingestion

**Class** `NOT REQUIRED` · **Status** Closed 2026-09-16

The original design sketched a publisher, an ingestion stage and a store. **A
separate ingestion tier is not justified here.** Events are written inside the
request's own transaction on the tenant's session, which gives ordering,
tenancy and atomicity for free; a queue between the route and the table would
add a delivery guarantee to reason about and a window in which a recorded
refusal has not been recorded.

Reopen if volume outgrows synchronous writes — the symptom would be flush
latency on hot routes, and nothing shows it as of 2026-09-16.

## AUDIT-004 — Tenant-isolated audit storage

**Class** `EXTEND` · **Status** Built · **Agents** `data-architect`, `database-specialist`

*As a* customer, *I want* my audit history invisible to other tenants and
uneditable by anyone, *so that* it is worth something as evidence.

**Why EXTEND.** The table and its policies existed. What changed is ownership:
it left the `reporting` capability and became foundation, so a product without
reporting still records.

- **AC** AUDIT-004-AC01..04
- **Tests** `supabase/tests/110_audit_isolation.sql`

## AUDIT-005 — Audit search

**Class** `NEW` · **Status** Planned · **Agents** `backend-specialist`, `frontend-specialist`, `ux-ui-designer`, `accessibility-qa`

*As a* tenant administrator, *I want* to search my own audit history, *so that*
I can answer a question without asking KORAS.

- **Technical** served by the `(tenant_id, action, created_at desc)` index;
  paged; 404 rather than 403 for a row the caller may not have
- **Security** security-classified rows need owner or administrator
- **AC** AUDIT-005-AC01..04

## AUDIT-006 — Audit filtering

**Class** `NEW` · **Status** Planned

*As a* tenant administrator, *I want* to narrow by actor, action, outcome, date
and class, *so that* a search returns an answer rather than a haystack.

- **Technical** typed, declared filters bound as parameters. **No free-text
  filter** — the rule `koras-reporting` already enforces
- **AC** AUDIT-006-AC01..02

## AUDIT-007 — Audit retention policies

**Class** `EXTEND` · **Status** Built

*As a* compliance officer, *I want* each kind of record kept for its own time,
*so that* noise expires and evidence does not.

**Why EXTEND.** A sweep existed with one number. Now four classes, three
settings, one transaction.

- **AC** AUDIT-007-AC01..04 · **Tests** `tests/unit/test_audit_retention.py`

## AUDIT-008 — Audit archival

**Class** `NEW` · **Status** Planned

*As a* compliance officer, *I want* rows moved to cheaper storage before they
are purged, *so that* long retention does not mean a growing hot table.

- **Dependencies** AUDIT-007 (built), and a destination that does not exist
- **Technical** the same open question as storage archival: nothing creates the
  bucket. `archival.md`
- **AC** AUDIT-008-AC01..02

## AUDIT-009 — Audit purge

**Class** `EXTEND` · **Status** Built

*As a* platform, *I want* rows past their retention removed, *so that* we do not
hold what we said we would not.

**Why EXTEND.** The delete exists and runs nightly. What it does **not** do is
check a hold, because no hold exists — which is why AUDIT-010 blocks calling
this finished.

- **AC** AUDIT-009-AC01..03

## AUDIT-010 — Legal / compliance hold

**Class** `NEW` · **Status** Planned · **Agents** `data-architect`, `privacy-compliance-reviewer`, `security-test`

*As* legal counsel, *I want* records preserved past their expiry while a matter
is open, *so that* retention is not an obstruction.

- **Technical** the sweep's `WHERE` must exclude held rows, and a qualified
  delete needs a select policy as well as a delete policy
- **Security** placing and lifting both audited; lifting needs owner or
  administrator, because it is what makes a purge possible again
- **AC** AUDIT-010-AC01..04 · **Docs** `legal-hold.md`

## AUDIT-011 — Audit export

**Class** `NEW` · **Status** Planned

*As a* compliance officer, *I want* an authorized export of a scope, *so that* I
can hand evidence to someone outside the product.

- **Technical** reuse the reporting export pipeline — 202, `pending` → `ready`
  or `failed`, signed artifact, retirement sweep. **Do not build a second one**
- **Security** refuse while the plan is unresolved; exporting is itself audited
- **AC** AUDIT-011-AC01..04

## AUDIT-012 — Audit export jobs

**Class** `EXTEND` · **Status** Planned

*As a* compliance officer, *I want* a large export to run in the background,
*so that* a request does not time out.

**Why EXTEND.** `report_exports` and its background writer already do this. The
work is reuse, not construction.

## AUDIT-013 — Customer audit viewer contract

**Class** `NEW` · **Status** Planned

*As a* tenant administrator, *I want* a page showing my audit history, *so that*
the capability is reachable without an API client.

- **Docs** `integration-contracts.md`

## AUDIT-014 — Control Plane audit contract

**Class** `EXISTING` · **Status** Built

*As* KORAS staff, *I want* activity counts per product, *so that* the console
can show adoption without reading anyone's records.

**Why EXISTING.** `GET /internal/platform/v1/activity` has answered counts and
distinct actors per tenant, day, action and outcome since the reporting
framework. Counts only, machine identity only, 92 days.

- **AC** AUDIT-014-AC01..02

## AUDIT-015 — Audit RBAC

**Class** `EXTEND` · **Status** Planned

*As a* security administrator, *I want* security-classified rows restricted,
*so that* an ordinary member cannot read every refusal.

**Why EXTEND.** Permissions and roles exist; no audit-specific permission does.
Needs `audit.view` in both mirrored catalogues in one commit.

- **AC** AUDIT-015-AC01..02

## AUDIT-016 — Audit integrity

**Class** `EXISTING` · **Status** Built

*As an* auditor, *I want* records that cannot be altered, *so that* they are
evidence rather than notes.

**Why EXISTING.** There is **no update policy on the table for anyone**, and no
tenant delete policy. Deletion is the sweep's alone, on the provisioning
context.

**What this does not claim:** there is no cryptographic chaining, no signature
and no external write-once store. Integrity here is "the database refuses the
write", which is strong against the application and not against a DBA with the
owner role. No requirement has asked for more as of 2026-09-16.

- **AC** AUDIT-016-AC01..02

## AUDIT-017 — Audit observability

**Class** `NOT REQUIRED` · **Status** Closed 2026-09-16

Not required *as metrics*, for the same reason as STORAGE-014: this repository
has no metric API, and a counter convention would be new framework. The sweep
logs its counts per class and the platform aggregate answers volume. Reopen with
the metric decision.

## AUDIT-018 — Audit configuration inheritance

**Class** `NEW` · **Status** Planned

*As a* product owner, *I want* platform, product and tenant retention to layer,
*so that* a tenant can keep records longer and never shorter.

- **AC** AUDIT-018-AC01..02

## AUDIT-019 — Audit action registry

**Class** `NEW` · **Status** Built · **Agents** `solution-architect`, `backend-specialist`

*As a* developer, *I want* the actions a build can record to be declared, *so
that* classification is a property of the action rather than of whoever typed
the string.

- **Technical** dotted lower-case, summary required, duplicates refused at
  import, ordered iteration, undeclared actions refused at recording
- **AC** AUDIT-019-AC01..05 · **Tests** `tests/unit/test_audit_actions.py`

## AUDIT-020 — Audit event classification

**Class** `NEW` · **Status** Built

*As a* compliance officer, *I want* each row to say what kind of record it is,
*so that* one sweep can keep them for different lengths of time.

- **Technical** `00019_audit_classification.sql`; written from the registry,
  never from a caller; indexed with the age because the sweep deletes by both
- **AC** AUDIT-020-AC01..03

## AUDIT-021 — Storage operations recorded

**Class** `NEW` · **Status** Built

*As a* customer administrator, *I want* every file operation recorded, *so that*
"who downloaded that" has an answer.

- **Technical** eight actions; details carry `file_id` and never `storage_key`,
  which the envelope refuses by name
- **AC** AUDIT-021-AC01..03 · **Tests** `tests/unit/test_storage_audit.py`
