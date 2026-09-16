# SAG-F2 — Audit Storage, Retention & Archival

| | |
|---|---|
| **Feature ID** | SAG-F2 |
| **Feature name** | Audit Storage, Retention & Archival |
| **Initiative** | Storage & Audit Governance (SAG) |
| **Status** | Part built (2026-09-16) |
| **Owner** | KORAS platform engineering |
| **Decision record** | `docs/adr/0003-koras-storage-audit-governance.md` |
| **Architecture** | `docs/AUDIT_ARCHITECTURE.md` |

## Purpose

Give every generated KORAS product one durable, tenant-isolated record of what
people and systems did, kept for as long as each kind of record deserves and no
longer, readable by the people entitled to read it, and impossible to edit.

## Problem statement

The starter had an audit envelope and a durable table, and three things wrong
with how they were arranged:

1. **The table belonged to the wrong owner.** `audit_events` shipped inside the
   `reporting` capability, so a product generated `--without reporting` had
   nowhere to record at all. A general audit table an unrelated capability can
   remove is not somewhere another module can safely record.
2. **One retention number governed everything.** A year for "somebody opened a
   file" and a year for "somebody was refused access to one" — simultaneously
   too long and too short, and nothing on the row said which was which.
3. **Actions were strings.** Whatever a call site passed became the action, with
   no declaration, no classification and no way to know what a build could
   record.

And one thing missing entirely: **storage recorded nothing**, so the module
holding customer files was the module with no history.

## Scope

- The event envelope, its redaction rule and its outcome vocabulary
- A declared action registry with classification per action
- The durable table, forced and insert-only, as foundation
- Classification on the row, and retention per class
- The write path, including the cross-context write a sweep needs
- The platform's aggregate view
- Search, export, archival and legal hold **as design**

## Out of scope

| Excluded | Why |
|----------|-----|
| A parallel event system | `koras-audit` and `audit_events` exist. A second pipeline would be the duplication this repository's rules reject |
| Operational logs in the audit store | They go to Loki. Putting them here makes the compliance store a log |
| Merging `ai_audit_events` into the general table | Deliberate duplication, swept on its own schedule; 00013's own header records the choice |
| Immutable external storage (WORM) | No requirement has asked for it; the table is insert-only with no update policy for anyone |

## Event categories

The distinction that keeps this table useful:

> An event is a row here only when somebody may later have to prove it happened.

| Category | Store | Kept | Tenant sees |
|----------|-------|------|-------------|
| Audit event | `audit_events`, class `audit` | a year | yes |
| Activity event | `audit_events`, class `activity` | 90 days | yes |
| Security event | `audit_events`, class `security` | 3 years | owners and administrators |
| Administrative event | `audit_events`, class `administrative` | a year | yes |
| Application event | structured log, Loki | days | no |
| Operational log | stdout, traces to Tempo | days | no |

## Functional requirements

| # | Requirement | State |
|---|-------------|-------|
| FR-01 | One envelope shared by every module and both profiles | Built |
| FR-02 | A refusal is recorded as firmly as a success | Built |
| FR-03 | A detail named like a credential is refused, not masked | Built |
| FR-04 | Actions are declared with their class; duplicates refused at import | Built |
| FR-05 | An undeclared action is refused at recording, not defaulted | Built |
| FR-06 | The table is foundation and survives `--without reporting` | Built |
| FR-07 | Rows are insert-only; no update policy for anyone | Built |
| FR-08 | Each class is swept at its own age | Built |
| FR-09 | A sweep reaching every tenant uses the provisioning context only | Built |
| FR-10 | The platform reads counts only, machine identity only | Built |
| FR-11 | A tenant administrator can search their own audit history | **Not built** |
| FR-12 | An authorized export produces CSV, JSON or NDJSON asynchronously | **Not built** |
| FR-13 | Rows move to cold storage before purge | **Not built** |
| FR-14 | A legal hold prevents purge whatever the dates say | **Not built** |

## Non-functional requirements

| # | Requirement |
|---|-------------|
| NFR-01 | Recording must not fail a request that otherwise succeeded, except where the record is the point |
| NFR-02 | A search is served from an index, never a sequential scan |
| NFR-03 | The sweep runs in one transaction per night, so an interruption leaves the table consistent |
| NFR-04 | No row carries a secret, a token, a payload or a file's contents |

## Retention

`docs/RETENTION_POLICY.md`. Precedence, strongest first: legal hold, regulatory
requirement, platform floor, product policy, tenant policy. **A tenant may
lengthen and may never shorten below the floor**, which inverts what the original
request proposed and is reconciled there.

## Archive, purge, export, legal hold

`archival.md` and `legal-hold.md` in this directory. All four are design;
`purge` today means the retention sweep's delete, with no archive step before it
and no hold check protecting it.

## Access control

| Who | Sees |
|-----|------|
| Tenant member | Their organization's non-security rows, through the Activity report |
| Owner / administrator | The same, plus security-classified rows |
| Platform machine identity | Counts per tenant, day, action and outcome. No actors, no targets |
| The worker | Every row, on the provisioning context, to delete by age |
| Nobody at all | Any update. There is no update policy |

Proposed permissions and entitlements — `audit.view`, `audit.export`,
`audit.extended_retention`, `audit.legal_hold` — are **not in any catalogue as of
2026-09-16**.

## Platform and customer visibility

`integration-contracts.md`. The platform pulls; a product pushes nothing,
because pushing needs a credential toward the platform and
`FOLLOW_UPS.md` F3/F2b has not decided a product may hold one.

## Compliance considerations

- Rows are evidence, so they outlive the data they describe and must carry none
  of it.
- Classification drives retention, so misclassifying an action is a compliance
  error rather than a tidiness one — which is why the class belongs to the
  declared action and not to the call site.
- A hold must outrank an expiry, or retention becomes a deletion schedule an
  investigation cannot stop.
- Deleting is irreversible: the sweep refuses a retention below one day, and
  checks every class before deleting any.

## Risks

| ID | Risk | Mitigation |
|----|------|------------|
| R-043 | Moving the table out of the reporting gate breaks existing products | Landed alone; the generator matrix proves both `--with` and `--without` |
| R-050 | An unregistered action 500s a route that would otherwise have succeeded | Deliberate: a silent default is worse. Tests exercise every route's audit path |
| R-051 | Classification drift between the API registry and the worker's literal | The worker spells `audit` for its one action; a test asserts the two agree |
| R-052 | The audit table grows unboundedly if the sweep stops | The sweep logs counts per class; no alert exists yet |

## Definition of Done

Per `definition-of-done.md`. **Unmet as of 2026-09-16:** independent code
review, security review, privacy and compliance review, manual QA with evidence,
and `final-acceptance`. Four of the fourteen functional requirements are
unbuilt.
