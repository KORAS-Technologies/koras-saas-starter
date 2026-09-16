# SAG-F1 — Storage Architecture & Data Protection

| | |
|---|---|
| **Feature ID** | SAG-F1 |
| **Feature name** | Storage Architecture & Data Protection |
| **Initiative** | Storage & Audit Governance (SAG) |
| **Status** | Part built (2026-09-16) |
| **Owner** | KORAS platform engineering |
| **Decision records** | `docs/adr/0003-koras-storage-audit-governance.md`, `0004`, `0005`, `0006` |
| **Architecture** | `docs/STORAGE_ARCHITECTURE.md` |

## Purpose

Give every generated KORAS product one way to store a customer's files that is
tenant-isolated, provider-independent, quota-enforced, integrity-checked,
auditable and recoverable — so that a product adds a page and never rebuilds
any of it.

## Problem statement

The Files module shipped on 2026-09-08 with a provider seam, an index, a quota
and signed URLs. What it did not have was anything that could be called data
protection:

- **No integrity.** A repository-wide search for a digest found one bootstrap
  helper. No copy of an object could be compared with the original, which makes
  a backup impossible to verify and a corruption impossible to detect.
- **No trace.** Upload, download and deletion emitted no audit events at all.
  The one module storing customer data was the one module whose operations left
  no record.
- **No reconciliation.** Two comments in `00005_files.sql` promised a sweep to
  find objects without rows. The provider protocol had no way to ask a bucket
  what it holds, so the sweep could not be written.
- **An advisory quota.** Checked when a ticket was issued and never again, so
  two concurrent uploads could each be inside the limit and jointly over it.
- **One extension slot.** The file hook was a mutable record with three fields;
  the assistant's indexer occupied it, and a scanner arriving second would have
  replaced it silently.

## Business value

Storage is the part of a SaaS product a customer notices losing. Three concrete
returns:

1. **A sellable answer to a security questionnaire.** "Is data scanned, is
   access logged, can you prove a file was not altered" are questions every
   enterprise procurement asks, and the honest answer was no.
2. **Recoverability.** Backup is meaningless without integrity, and integrity
   is the prerequisite this feature delivers.
3. **One implementation, not one per product.** Docoris, Dianova and LegalApp
   inherit it rather than each writing their own and each getting it subtly
   wrong.

## Scope

- The provider abstraction and the providers this estate actually uses
- The canonical object key and what belongs in it
- The object metadata model
- Integrity: digests recorded, and their provenance recorded with them
- Quota enforcement at both ends of an upload
- The file hook registry, and a scan seam with enforced quarantine
- Reconciliation between bucket and index
- Audit of every storage operation
- Lifecycle, retention, legal hold, backup and restore **as design**

## Out of scope

| Excluded | Why |
|----------|-----|
| Disaster recovery | An estate-level decision about RPO, RTO and failover. Needs its own ADR; does not belong in a product template. Decided 2026-09-15 |
| Integrating a specific malware scanner | A product's decision, often a customer's contractual one. The starter owes a seam, not a vendor |
| Azure Blob, customer-owned buckets | Not S3-compatible, and no credential in the estate. Refused with 503 and a reason |
| Multipart upload | One object, one signed PUT, five gigabytes. `FOLLOW_UPS.md` F22 |
| Object versioning | Modelled as a column and deliberately inert; see ADR 0003 consequences |
| Per-period storage quota | The platform's quota mechanism needs a period and storage has none. F22 |

## Personas

| Persona | What they need |
|---------|----------------|
| Tenant member | Upload and download their organization's files without thinking about any of this |
| Tenant owner / administrator | Delete files, see the quota, answer "who downloaded that" |
| Security administrator | Know that scanning exists, that withheld files are refused server-side, and that access is logged |
| Platform operator (KORAS staff) | Know that backups ran and verified; find orphans; restore on request |
| Compliance officer | Prove retention, prove a hold was honoured, export the evidence |
| Product developer | Register a hook, attach a file to a domain record, never touch a bucket |

## Functional requirements

| # | Requirement | State |
|---|-------------|-------|
| FR-01 | Objects are stored through one provider-independent interface | Built |
| FR-02 | Bytes never pass through the product; the browser talks to the bucket | Built |
| FR-03 | The object key is minted by the API and never by the caller | Built |
| FR-04 | Every object is scoped to exactly one tenant, enforced in the database | Built |
| FR-05 | A digest is recorded at upload, with its provenance distinguishable | Built |
| FR-06 | The quota is enforced at ticket issue and again at confirmation | Built |
| FR-07 | Every storage operation and refusal is audited | Built |
| FR-08 | More than one module may register an interest in an upload | Built |
| FR-09 | A scan result may be recorded, and a withheld file is refused server-side | Built (seam; no scanner) |
| FR-10 | The bucket and the index can be compared, and disagreements reported | Built |
| FR-11 | Objects carry classification, retention and hold state | Schema only |
| FR-12 | Retention expiry moves an object through its lifecycle | Not built |
| FR-13 | A legal hold prevents removal whatever the dates say | Not built |
| FR-14 | Objects are backed up daily and the copy is verified | Not built |
| FR-15 | An object or a scope can be restored, with approval | Not built |

## Non-functional requirements

| # | Requirement |
|---|-------------|
| NFR-01 | A signed upload URL expires in 15 minutes; a download URL in 5 |
| NFR-02 | A listing is paged; no unbounded query against a bucket or the index |
| NFR-03 | A sweep that cannot complete reports partial rather than acting on a partial answer |
| NFR-04 | A hook failing after an upload must not fail the upload |
| NFR-05 | The largest single object is 5 GiB |
| NFR-06 | A credential never appears in a log, an audit row, an API response or a client bundle |

## Dependencies

| Depends on | Why |
|------------|-----|
| `koras-tenant`, `koras-database` | Trusted tenant context, and a transaction that refuses to open undeclared |
| `koras-auth`, `packages/permissions` | The permission catalogue, mirrored in both runtimes |
| Control Plane storage policy | Which provider serves which customer |
| Control Plane entitlements | Whether the tenant may store anything, and how much |
| Doppler | Every provider credential |
| `koras-audit` | The envelope, the redaction rule and the action registry |

## Entitlements

| Code | State |
|------|-------|
| `storage.files` | **Exists.** Granted from Starter upward, per-plan ceiling in gigabytes |
| storage archive, restore, custom retention, cross-provider backup | **Proposed.** Not in the platform catalogue as of 2026-09-16, and adding them is Control Plane work this task must not do |

## Configuration

See `docs/features/storage-architecture/configuration.md`. In brief: bucket and
credentials from Doppler; provider per customer from the Control Plane;
reconciliation off unless asked for.

## Security requirements

See `docs/features/storage-architecture/security.md` and `docs/AI_SECURITY.md`
for the approval machinery a restore reuses. The load-bearing ones:

- Authorization is decided server-side on every path, and the key's spelling
  authorizes nothing.
- Row-level security is forced on the index, so the API's checks and the
  database's are two independent layers.
- A withheld file is refused before a URL is signed.
- A signed URL is a bearer credential and is never logged or audited.

## Tenant isolation requirements

- Every object key is prefixed by the tenant, and the prefix is chosen by the API.
- Every row carries `tenant_id` with forced row-level security.
- Cross-tenant insert, update, delete and `tenant_id` movement are each refused,
  proven as a restricted role against a real Postgres.
- A sweep reaching every tenant runs only on the provisioning context, which is
  transaction-local and derived from no request input.

## Observability

Audit events for every operation (see SAG-F2). Tracing through the API.
Structured logs from the sweeps.

**There is no metric API in this repository as of 2026-09-16** — observability
is tracing-only, so byte and object counts are answered by queries rather than
gauges. Introducing counters would be new framework and is an open decision.

## Risks

| ID | Risk | Mitigation |
|----|------|------------|
| R-044 | A sweep deletes what it should not | Reconciliation reports and never deletes; a partial listing reports no orphans |
| R-045 | A backup reports success without being verifiable | `verified` requires a digest match; a copy call returning success is `copied` |
| R-046 | A client-asserted digest is mistaken for end-to-end integrity | Two columns, and documentation that says which is which |
| R-047 | Cross-provider credentials widen a leak's blast radius | API-process only, Doppler-held, never presigned |
| R-048 | The capability leaks files into products that excluded it | The derived leak test covers Python; SQL and TypeScript need review by hand |

## Definition of Done

Per `profiles/product/template/.claude/orchestration/definition-of-done.md`.
For this feature specifically, and **none of the last four is satisfied as of
2026-09-16**:

1. Every story either done, or marked `NOT REQUIRED` with a reason — *partial*
2. Automated tests pass, evidenced by executed results — *satisfied for shipped stories*
3. Tenant isolation proven as the restricted role — *satisfied, except the reconciliation sweep's own audit write*
4. Independent code review with no unresolved CRITICAL or HIGH — **not run**
5. Security review by an agent that did not write the code — **not run**
6. Manual QA executed against a real environment with evidence — **not run**
7. `final-acceptance` reports READY — **not run**
