# Koras Retention Policy

> How long a stored object and an audit record are kept, who may change that,
> and what stops anything being removed while it matters.
>
> The decision record is `docs/adr/0003-koras-storage-audit-governance.md`.
> The mechanisms are in `docs/STORAGE_ARCHITECTURE.md` and
> `docs/AUDIT_ARCHITECTURE.md`.

## What is built, and what is design

This document describes one rule set covering two subjects. They are at
different stages, and conflating them would be the kind of documentation defect
`RISK_REGISTER.md` R-042 is about.

| Subject | State as of 2026-09-16 |
|---------|------------------------|
| Audit retention, per class | **Built.** Nightly sweep, four classes, three settings |
| Object retention columns | **Built.** `retain_until`, `retention_policy`, `legal_hold` on `files` |
| Object retention *engine* | **Built 2026-09-16.** A nightly sweep resolves a date, lengthens to a raised floor, and purges what has passed one |
| Legal hold enforcement | **Built 2026-09-16.** The sweep will not select a held row, and `DELETE /files/{id}` refuses one |
| Tenant retention overrides | **Built 2026-09-16.** Lengthening only, capped at ten years |
| Lifecycle transitions | **Designed, not built.** See the tiers below; WARM, COLD and ARCHIVE remain metadata with no physical effect |

So: both halves of this document now describe behaviour that can be observed,
except the storage tiers. Those stay designed because no provider in this
estate offers tiering and no bucket is provisioned for an archive -- a `tier`
column that nothing acts on would be the defect this work exists to close.

## Precedence

When several rules could decide how long something is kept, this order applies,
strongest first:

```
Legal hold
    >  Regulatory requirement
    >  Platform floor
    >  Product policy
    >  Tenant policy
```

**A tenant may lengthen retention and may not shorten it below the platform
floor.** This inverts the ordering the original request proposed, which put
tenant and product policy above the platform default. That ordering contradicts
the requirement in the same request that security and compliance minimums must
not be weakened by tenant configuration, and a tenant able to shorten their own
retention is a tenant able to erase their own audit trail before anyone reads
it. The decision was taken on 2026-09-15 and is ADR 0003 decision 10.

A hold outranks everything, including a regulatory expiry: a record under hold
is kept past the date it would otherwise have gone, because the hold exists
precisely for the case where somebody needs it after it would normally have been
forgotten.

## Audit retention

Four classes, three settings, one nightly sweep.

| Class | Setting | Default | Why |
|-------|---------|---------|-----|
| `activity` | `AUDIT_ACTIVITY_RETENTION_DAYS` | 90 days | The bulk of the rows, and the least of them worth a year |
| `audit` | `AUDIT_RETENTION_DAYS` | 365 days | Long enough to answer a question about last quarter |
| `administrative` | `AUDIT_RETENTION_DAYS` | 365 days | A configuration change is as durable a fact as an access |
| `security` | `AUDIT_SECURITY_RETENTION_DAYS` | 1095 days | The question asked about one of these is usually asked late |

The class belongs to the action rather than to the caller; see the action
registry in `docs/AUDIT_ARCHITECTURE.md`.

Two safety properties, both tested:

- **Retention of nothing is a wipe**, so any value below one day is refused.
- The guard runs over **every** class before the first delete, so a typo in one
  number cannot delete the three that were spelled correctly.

The sweep runs in one transaction on the provisioning context, so an
interruption leaves the table consistent with itself rather than with two of
four classes swept.

## Object retention

The columns `00018_files_governance.sql` added are the contract, and
`storage_lifecycle.py` is the engine that drives them as of 2026-09-16: a
nightly sweep that resolves a date for objects that have none, lengthens any
date that falls short of a raised floor, and removes what has passed one and no
hold is keeping. Off unless `STORAGE_LIFECYCLE_ENABLED` asks for it, because it
deletes.

### The floors

| Classification | Setting | Default | Why |
|----------------|---------|---------|-----|
| `standard` | `STORAGE_RETENTION_DAYS_STANDARD` | 1 day | The tenant's own policy decides; the floor only stops a retention of nothing |
| `sensitive` | `STORAGE_RETENTION_DAYS_SENSITIVE` | 3650 days | A classification a product sets deliberately, for content it has decided carries an obligation |
| `restricted` | `STORAGE_RETENTION_DAYS_RESTRICTED` | 3650 days | The same, and the narrower set |

**`standard` was 2555 — seven years — until 2026-09-16, and a tenant could not
shorten it.** That meant a customer who uploaded a document and wanted it gone
in ninety days could not have that. A floor over arbitrary customer content is
not a compliance control; it is a product refusing a deletion the customer is
entitled to ask for, which is the finding rather than the defence. The floor now
sits where the obligation sits. ADR 0003 decision 15.

Seven years was never derived from a regulation this product is subject to. It
is the common commercial middle — above the six-year limitation period for
contract claims in England and Wales, level with the Sarbanes-Oxley period for
audit records and with Dutch fiscal retention, below the ten years German
`HGB` §257 requires for books. Five years would have been defensible for
anti-money-laundering records, which is the regime that names five, and short
for anything a contract claim could reach in year six. That spread is the
argument for the floors being settings a product sets against its own
obligations rather than a number the factory is confident about.

`retain_until` null means **no policy has been resolved for this object**, which
is not the same as expired. A sweep must treat null as not-yet-eligible rather
than as due. Getting that backwards would delete every object nobody has
classified.

`retention_policy` names a rule resolved in code rather than stored per row,
because precedence is a rule and not a column: a row that cached its own answer
would go stale the moment the platform floor changed.

## Erasure requests

**A request under GDPR Article 17 removes a data subject's content and leaves
every audit row about them.** Decided 2026-09-16 as ADR 0003 decision 14, on
Article 17(3)(b) — processing necessary for compliance with a legal obligation
— and 17(3)(e) — the establishment, exercise or defence of legal claims.

Two alternatives were considered:

| Considered | Why not |
|------------|---------|
| Pseudonymise `actor_id` after a floor | Correlation across the remaining rows still identifies the person, so it buys little — and it destroys "who did this" for exactly the investigation the rows exist to support |
| Erase `activity`, refuse the other three | The more defensible answer, and recorded as a follow-up rather than built: it needs an erasure route, an audit row for the erasure itself, and a hold check, none of which should be improvised |

What the product does today is delete the content and refuse the history, and
a deletion refused by a hold says so with `file_under_hold` rather than failing
quietly.

## Lifecycle — designed

```
HOT  ->  WARM  ->  COLD  ->  ARCHIVE  ->  PURGE
```

Named as four tiers and, for the providers this estate uses, **implemented
honestly as two**:

| Tier | What it actually means here |
|------|------------------------------|
| HOT | The object in its normal bucket |
| WARM | Metadata only. No provider move |
| COLD | Metadata only. No provider move |
| ARCHIVE | A copy into a separate archive bucket |
| PURGE | Removal, and irreversible |

No provider in scope offers storage tiering — Supabase Storage has none, and R2
has no Glacier equivalent. Naming four tiers and implementing two is better than
implying a provider does something it does not. This was decided on 2026-09-15
as ADR 0003 decision 11.

PURGE is the only irreversible transition, and the one a hold blocks.

## Legal hold

A hold prevents archival, purge and deletion for everything in its scope,
whatever the dates say. The record carries a scope, a reason, who requested it,
who approved it, a start and an optional end, and a status. Migration
`00020_legal_holds.sql` is the table, `routers/holds.py` the four routes, and
`public.under_legal_hold(tenant, scope)` the single question every sweep asks —
one function rather than a condition repeated, so two sweeps cannot answer it
differently.

Three properties that matter more than the schema:

1. **Placing and lifting a hold are both audited**, and lifting is the dangerous
   one: it is what makes a purge possible again, so it needs an owner or
   administrator, and it needs someone other than the person who requested the
   hold. The same second-person rule approving takes rather than a stricter
   one, because a rule needing a third distinct person is unsatisfiable in a
   tenant with two administrators.
2. **The sweep's query must exclude held rows**, and a qualified delete needs a
   select policy as well as a delete policy — the lesson migration
   `00008_ai_retention.sql` records, restated in 00009 and 00013.
3. A hold on a row a tenant cannot see is not a hold. The isolation test
   `supabase/tests/170_files_governance_isolation.sql` already proves a tenant
   cannot lift another tenant's hold or shorten another tenant's retention,
   which is the property the engine depends on.

A bounded hold stops holding on the day its `ends_at` names — `under_legal_hold`
has always read it — and a nightly sweep closes the row out as `expired` so the
list stops showing holds that hold nothing.

## Configuration

```
Platform floor   in settings, and nothing below it
     |
Product policy   in the product's own configuration
     |
Tenant policy    in tenant settings, lengthening only
```

As of 2026-09-16 the platform and tenant levels exist: the platform floors as
the settings above, and the tenant level as `retention_overrides` on
`tenant_settings`, written through `PUT /retention` and resolved by
`public.retention_days_for`. A tenant may only lengthen, and never past ten
years. The product level -- a product's own configuration sitting between the
two -- is still the design.

Security and compliance minimums are not tenant-configurable at any level. That
is the whole point of the floor — and, since 2026-09-16, the reason the floor
over `standard` content is one day: a floor that is not protecting a minimum is
not a floor, it is a refusal to delete.

## What is deliberately not here

**Per-period quotas.** The storage limit is a ceiling in gigabytes on a plan
grant, not a quota with a period, because the platform's quota mechanism needs a
period and storage has none. `FOLLOW_UPS.md` F22 records this.

**Automatic deletion of reconciliation findings.** The sweep reports orphans and
removes nothing; deciding to delete is a later decision with a person behind it.
