# SAG-F2 — Configuration

Every setting audit reads, and what may override what. Status 2026-09-16.

## Inheritance

```
Platform floor      settings and code. Nothing goes below it
      |
Product policy      designed, not built
      |
Tenant policy       designed, not built. Lengthening only
```

Only the platform level exists. When the others are built the rule is that **a
tenant may lengthen retention and may never shorten it below the floor**, for
the reason argued in `docs/RETENTION_POLICY.md`.

## Settings

Declared in `local/config/secrets.manifest`. A setting not declared there is
never prompted for and never checked.

| Setting | Class | Default | What it does |
|---------|-------|---------|--------------|
| `AUDIT_RETENTION_DAYS` | optional | 365 | Governs the `audit` and `administrative` classes |
| `AUDIT_ACTIVITY_RETENTION_DAYS` | optional | 90 | The bulk of the rows |
| `AUDIT_SECURITY_RETENTION_DAYS` | optional | 1095 | Refusals and authorization decisions |
| `AI_AUDIT_RETENTION_DAYS` | optional | 365 | The assistant's own table, swept separately |

**Lowering any of the first three deletes existing rows on the next sweep.**
Retention is resolved at sweep time from the class, not stamped on the row when
it was written, so a change applies to history as well as to future rows. There
is no dry run. `retention-policy.md` explains why that is the right behaviour and
why it is still worth a warning.

## What is configured in code rather than in settings

| Thing | Where | Why not a setting |
|-------|-------|-------------------|
| Which actions exist | the registry, at import | An action is code; a duplicate must fail at import |
| Which class an action has | the registry | A caller choosing it per call is the failure mode the registry exists to prevent |
| Which classes exist | `Classification` | Adding one is a migration, because the column has a check constraint |
| The sweep's hour | `worker.py` cron | Staggered against the other sweeps |

## Capability

Audit is **foundation**. It is generated into every product and `--without`
removes none of it. That is the change made on 2026-09-15: the table shipped
inside `reporting` and a product generated without reporting had nowhere to
record.

Reporting still registers its own six actions, so a product without reporting
declares none of them and its sweep never looks for them.

The audit governance capability the plan named — search, export, holds, the
viewer — is **undeclared as of 2026-09-16**. When declared it is off by default.

## Per-tenant configuration

None exists. The only per-tenant input to audit today is which tenant a row
belongs to.

When tenant overrides are built, the two rules are: a tenant may only lengthen,
and a tenant may not reclassify an action, because classification drives
retention and reclassifying is shortening by another route.

## Not configurable, deliberately

| Thing | Why |
|-------|-----|
| Whether operations are audited | Auditing is not optional |
| Whether rows can be updated | There is no update policy. Adding one would end the table's usefulness |
| Whether the sweep runs | It runs. A product that wants longer retention raises the number |
| The minimum retention | One day, floor, enforced before any delete |
| Whether an undeclared action is allowed | It raises. A fallback would reintroduce the silent default |
