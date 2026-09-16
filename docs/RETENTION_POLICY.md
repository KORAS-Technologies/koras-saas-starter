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

## Object retention — designed

The columns `00018_files_governance.sql` added are the contract; the engine that
would drive them has not been written as of 2026-09-16.

`retain_until` null means **no policy has been resolved for this object**, which
is not the same as expired. A sweep must treat null as not-yet-eligible rather
than as due. Getting that backwards would delete every object nobody has
classified.

`retention_policy` names a rule resolved in code rather than stored per row,
because precedence is a rule and not a column: a row that cached its own answer
would go stale the moment the platform floor changed.

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

## Legal hold — designed

A hold prevents archival, purge and deletion for everything in its scope,
whatever the dates say. The intended record carries a scope, a reason, who
requested it, who approved it, a start and an optional end, and a status.

Three properties that matter more than the schema:

1. **Placing and lifting a hold are both audited**, and lifting is the dangerous
   one: it is what makes a purge possible again, so it needs an owner or
   administrator.
2. **The sweep's query must exclude held rows**, and a qualified delete needs a
   select policy as well as a delete policy — the lesson migration
   `00008_ai_retention.sql` records, restated in 00009 and 00013.
3. A hold on a row a tenant cannot see is not a hold. The isolation test
   `supabase/tests/170_files_governance_isolation.sql` already proves a tenant
   cannot lift another tenant's hold or shorten another tenant's retention,
   which is the property the engine will depend on.

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
is the whole point of the floor.

## What is deliberately not here

**Per-period quotas.** The storage limit is a ceiling in gigabytes on a plan
grant, not a quota with a period, because the platform's quota mechanism needs a
period and storage has none. `FOLLOW_UPS.md` F22 records this.

**Automatic deletion of reconciliation findings.** The sweep reports orphans and
removes nothing; deciding to delete is a later decision with a person behind it.
