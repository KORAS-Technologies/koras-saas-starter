# SAG-F2 — The audit event model

The canonical envelope, what is mandatory, what is refused, and where the
original proposal's fields went.

## The envelope as built

`python-packages/koras-audit`, shared by both profiles.

| Field | Type | Mandatory | Notes |
|-------|------|-----------|-------|
| `action` | text | yes | Dotted lower-case, and **must be registered** |
| `actor_id` | text | yes | The ZITADEL subject, or the literal `system` |
| `tenant_id` | uuid | yes | Must equal the sink's tenant, or the emit is refused |
| `target_type` | text | yes | What kind of thing was acted on |
| `target_id` | text | yes | Which one. `-` where there is not one yet |
| `outcome` | text | yes | `ok`, `denied`, `failed`, `pending` |
| `details` | jsonb | no | A small map. Defaults to empty |
| `classification` | text | derived | From the registry, never from the caller |
| `created_at` | timestamptz | derived | Defaults to now |
| `id` | uuid | derived | Generated |

## Where the proposed fields went

The original request listed a wider envelope. Each field was placed
deliberately, and three were declined:

| Proposed | Where it is | Why |
|----------|-------------|-----|
| `event_id` | `id` | Same thing, existing name |
| `event_type` | `action` | One concept; two names would diverge |
| `timestamp` | `created_at` | The schema's convention throughout |
| `environment` | not stored | Each environment is a separate database. A column would record what the connection already proves |
| `organization_id` | not stored on the row | Resolved from the tenant. Storing it freezes a mutable fact, the same reason it is absent from an object key |
| `product_id` | not stored | A deployment is one product; the platform attributes on collection |
| `tenant_id` | `tenant_id` | The boundary |
| `workspace_id` | not stored | The starter has no workspace below a tenant. Modelled on `files` and inert; adding it here before a product needs it would be a column nothing writes |
| `actor` | `actor_id` (+ `actor_display` declined) | A display name is a copy of data that changes. The subject resolves to a current name when read |
| `action` | `action` | — |
| `resource_type`, `resource_id` | `target_type`, `target_id` | Existing names |
| `result` | `outcome` | Existing name and vocabulary |
| `correlation_id`, `request_id` | `details` | Real and useful; not queried, so not columns |
| `source` | `details` | As above |
| `ip` / context | **declined by default** | Personal data with a retention cost, recorded only where a specific control needs it |
| `metadata` | `details` | Same thing |
| `classification` | `classification` | A column, because the sweep queries it |
| `retention_policy_id` | not stored | Retention is resolved from the class. A per-row policy id would cache an answer that goes stale when the floor changes |

The rule behind most of those rows: **a field becomes a column when something
queries it, and a detail when it is only ever read back.** Columns cost an index
decision and a migration; details cost nothing and cannot be filtered on.

## Validation

At construction, before anything reaches a database:

- **The action must match** `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$` — dotted,
  lower-case, at least two segments.
- **The action must be registered**, with a summary and a class. An undeclared
  action raises at recording rather than receiving a default.
- **A detail key that looks like a credential raises.**
- **A cross-tenant event is refused** by the sink rather than dropped.

## Redaction, and why it is refusal

`AuditEvent` raises if any detail key contains `token`, `secret`, `password`,
`key`, `credential` or `authorization`. It inspects **names, never values**.

Two consequences worth stating:

1. **It throws instead of masking.** A masked value is still a row that was
   built as though carrying a credential were reasonable. Refusing makes the
   call site change.
2. **`storage_key` contains `key` and is refused.** Every storage call site
   records `file_id` instead — which is the better identifier anyway, because an
   object key is half a signed URL and the file id is what a later question is
   actually about.

The rule is deliberately crude. It has false positives, `report_key` among them,
and the cost of those is a call site renaming a detail. The cost of the opposite
error is a credential in a table kept for three years.

## What must never be recorded

File contents, request or response bodies, tokens of any kind, passwords,
provider credentials, signed URLs, and personal data beyond the actor's subject.

## Sensitive data and personal data

The actor's subject is personal data, and it is the minimum the record cannot do
without. Everything else about a person — name, email, address — is resolved at
read time from the identity provider rather than copied into a row that outlives
it. That is the reason `actor_display` was declined.

## Schema versioning

There is no version field. The envelope is a frozen dataclass shared by both
profiles and shipped with the code that writes it, so a build cannot disagree
with itself, and the table's columns are the compatibility surface.

A field added later is additive with a default, the way `classification` was on
2026-09-16: old rows keep the default, which for that column was the value the
single retention number already meant. **Rows are not reclassified
retrospectively** — a row's class is what was true when it was recorded.

If an incompatible change is ever needed, it is a new table alongside, the way
the contract directory versions a `v2` beside `v1`.

## Idempotency

Recording is **not** idempotent, and does not need to be: a write happens once,
inside the request's own transaction, and a request retried by a client is a
second real attempt that deserves a second row. Two upload attempts are two
facts.

The sweeps that delete are naturally idempotent — `delete ... where created_at <
:before` — and the reconciliation sweep writes at most one row per tenant per
run.

## Ordering

Within one flush, events are written in emit order. Across requests, ordering is
`created_at`, which is the transaction's clock.

**No stronger guarantee is offered**, and none should be inferred: two events
recorded in the same second by different requests have no defined order between
them, and the table is not a stream. A consumer needing causal order should use
the correlation id in `details` rather than timestamps.

## Where rows are written from

| Writer | Context | Note |
|--------|---------|------|
| API routes | the request's tenant session | Buffered, flushed after the answer |
| Reporting worker | a tenant context entered from provisioning | Spells its own class literal |
| Reconciliation sweep | as above | The audit table admits an insert only for its own tenant |

The last two are the only cross-context writes, and they exist because the
insert policy is deliberately narrow: there is no provisioning insert policy, so
a sweep must become the tenant to record something about it.
