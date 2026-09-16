# SAG-F2 — Retention, feature notes

> The policy itself — precedence, defaults, overrides, and which half is built —
> is `docs/RETENTION_POLICY.md`, which covers both features and is not
> duplicated here. This file carries only what is specific to audit records.
> Status 2026-09-16.

## What is built

Four classes, three settings, one nightly sweep in one transaction.

| Class | Setting | Default |
|-------|---------|---------|
| `activity` | `AUDIT_ACTIVITY_RETENTION_DAYS` | 90 days |
| `audit` | `AUDIT_RETENTION_DAYS` | 365 days |
| `administrative` | `AUDIT_RETENTION_DAYS` | 365 days |
| `security` | `AUDIT_SECURITY_RETENTION_DAYS` | 1095 days |

The assistant's own table is swept separately under
`AI_AUDIT_RETENTION_DAYS`, which is deliberate: `ai_audit_events` predates the
general table and keeps its own schedule.

## Why the class belongs to the action

The single most consequential decision in this feature, and the one that would be
easiest to get wrong later.

If a caller chose the class per call, the same action recorded from two routes
could be kept for two different times — and the one that mattered would be the
one somebody set to `activity` by accident. So the class is declared with the
action, once, in the registry, and the sink reads it from there. **A caller
cannot set it at all.**

The corollary: adding an action means deciding its retention. There is no
default, and an undeclared action raises rather than being recorded as
`audit`.

## Minimum and maximum

| | Value | Enforced |
|---|-------|----------|
| Minimum | 1 day, for every class | Yes — the sweep raises below it |
| Maximum | none | No |

There is no maximum because no regulatory requirement has named one, and a
ceiling nobody asked for would be a reason to delete evidence.

The minimum exists because **retention of nothing is a wipe**, and a
misconfigured environment variable is the most likely way that would happen.
The guard runs over every class before the first delete, so one bad number
cannot take the three that were right with it.

## Policy versioning

There is none, and the absence is deliberate.

A row's retention is resolved from its class at sweep time rather than stamped
on the row when it was written. So changing a class's retention changes it for
every row of that class, past and future, on the next night.

That is the right behaviour for a policy — a shortened retention should take
effect, not apply only to rows written after the change — but it has a sharp
edge worth stating: **shortening a retention deletes existing rows on the next
sweep.** There is no dry run and no warning. Anyone lowering one of the three
settings should expect the next night to remove everything that falls outside
the new window.

The alternative, a `retention_policy_id` per row, was declined because a row that
caches its own answer goes stale the moment the floor changes, and reconciling
stale rows against a new floor is a harder problem than the one it solves.

## Tenant and product overrides

Neither exists. The design is in `docs/RETENTION_POLICY.md`, and the rule that
governs it is that **a tenant may lengthen and may never shorten below the
platform floor** — which inverts the ordering the original request proposed, for
the reason given there.

## What retention does not do yet

| Missing | Consequence |
|---------|-------------|
| No hold check | AUDIT-009 cannot be called finished; the sweep would delete a record under investigation |
| No archive step | Rows go from the hot table to nothing |
| No alert if the sweep stops | The table grows and the counts are only in the log |

The first is the one that matters. See `legal-hold.md`, and specifically the
observation that a hold record nothing enforces is worse than no hold record.
