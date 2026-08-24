---
name: koras-multitenancy
description: Koras Multi-Tenancy guidance for Koras applications.
---

# Koras Multi-Tenancy

Use this skill whenever data or behavior is tenant/organization scoped.

## Security Model

Treat tenant isolation as a security boundary.

Typical context:

```text
principal
  -> organization
  -> tenant
  -> permission
  -> resource
```

## Trusted Tenant Context

Do not authorize access solely from a `tenant_id` supplied by the browser. Resolve or validate tenant context from trusted authentication/session/server-side membership information.

## Query Rules

For tenant-owned data:

- scope reads and writes by tenant
- ensure update/delete predicates include the correct tenant ownership boundary
- prevent cross-tenant object references
- review joins for accidental leakage
- avoid cache keys that omit tenant context

## APIs

Tenant context should be explicit in trusted service boundaries. If a route contains a tenant identifier, verify the caller's relationship to that tenant before use.

## Database

For new tenant-owned tables review:

- tenant ownership column
- foreign keys
- indexes beginning with or including tenant key where query patterns require
- RLS/policies
- uniqueness constraints that should be tenant-scoped
- audit columns

## Background Jobs

Jobs must carry an explicit trusted tenant context and avoid processing mixed-tenant data without deliberate partitioning.

## Storage

Object paths/buckets alone are not authorization. Enforce tenant access using trusted server logic and/or storage policies.

## Logging

Include tenant identifiers in relevant audit/diagnostic events when safe, but do not log sensitive tenant data unnecessarily.

## Fail Closed

If tenant context is missing, ambiguous, or inconsistent, reject the operation rather than choosing a default tenant.
