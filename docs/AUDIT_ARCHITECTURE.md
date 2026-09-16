# Koras Audit Architecture

> What a generated product records about what people did, how long each kind of
> record is kept, and what stops the audit table becoming the log.
>
> The decision record is `docs/adr/0003-koras-storage-audit-governance.md`.
> The storage half is `docs/STORAGE_ARCHITECTURE.md`; retention rules and holds
> are `docs/RETENTION_POLICY.md`.

## Purpose

An audit record exists so that a question asked later — by a customer, an
auditor, or someone working out what happened — has an answer that does not
depend on a log pipeline still holding last quarter.

That purpose implies its own constraints. A record kept for years and read by
more people than the data it describes must carry no secret, no token and no
content. And a table that everything writes to indiscriminately is a log with a
slower query planner.

## Audit, activity, and everything that is not either

The rule that keeps this table useful:

> **An event is a row here only when somebody may later have to prove it
> happened.** Everything else is a log line.

| Kind | Where it goes | Kept | Visible to the tenant |
|------|---------------|------|-----------------------|
| **Audit event** | `audit_events`, class `audit` | a year | yes |
| **Activity event** | `audit_events`, class `activity` | ninety days | yes |
| **Security event** | `audit_events`, class `security` | three years | owners and administrators |
| **Administrative event** | `audit_events`, class `administrative` | a year | yes |
| **Application event** | structured log to Loki | days | no |
| **Operational log** | stdout, traces to Tempo | days | no |

The four classes are not decoration. They exist because one retention number
governed the whole table until 2026-09-16, and one number is simultaneously too
long for "somebody opened a file" and too short for "somebody was refused one".

## The envelope

`python-packages/koras-audit` owns the shape, and both profiles share it. An
`AuditEvent` names an action, an actor, a tenant, a target and an outcome, and
carries a small mapping of details.

**A refusal is as much a fact as a success.** The outcome vocabulary is `ok`,
`denied`, `failed` and `pending`, and the routes record denials as firmly as
they record what went through. An operation that leaves no record when it fails
is the one worth recording.

### Redaction is refusal, not masking

`AuditEvent` raises if any detail key contains `token`, `secret`, `password`,
`key`, `credential` or `authorization`. It inspects names, never values, and it
throws rather than starring anything out — a masked value in an audit row is
still a row that was built as though carrying a credential were reasonable.

One consequence is load-bearing and catches everybody once: **`storage_key`
contains `key` and is refused.** Every storage call site records `file_id`
instead, which is also the better identifier — an object key is half a signed
URL, and the file id is what a later question is actually asked about.

## The action registry

The classification belongs to the **action**, not to the call site. The same
action recorded from two routes must be kept for the same time, and a caller
choosing per call is how a security event ends up swept on the activity
schedule.

So actions are declared, in the shape `koras-reporting` uses for reports:

- a key must be dotted lower-case, and must carry a summary;
- a duplicate key is refused at import, where it is a traceback with a stack
  rather than a 500 for a customer;
- iteration is ordered, so two runs of one build agree;
- **an action nobody declared is refused at the point of recording**, rather
  than given a default class. A default is the silent version of the same
  mistake.

Storage registers eight actions in the foundation. Reporting registers six in
the capability that emits them, so a product generated without reporting
declares none of them and its sweep never looks for them.

| Action | Class |
|--------|-------|
| `storage.object.uploaded` | audit |
| `storage.object.downloaded` | activity |
| `storage.object.deleted` | audit |
| `storage.object.delete_refused` | security |
| `storage.object.quarantined` | security |
| `storage.upload.refused` | security |
| `storage.upload.failed` | audit |
| `storage.reconcile.orphan_found` | audit |
| `report.viewed` | activity |
| `report.exported` | audit |
| `report.export_failed` | audit |
| `report.scheduled` | administrative |
| `report.schedule_removed` | administrative |
| `report.delivered` | audit |

A download is activity because it is noise a month later; a refusal is security
because it is the thing somebody asks about two years later. An export is audit
rather than activity because a copy of the rows left the product.

## The table

`public.audit_events`, created by `00013_audit_events.sql` and classified by
`00019_audit_classification.sql`.

**It is foundation, not a capability.** It shipped inside `reporting` until
2026-09-15, which meant a product generated without reporting had nowhere to
record. A general audit table that an unrelated capability can remove is not
somewhere another module can safely record.

Row-level security is enabled **and forced**, and the policies that are *absent*
are the design:

| Verb | Tenant | Provisioning |
|------|--------|--------------|
| select | own tenant | yes, for the sweep and the platform aggregate |
| insert | own tenant | no |
| update | **nobody** | **nobody** |
| delete | **nobody** | yes, the sweep only |

An audit row that can be edited is not an audit row. A tenant cannot delete its
own history, and nothing but the retention sweep can delete anyone's.

**Nor does an erasure request reach it.** A data subject asking under GDPR
Article 17 has their content removed and every audit row about them kept, on
17(3)(b) and 17(3)(e) — decided 2026-09-16 as ADR 0003 decision 14, with the
reasoning and the two rejected alternatives in `docs/RETENTION_POLICY.md`.
That the table has no update policy is what makes the position cheap to hold:
there is no half-measure available in the schema, so pseudonymising had to be a
deliberate build rather than something a route could quietly do.

An export closes out the same way, for the same reason. The request records
`pending` because the row exists before the artifact does, and the result
arrives as a second event rather than as an edit to the first — an update
statement against `audit_events` finds no policy, touches zero rows, and
reports success.

## The write path

`services/api/koras_api/core/audit.py`. Events are buffered and flushed by the
route, after the answer and after a refusal alike — a sink that wrote
mid-request would leave the session in whatever state the write left it.

Two details that are easy to get wrong and are handled here once:

- An event whose tenant is not the session's tenant is **refused**, not dropped.
- The commit drops `app.tenant_id`, which is transaction-local, so the sink
  rebinds the tenant afterwards. A caller that kept using the session without
  that rebinding would find every later query matching nothing.

The classification is written from the registry, never from the caller.

The worker writes its own rows for scheduled delivery and for reconciliation
findings. The audit table admits an insert only for the tenant the row belongs
to, so a sweep running on the provisioning context leaves it, writes as that
tenant, and returns.

## Retention

`services/worker/koras_worker/tasks/audit_retention.py`, nightly, on the
provisioning context, which is the only context that reaches every tenant and is
transaction-local so a pooled connection cannot inherit it.

The sweep deletes by class and age together, in one transaction, so a sweep
interrupted half way leaves the table consistent with itself rather than with
two of four classes swept. `00019` adds the index that makes that one range scan
per class.

Settings: `AUDIT_RETENTION_DAYS` (a year, governing `audit` and
`administrative`), `AUDIT_ACTIVITY_RETENTION_DAYS` (ninety days) and
`AUDIT_SECURITY_RETENTION_DAYS` (three years).

**Retention of nothing is a wipe**, so a value below one day is refused — and
the guard runs over every class *before* the first delete, so a typo in one
number cannot wipe the three that were spelled correctly.

`docs/RETENTION_POLICY.md` carries the precedence rules and the interaction with
holds.

## The assistant's own table

`ai_audit_events` is column-for-column identical and predates the general table.
It stays separate: the assistant's records are swept on their own schedule under
`AI_AUDIT_RETENTION_DAYS`, and the Activity report reads both together. The
duplication is deliberate rather than accidental — 00013's own header calls
itself the second durable implementation of the same sink.

## What the platform sees

`GET /internal/platform/v1/activity` answers events and distinct actors per
tenant, day, action and outcome, for up to 92 days. **Counts only**: no actor
ids, no targets, no details. Machine identity only, on the private contract.

The Control Plane's hourly collector keeps daily rows per organization for its
Usage and Adoption report. A product's audit rows never leave the product.

## What a customer can read today

The Activity report, through the reporting capability, reading `audit_events`
and `ai_audit_events` together.

**Filtered audit search and audit export were built on 2026-09-16.**
`GET /audit` with typed bound filters, `POST /audit/exports` for a CSV, JSON or
NDJSON artifact, and the Audit page in the shell. `audit.view` and
`audit.export` are the permissions, the second held by owners and
administrators alone: reading the history inside the product and taking a copy
out of it are different authorities. The audit governance capability itself is
still undeclared as of 2026-09-16 -- the code ships in the foundation, so every
product has it, and gating it is the next decision rather than a missing
feature.

## Testing

| Claim | Where |
|-------|-------|
| The registry refuses duplicates and undeclared actions | `tests/unit/test_audit_actions.py` |
| Each class is swept at its own age, and a bad number deletes nothing | `tests/unit/test_audit_retention.py` |
| Storage records what it did, and never a key-shaped detail | `tests/unit/test_storage_audit.py` |
| A tenant sees only its own rows, and cannot rewrite or delete them | `supabase/tests/110_audit_isolation.sql` |
| The sweep removes only what is old enough | `supabase/tests/110_audit_isolation.sql` |

**Not covered as of 2026-09-16:** the reconciliation sweep's own audit write —
it switches from the provisioning context into a tenant's to insert, and no
isolation test exercises that writer under the restricted role.
