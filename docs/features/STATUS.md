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
| STORAGE-006 | Object lifecycle | NEW | Planned |
| STORAGE-007 | File versioning | NOT REQUIRED | Closed |
| STORAGE-008 | Secure signed URLs | EXISTING | Built |
| STORAGE-009 | Daily backup | NEW | Blocked — no bucket |
| STORAGE-010 | Cross-provider backup | NEW | Blocked — STORAGE-009 |
| STORAGE-011 | Backup integrity verification | NEW | Blocked — STORAGE-009 |
| STORAGE-012 | Object restore | NEW | Blocked — STORAGE-011 |
| STORAGE-013 | Snapshot restore | NEW | Blocked — STORAGE-012 |
| STORAGE-014 | Storage usage metrics | NOT REQUIRED | Closed — no metric API |
| STORAGE-015 | Storage administration contracts | NEW | Planned |
| STORAGE-016 | Storage configuration inheritance | NEW | Planned |
| STORAGE-017 | Object integrity at upload | NEW | Built |
| STORAGE-018 | Malware scan seam and quarantine | NEW | Built |
| STORAGE-019 | Bucket/index reconciliation | NEW | Built |
| STORAGE-020 | Multi-consumer upload hooks | EXTEND | Built |

**11 built · 4 planned · 3 blocked · 2 closed**

## SAG-F2 — Audit Storage, Retention & Archival

| Story | Title | Class | Status |
|-------|-------|-------|--------|
| AUDIT-001 | Canonical audit event model | EXISTING | Built |
| AUDIT-002 | Audit event publisher | EXISTING | Built |
| AUDIT-003 | Audit ingestion | NOT REQUIRED | Closed — synchronous write is better here |
| AUDIT-004 | Tenant-isolated audit storage | EXTEND | Built |
| AUDIT-005 | Audit search | NEW | Planned |
| AUDIT-006 | Audit filtering | NEW | Planned |
| AUDIT-007 | Audit retention policies | EXTEND | Built |
| AUDIT-008 | Audit archival | NEW | Planned |
| AUDIT-009 | Audit purge | EXTEND | Built — **not finishable until AUDIT-010** |
| AUDIT-010 | Legal / compliance hold | NEW | Planned |
| AUDIT-011 | Audit export | NEW | Planned |
| AUDIT-012 | Audit export jobs | EXTEND | Planned |
| AUDIT-013 | Customer audit viewer contract | NEW | Planned |
| AUDIT-014 | Control Plane audit contract | EXISTING | Built |
| AUDIT-015 | Audit RBAC | EXTEND | Planned |
| AUDIT-016 | Audit integrity | EXISTING | Built |
| AUDIT-017 | Audit observability | NOT REQUIRED | Closed — no metric API |
| AUDIT-018 | Audit configuration inheritance | NEW | Planned |
| AUDIT-019 | Audit action registry | NEW | Built |
| AUDIT-020 | Audit event classification | NEW | Built |
| AUDIT-021 | Storage operations recorded | NEW | Built |

**9 built · 9 planned · 0 blocked · 3 closed**

## Blockers, and who owns them

| Blocker | Blocks | Owner |
|---------|--------|-------|
| Nothing provisions a bucket | STORAGE-009..013, AUDIT-008 | A human decision; ADR 0006 question 1 |
| No entitlement codes in the platform catalogue | STORAGE-012, AUDIT-011, AUDIT-015 | Control Plane work, governed by F3/F2b |
| No metric API in the repository | STORAGE-014, AUDIT-017 | Open framework decision |
| No hold record | AUDIT-009 cannot be finished | AUDIT-010 |
| The two capabilities are undeclared | Every gated surface | Generator work; both off by default when declared |

## Definition of Done — where both features stand

| Condition | SAG-F1 | SAG-F2 |
|-----------|--------|--------|
| Stories done or closed with a reason | partial | partial |
| Automated tests pass, evidenced | yes, for built stories | yes, for built stories |
| Tenant isolation proven as the restricted role | yes, except the sweep's own audit write | yes, except the same |
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

1. **Two `.sql` isolation tests** — the reconciliation sweep's cross-context
   insert, and a tenant's inability to rewrite `classification`. Both are small,
   both cover a boundary deliberately crossed, and both are cheaper now.
2. **Independent security review** of what shipped, before more ships.
3. **Answer ADR 0006 question 1.** It blocks six stories across both features.
4. **Declare the two capabilities**, so the gated surfaces have somewhere to go.
5. **AUDIT-010**, because AUDIT-009 cannot be called finished without it and a
   sweep with no hold check will eventually delete something an investigation
   needed.
6. Then search and export, which are the first things a customer would notice.
