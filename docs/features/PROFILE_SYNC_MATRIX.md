# Storage & Audit Governance — profile sync matrix

Which repository owns what, for every `STORAGE-*` and `AUDIT-*` story. The
cross-**repository** sibling of `STATUS.md`, which tracks the same stories
cross-**feature**. Written 2026-09-16.

`STATUS.md` answers "is this story built". This answers "built *where*, and what
does each of the three repositories owe it".

> **Why this file is here and not in `docs/features/storage-audit-governance/`.**
> That directory would be a third feature directory for something that is not a
> feature. `STATUS.md` already spans both features from `docs/features/`, and
> this belongs beside it.

## The three repositories, and how they actually relate

| Repository | Profile | How it receives shared work |
|------------|---------|-----------------------------|
| `koras-saas-starter` | *neither* — it is the factory | Canonical. Nothing flows into it. |
| `output/koras-e2e-shop` | `product` | A hand-carried `chore: sync … from the starter` commit per change |
| `koras-control-plane` | `control-plane` | **Nothing flows into it but one file.** See below |

**The Control Plane is not kept in sync from the starter, and the architecture
diagram most people draw is wrong about this.** It was generated once and then
built out independently. `profiles/control-plane/template/apps/` contains only
`api/auth` and `login`; every real console surface — organizations, products,
entitlements, analytics, health, storage policy — was written in that repository.
Its `packages/` and `python-packages/` are local workspace members named
`@koras-control-plane/*`, resolving to nothing upstream.

Exactly one artifact is genuinely shared:
`contracts/product-platform.v1.json`, kept byte-identical by hand and checked
from the starter's side by `shared-template-parity.test.ts`.

**So "sync a feature into the Control Plane" means: extend the contract, then
implement a consumer there.** It never means copying template files, and any
plan that assumes otherwise will produce work nobody can apply.

## The constraint that decides most of this matrix

`contracts/product-platform.v1.json` states the rule as
`no_direct_writes`: *"The Control Plane never writes to product business
tables. Every interaction goes through these routes."*

Three consequences, and they remove more from the Control Plane's share than
anything else here:

1. **The platform can observe product governance; it cannot administer it.**
   Retention periods, legal holds, restore approvals and export requests all
   live in a product's own database under that tenant's RLS. A console that
   changed one would be a second schema owner.
2. **What the platform may read is counts.** Both integration-contract documents
   say so at length, and the reason is not squeamishness: actor ids and hold
   reasons are cross-tenant personal data being moved for an operational
   question.
3. **Administration from the console is therefore a new decision, not a sync.**
   It needs a write contract that does not exist, and it would put a platform
   operator inside a tenant's two-person approval.

**That decision was taken on 2026-09-16: observe, plus administration in one
direction only.**

`no_direct_writes` forbids writing to product *tables*, not platform-initiated
change as such — `PUT /tenants/{tenant_id}/plan` is already a platform write
that goes through a contract route. So the question was never "can the platform
act" but "which acts are safe to hand it".

The rule, and it is one sentence: **the platform may only act in the direction
that keeps data.**

| The platform may | The platform may not | Why the asymmetry |
|------------------|----------------------|-------------------|
| Raise a retention floor | Lower one | Lengthening cannot destroy; shortening is a deletion with a configuration change's blast radius |
| Place a legal hold | Lift one | A hold is the customer's legal instrument; lifting it is what makes a purge possible again |
| Trigger a backup, a verification or a reconciliation | Trigger a purge, an expiry or a lifecycle sweep | The first three read and copy; the last three delete |
| Pause a destructive sweep estate-wide | Resume or force one | Stopping a deletion is recoverable in a way that starting one is not |
| Read counts | Approve a restore or an export | Both are inside a tenant's own two-person rule, and a platform operator is not one of that tenant's two people |

Every capability on the left preserves data and every one on the right destroys
or discloses it. That is the whole test, and it is deliberately mechanical: a
future route is admitted by asking which column it falls in, not by weighing how
useful it would be.

This needs its own ADR before the first write route is built. It is recorded
here because it was decided before the work, which is the order these decisions
keep failing to happen in.

## The Control Plane's two audit tables are not the same thing

`koras-control-plane` has `public.audit_events` (migration `00010_operations.sql`)
— actor, action, `resource_kind`, `organization_id`, before/after state,
append-only via a `reject_mutation()` trigger. It records **what platform staff
did to the platform**.

A product has `public.audit_events` (migration `00013_audit_events.sql`) —
tenant-scoped, four classes, retention per class. It records **what a customer's
people did in the product**.

Same name, different schema, different subject, different database. Nothing in
`AUDIT-*` is about the first one. A matrix row saying the Control Plane
"already has audit search" would be true of a different table and useless here.

## Matrix — SAG-F1, Storage Architecture & Data Protection

Legend: **S** = starter owns the implementation · **P** = reaches the product by
template · **CP** = Control Plane work · *observe* = reads counts through the
contract · — = nothing owed.

| Story | Title | Classification | Starter | Product | Control Plane | Entitlement | RBAC | Contract | Status |
|-------|-------|----------------|---------|---------|---------------|-------------|------|----------|--------|
| STORAGE-001 | Provider abstraction | SHARED | `koras-storage` | consumes | — | — | — | — | Synced |
| STORAGE-002 | Metadata registry | SHARED | `00005`,`00018` | consumes | *observe* | — | `files.read` | `/governance` | Synced |
| STORAGE-003 | Tenant-isolated objects | SHARED | RLS + key scheme | consumes | — | — | — | — | Synced |
| STORAGE-004 | Configurable providers | BOTH | `resolve_destination` | consumes | **owns the policy** | `storage.files` | area `storage` | `/storage-defaults` | Synced |
| STORAGE-005 | Storage quotas | BOTH | enforcement | enforces | **owns the limit** | `storage.files` GB/plan | area `entitlements` | — | Synced |
| STORAGE-006 | Object lifecycle | SHARED | `storage_lifecycle.py` | runs it | *observe* | — | — | `/governance` | **Product behind** |
| STORAGE-007 | File versioning | NOT REQUIRED | — | — | — | — | — | — | Closed |
| STORAGE-008 | Signed URLs | SHARED | `presign_*` | consumes | **never receives one** | — | `files.read` | — | Synced |
| STORAGE-009 | Daily backup | SHARED | `storage_backup.py` | runs it | *observe* — proposed | — | — | proposed | **Product behind** |
| STORAGE-010 | Cross-provider backup | SHARED | same | runs it | *observe* | — | — | proposed | **Product behind** |
| STORAGE-011 | Backup verification | SHARED | digest comparison | runs it | *observe* | — | — | proposed | **Product behind** |
| STORAGE-012 | Object restore | SHARED | `00026`, `core/restore.py` | **missing** | *observe only* — see the constraint above | **none, decided** | `files.manage` + two people | proposed | **Not synced** |
| STORAGE-013 | Snapshot restore | NOT STARTED | — | — | operator runbook | — | — | — | Not started |
| STORAGE-014 | Usage metrics | NOT REQUIRED | — | — | — | — | — | — | Closed |
| STORAGE-015 | Administration contracts | BOTH | `/governance` built | serves it | **contract + collector + page** | — | area `storage` | `/governance` | **CP not started** |
| STORAGE-016 | Config inheritance | BOTH | `retention_days_for` | tenant override | policy half exists | — | `files.manage` | — | Synced |
| STORAGE-017 | Integrity at upload | SHARED | digest seam | consumes | *observe* | — | — | `/governance` | Synced |
| STORAGE-018 | Scan seam, quarantine | SHARED | `file_scan.py` | consumes | *observe* | — | — | `/governance` | Synced |
| STORAGE-019 | Reconciliation | SHARED | `storage_reconcile.py` | runs it | *observe* — proposed | — | — | proposed | Synced |
| STORAGE-020 | Upload hooks | SHARED | `file_hooks.py` | consumes | — | — | — | — | Synced |

## Matrix — SAG-F2, Audit Storage, Retention & Archival

| Story | Title | Classification | Starter | Product | Control Plane | Entitlement | RBAC | Contract | Status |
|-------|-------|----------------|---------|---------|---------------|-------------|------|----------|--------|
| AUDIT-001 | Canonical event model | SHARED | `koras-audit` | publishes | *observe* | — | — | `/activity` | Synced |
| AUDIT-002 | Event publisher | SHARED | `core/audit.py` | publishes | — | — | — | — | Synced |
| AUDIT-003 | Ingestion | NOT REQUIRED | — | — | — | — | — | — | Closed |
| AUDIT-004 | Tenant-isolated storage | SHARED | `00013` + RLS | consumes | — | — | — | — | Synced |
| AUDIT-005 | Audit search | PRODUCT | `routers/audit.py` | serves it | **N/A — different table** | none | `audit.view` | — | Synced |
| AUDIT-006 | Audit filtering | PRODUCT | typed bound filters | serves it | N/A | none | `audit.view` | — | Synced |
| AUDIT-007 | Retention policies | SHARED | `audit_retention.py` | runs it | *observe only* — **cannot administer** | — | — | proposed | Synced |
| AUDIT-008 | Archival | BLOCKED | — | — | — | — | — | — | Blocked: no bucket |
| AUDIT-009 | Purge | SHARED | hold-aware sweep | runs it | *observe* | — | — | proposed | Synced |
| AUDIT-010 | Legal hold | SHARED | `00020`, `routers/holds.py` | serves it | *counts by scope only, never a reason* | none | `audit.legal_hold` | proposed | Synced |
| AUDIT-011 | Audit export | SHARED | `audit_exports.py` | serves it | *counts only, never an artifact or URL* | none today | `audit.export` | proposed | Synced |
| AUDIT-012 | Export jobs | SHARED | `audit_exports` + sweep | runs it | *observe* | — | — | proposed | Synced |
| AUDIT-013 | Customer viewer | PRODUCT | Audit page | **has it** | — | none | `audit.view` | — | Synced |
| AUDIT-014 | Control Plane contract | BOTH | `/activity` | serves it | **collector built** | — | — | `/activity` | Synced |
| AUDIT-015 | Audit RBAC | SHARED | `permissions.py` | enforces | — | — | three codes | — | Synced |
| AUDIT-016 | Audit integrity | SHARED | no update policy | consumes | — | — | — | — | Synced |
| AUDIT-017 | Observability | NOT REQUIRED | — | — | — | — | — | — | Closed |
| AUDIT-018 | Config inheritance | SHARED | `retention_overrides` | serves it | *observe* | — | `files.manage` | — | Synced |
| AUDIT-019 | Action registry | SHARED | `core/audit.py` | consumes | — | — | — | — | Synced |
| AUDIT-020 | Event classification | SHARED | `00019` | consumes | *observe by class* | — | — | `/governance` | Synced |
| AUDIT-021 | Storage operations recorded | SHARED | storage actions | records | *observe* | — | — | — | Synced |

## What each repository actually owes

### `koras-saas-starter`

1. **Finish STORAGE-012's surface.** `GET /api/v1/backups`, the api-client
   block and `dashboard/restore/actions.ts.hbs` are written and uncommitted;
   `RestorePanel.tsx.hbs`, `page.tsx.hbs`, the i18n keys, the navigation entry
   and an e2e spec are not. Without the catalogue route the feature is
   unusable — the `files` row for a deleted object is gone, so nothing else can
   find it.
2. **Correct `storage-architecture/user-stories.md`.** Its summary table still
   reads STORAGE-012 `Blocked`, STORAGE-015 `Planned`, STORAGE-016 `Planned`.
   All three shipped 2026-09-16. R-042.
3. **Add a `## Profile applicability` section** to both `feature.md` files.

### `output/koras-e2e-shop`

1. **Sync two commits** — `ac87be6` and `6004821`. That is the whole of
   STORAGE-012 plus the capability declarations: eight files, migration `00026`,
   five error codes, four audit actions, the api-client block and fifteen i18n
   keys.
2. **Three findings that are the shop's own and predate this work.** Decided
   2026-09-16: **a separate pass, not this one.** None of them is a governance
   defect and folding them in would make a sync indistinguishable from a repair.
   They are recorded here rather than in that repository because it has no
   `docs/` at all, which is the third of them:
   - `purge_shop_orders` exists, is tested, and **is never scheduled** —
     `worker.py` is kept starter-identical and the shop's task had nowhere to
     register.
   - Shop migrations are numbered `00014_shop.sql` and `00015_shop_retention.sql`,
     **colliding with starter ordinals**. Ordering is lexicographic luck.
   - No `docs/AGENT_CONTEXT.md`, which `CLAUDE.md` names as the one file the
     generator never overwrites and the designated home for exactly these
     decisions.

### `koras-control-plane`

Its share is small, precise, and smaller than a reading of the feature titles
suggests.

1. **Contract first, and it is two files.** `GET /governance` is in the
   starter's contract and absent from the Control Plane's copy.
   `tests/contract/test_product_platform_contract.py` asserts the declared
   routes equal what `tests/contract/reference_product.py` implements, so
   adding the route to the JSON fails that suite until the reference product
   serves it. **Nothing else in the Control Plane can start until this lands.**
2. **A `governance` collector**, following `ai_usage` and `product_activity`
   exactly: `collect_product` / `collect_estate`, hourly from the scheduler,
   every attempt recorded in `collection_runs`. That table's
   `collection_runs_collector_known` check constrains the collector name, so a
   migration widens it — next ordinal `00044`.
3. **One console page** under the existing `storage` area: `NavigationItem` in
   `apps/admin/src/lib/navigation.ts`, `DataTable`, no new UI foundation.
4. **Nothing else.** No object layer, no retention administration, no restore
   approval, no hold management. Each of those is blocked by `no_direct_writes`
   rather than by effort.

## Entitlements

`storage.restore` was **proposed and then decided against** on 2026-09-16
(ADR 0006 question 3). Restore is gated by `files.manage` plus the two-person
rule and no entitlement, because gating data recovery behind a plan tier means a
customer whose plan lapsed cannot get their data back.

Two things worth knowing before any code is added to the platform catalogue:

- A code must be added in **two** places — `ENTITLEMENT_CATALOGUE` in
  `python-packages/koras-platform/src/koras_platform/plans.py`, *and* a
  migration for products already registered, because the seed runs only at
  registration.
- The five `reporting.*` codes were migration-only and absent from the Python
  catalogue when this was written on 2026-09-16. That inconsistency is not this
  feature's, and it is the shape of the mistake anyone adding a code here would
  repeat.

## RBAC

Nothing new in either repository.

| Where | Vocabulary | Governs |
|-------|-----------|---------|
| Product | `files.read`, `files.upload`, `files.manage`, `audit.view`, `audit.export`, `audit.legal_hold` | Every customer-facing surface here |
| Control Plane | `AREA_ROLES` in `packages/permissions/src/index.ts` | Console visibility; a new page adds a key |
| Control Plane | `platform.read/billing/support/admin` | Wired only into reporting today |

## Database ownership

| Migration range | Database | Owner |
|-----------------|----------|-------|
| `00018`–`00026` (product) | each product's Supabase | starter template |
| `00044+` (platform) | Control Plane Supabase | written in that repo |

**No governance migration is copied between databases.** The Control Plane's
only migration here widens a check constraint on its own `collection_runs`.
