# SAG-F2 — Integration contracts

What the Control Plane and a customer's portal would consume from a product's
audit store.

> **Nothing here modifies the Control Plane or any generated product.**
> Contracts are defined; consumers are not written. Status 2026-09-16.

## Where a contract lives

`profiles/_shared/template/contracts/product-platform.v1.json`, read by both
sides, identical in both profiles, versioned in the path so a breaking change is
a `v2` alongside rather than an edit.

Its rules apply unchanged: machine identity only, idempotent creates, no direct
writes, and the environment must match.

## Control Plane — built

### `GET /internal/platform/v1/activity?since=`

Already exists. Events and distinct actors per tenant, day, action and outcome,
up to 92 days. **Counts only**: no actor ids, no target ids, no details.

The Control Plane's hourly collector keeps daily rows per organization for its
Usage and Adoption report, and records each attempt so that a product with
nothing to report still reads as collected while one that has stopped answering
reads as stale.

## Control Plane — proposed

### `GET /internal/platform/v1/audit-summary`

Per tenant: row counts by class, the oldest row per class, and when the sweep
last ran.

The purpose is operational rather than investigative. It answers "is retention
working across the estate" — a product whose oldest activity row is two years
old has a sweep that stopped, and nothing surfaces that today.

### `GET /internal/platform/v1/audit-holds`

Per tenant: how many holds are active and what they cover, by scope kind. Never
the reason text, which is legal context and often names a matter.

*Blocked until AUDIT-010.*

### `GET /internal/platform/v1/audit-exports`

Per tenant: export jobs with state, requester, scope and outcome. Never the
artifact and never a URL to it.

*Blocked until AUDIT-011.*

## What the platform must never receive

| Never | Why |
|-------|-----|
| Audit row contents | The platform's questions are answered by counts |
| Actor ids | Cross-tenant personal data, for an operational question |
| Details maps | The place a mistake would surface |
| Hold reasons | Legal context, often naming a matter or a person |
| Export artifacts or their URLs | A signed URL is a bearer credential |

The principle: **the platform is answering questions about the estate, not about
anyone's records.** Every route above is an aggregate, and the moment one is not,
it needs a different justification than this document provides.

## Customer portal — proposed

Served by the product's own API with the customer's token, gated by permission
**and** entitlement.

| Surface | Permission | Entitlement | Story |
|---------|-----------|-------------|-------|
| Audit history, filtered | `audit.view` | `audit.view` | AUDIT-005, 006 |
| Security-classified rows | owner/administrator | as above | AUDIT-015 |
| Export a scope | `audit.export` | `audit.export` | AUDIT-011 |
| My retention policy | `audit.view` | — | AUDIT-018 |
| Holds affecting me | `audit.view` | `audit.legal_hold` | AUDIT-010 |

Four rules for that surface:

1. **Server-authorized.** The web tier renders a decision; it never makes one.
2. **404, not 403**, for a row the caller may not have, so list and URL agree and
   existence is not confirmed by a status code.
3. **Filters are declared and bound.** Anything undeclared is 422, and there is
   no free-text filter — the rule `koras-reporting` already enforces, and the
   reason is injection rather than tidiness.
4. **Refuse while the plan is unresolved.** Export follows the export rule, not
   the upload rule: a download leaves the product.

## Proposed permissions and entitlement codes

None of these exists in any catalogue as of 2026-09-16.

```
audit.view
audit.export
audit.extended_retention
audit.legal_hold
```

A permission must be added to **both** the TypeScript and Python mirrors in one
commit, with a role mapping, or the generator's structural test fails. An
entitlement code is Control Plane catalogue work, which this task must not do,
and which `FOLLOW_UPS.md` F3/F2b governs.

## Why the platform pulls

A product pushing to the platform needs a credential toward the platform, and
whether a product may hold one is exactly the open question in F3/F2b — the
risk being one product's CI holding write access to another product's registry
entry. The AI usage contract settled this on 2026-09-14 by having the platform
collect, and the reasoning transfers unchanged.
