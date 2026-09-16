# Storage & Audit Governance — status

Planner tracking for both features. Status vocabulary is
`docs/features/README.md`. Last reviewed 2026-09-16.

## SAG-F1 — Storage Architecture & Data Protection

| Story | Title | Class | Status |
|-------|-------|-------|--------|
| STORAGE-001 | Storage provider abstraction | EXTEND | Built |
| STORAGE-002 | Storage metadata registry | EXTEND | Built |
| STORAGE-003 | Tenant-isolated object storage | EXISTING | Built |
| STORAGE-004 | Configurable storage providers | EXISTING | Built |
| STORAGE-005 | Storage quotas | EXTEND | Built |
| STORAGE-006 | Object lifecycle | NEW | Built — purge and retention; ARCHIVE still blocked |
| STORAGE-007 | File versioning | NOT REQUIRED | Closed |
| STORAGE-008 | Secure signed URLs | EXISTING | Built |
| STORAGE-009 | Daily backup | NEW | **Built 2026-09-16** |
| STORAGE-010 | Cross-provider backup | NEW | **Built 2026-09-16** — the settings already promised it |
| STORAGE-011 | Backup integrity verification | NEW | **Built 2026-09-16** |
| STORAGE-012 | Object restore | NEW | Blocked — ADR 0006 question 3 |
| STORAGE-013 | Snapshot restore | NEW | Blocked — STORAGE-012 |
| STORAGE-014 | Storage usage metrics | NOT REQUIRED | Closed — no metric API |
| STORAGE-015 | Storage administration contracts | NEW | Built — `GET /governance` |
| STORAGE-016 | Storage configuration inheritance | NEW | Built — tenant may lengthen only |
| STORAGE-017 | Object integrity at upload | NEW | Built |
| STORAGE-018 | Malware scan seam and quarantine | NEW | Built |
| STORAGE-019 | Bucket/index reconciliation | NEW | Built |
| STORAGE-020 | Multi-consumer upload hooks | EXTEND | Built |

**14 built · 1 planned · 3 blocked · 2 closed**

## SAG-F2 — Audit Storage, Retention & Archival

| Story | Title | Class | Status |
|-------|-------|-------|--------|
| AUDIT-001 | Canonical audit event model | EXISTING | Built |
| AUDIT-002 | Audit event publisher | EXISTING | Built |
| AUDIT-003 | Audit ingestion | NOT REQUIRED | Closed — synchronous write is better here |
| AUDIT-004 | Tenant-isolated audit storage | EXTEND | Built |
| AUDIT-005 | Audit search | NEW | Built |
| AUDIT-006 | Audit filtering | NEW | Built |
| AUDIT-007 | Audit retention policies | EXTEND | Built |
| AUDIT-008 | Audit archival | NEW | Planned |
| AUDIT-009 | Audit purge | EXTEND | Built — hold-aware since 2026-09-16 |
| AUDIT-010 | Legal / compliance hold | NEW | Built |
| AUDIT-011 | Audit export | NEW | Built |
| AUDIT-012 | Audit export jobs | EXTEND | Built |
| AUDIT-013 | Customer audit viewer contract | NEW | Built — the page and its e2e suite |
| AUDIT-014 | Control Plane audit contract | EXISTING | Built |
| AUDIT-015 | Audit RBAC | EXTEND | Built — `audit.view`, and the security class needs a manager |
| AUDIT-016 | Audit integrity | EXISTING | Built |
| AUDIT-017 | Audit observability | NOT REQUIRED | Closed — no metric API |
| AUDIT-018 | Audit configuration inheritance | NEW | Built |
| AUDIT-019 | Audit action registry | NEW | Built |
| AUDIT-020 | Audit event classification | NEW | Built |
| AUDIT-021 | Storage operations recorded | NEW | Built |

**18 built · 0 planned · 0 blocked · 3 closed**

## Blockers, and who owns them

| Blocker | Blocks | Owner |
|---------|--------|-------|
| Nothing provisions a bucket | AUDIT-008 | Answered 2026-09-16 for backup: a manual step, as `STORAGE_BUCKET` already is. The archive destination is still nobody's |
| No entitlement codes in the platform catalogue | STORAGE-012; audit export is gated by permission alone | Control Plane work, governed by F3/F2b |
| ~~Everything shipped into the foundation~~ | ~~every story~~ | Closed 2026-09-16: `audit_governance` and `storage_governance` are declared, both on by default |
| No metric API in the repository | STORAGE-014, AUDIT-017 | Open framework decision |
| The two capabilities are undeclared | Every gated surface | Generator work; both off by default when declared |

## Definition of Done — where both features stand

| Condition | SAG-F1 | SAG-F2 |
|-----------|--------|--------|
| Stories done or closed with a reason | partial | partial |
| Automated tests pass, evidenced | yes, for built stories | yes, for built stories |
| Tenant isolation proven as the restricted role | yes — fourteen suites, mutation-tested | yes — the same |
| Independent code review | **no** | **no** |
| Security review | **no** | **no** |
| Privacy and compliance review | **no** | **no** |
| Manual QA executed with evidence | **no** — 14 cases, all blank | **no** — 11 cases, all blank |
| Documentation updated | yes | yes |
| `final-acceptance` READY | **no** | **no** |

**Neither feature is Done, and neither is close to it.** The gap is not code; it
is that nothing independent has reviewed the code, and nobody has run the
software against a real environment and written down what happened.

## Recommended order

**SAG-F2 has no unbuilt stories left.** Everything below is either review,
a decision, or work that belongs to SAG-F1.

1. **Independent security review** of what has shipped. Eight commits of
   governance code — migrations, policies, two destructive sweeps, an
   authorization asymmetry, an export path that moves records out of the
   product — have had no independent eyes, and the gap widens with each
   feature rather than closing.
2. **A manual pass.** Twenty-five cases, every verdict still blank, and the
   export and hold flows have never been exercised by a person.
3. **Answer ADR 0006 question 1.** It blocks five storage stories and is half
   a day of somebody's decision rather than of engineering.
4. **Declare the two capabilities.** Everything has landed in the foundation,
   so every product carries holds, audit search, export and two sweeps whether
   it wants them or not.
5. **STORAGE-015**, the platform contract, so the console can show governance
   state across the estate.
