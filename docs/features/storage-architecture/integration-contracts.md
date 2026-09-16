# SAG-F1 — Integration contracts

What the Control Plane and a customer's own portal would consume, defined here
so that building either later is an implementation rather than a negotiation.

> **Nothing here is built, and nothing in this task modifies the Control Plane
> or any generated product.** Contracts are defined; consumers are not written.
> Status 2026-09-16.

## Where a contract lives

`profiles/_shared/template/contracts/product-platform.v1.json` is the single
declaration both sides read, and both profiles ship an identical copy. Its
rules are named objects with a requirement and a reason:

| Rule | What it means here |
|------|--------------------|
| `machine_identity_only` | Every route below is machine-to-machine; no customer token reaches them |
| `create_is_idempotent` | A collector repeating a call must not double-count |
| `no_direct_writes` | The platform reads; it does not write into a product's tables |
| `environment_must_match` | A dev collector never reads prod |

A breaking change is a `v2` alongside `v1`, never an edit to `v1`.

## Control Plane — what the platform would read

All on the private prefix `/internal/platform/v1`, counts and aggregates only.

### `GET /storage-summary`

Per tenant: object count, total bytes, bytes by category, the provider actually
in use, and the quota ceiling resolved for that tenant.

**No names, no keys, no uploader identities.** The platform is answering "is this
customer near their limit and where are their files", not "what does this
customer have".

### `GET /storage-backup-status`

Per tenant: the last run's outcome, when it finished, how many objects were
`copied` versus `verified`, and the first error where there was one.

The distinction between copied and verified is the contract's whole reason for
existing. A console showing "backed up" for objects that were only copied would
report a safety property the estate does not have.

*Blocked until STORAGE-009 and STORAGE-011.*

### `GET /storage-restore-history`

Per tenant: restore requests with their state, who requested, who approved, the
scope and the outcome. No object contents and no keys.

*Blocked until STORAGE-012.*

### `GET /storage-reconciliation`

Per tenant: the last sweep's counts — orphan objects, stale pending rows,
unverifiable rows — and whether the listing was partial.

**`partial` must be carried through to the console.** A count derived from an
unfinished listing that is presented as a total is worse than no count.

*Buildable now: the sweep exists and records these.*

## What the platform must never receive

| Never | Why |
|-------|-----|
| An object key | Half a signed URL |
| A signed URL | A bearer credential |
| A provider credential | Doppler holds these; the platform holds references by name |
| A filename or uploader identity | Metadata is disclosure; counts answer the platform's questions |
| File contents | Obviously |

## Customer portal — what a tenant administrator would see

Served from the product's own API on `/api/v1`, with the customer's token, gated
by permission **and** entitlement.

| Surface | Permission | Entitlement | State |
|---------|-----------|-------------|-------|
| My storage: usage against quota | `files.read` | `storage.files` | **Buildable now** |
| Per-category breakdown | `files.read` | `storage.files` | **Buildable now** |
| Integrity: how many objects carry a verified digest | `files.manage` | `storage.files` | **Buildable now** |
| Backup status for my data | `files.manage` | proposed | Blocked |
| Request a restore | `files.manage` | proposed | Blocked |
| My retention policy | `files.read` | proposed | Blocked |

Three rules for that surface:

1. **Server-authorized.** The web tier renders a decision; it never makes one.
2. **An unresolved plan hides rather than lies.** A figure that cannot be
   computed is reported unavailable, never zero — the rule
   `docs/REPORTING_ARCHITECTURE.md` already applies to derived revenue.
3. **A restore request is not a restore.** It enters the approval flow; the
   portal shows its state and never performs it.

## Proposed entitlement codes

Not in the platform catalogue as of 2026-09-16. Adding them is Control Plane
work, and `FOLLOW_UPS.md` F3/F2b is the open authorization question that governs
what a product may do toward the platform at all.

```
storage.archive
storage.restore
storage.custom_retention
storage.cross_provider_backup
```

Each would be read exactly as `storage.files` is read: with the customer's own
token, cached, and with the silence policy stated per operation rather than
assumed — upload continues during an outage, restore does not.

## Events, not polling

The platform **pulls**. The AI usage contract settled this on 2026-09-14 and the
reasoning transfers unchanged: a product pushing to the platform needs a
credential toward the platform, which is exactly the thing F2b has not decided
it may hold. Until that is answered, every contract above is a route the
platform's collector reads on its own schedule, recording each attempt so that a
product with nothing to report still reads as collected and one that has stopped
answering reads as stale.
