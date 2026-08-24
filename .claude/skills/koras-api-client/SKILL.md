---
name: koras-api-client
description: Koras API Client guidance for Koras applications.
---

# Koras API Client

Use this skill when frontend or server code communicates with internal or external APIs.

## Goal

Centralize transport concerns and expose typed domain-oriented operations instead of scattering raw HTTP calls across UI components.

## Preferred Shape

Follow the repository convention. A typical organization is:

```text
packages/api-client/
  users.ts
  tenants.ts
  documents.ts
  billing.ts
```

Expose operations such as:

```text
list
get
create
update
remove
```

rather than requiring each caller to understand URLs and transport details.

## Client Responsibilities

Where applicable, centralize:

- base URL resolution
- authentication headers
- request IDs/correlation IDs
- content negotiation
- request serialization
- response parsing
- runtime validation for untrusted payloads
- timeout handling
- normalized error objects
- safe retry policy
- cancellation/AbortSignal support

## Retry Rules

Do not blindly retry non-idempotent operations. Retry only when semantics are safe and the failure class is appropriate. Honor rate-limit/retry headers when supported.

## Error Rules

Do not leak raw upstream secrets or sensitive response bodies into user-visible errors or logs. Preserve enough structured information for observability and UI behavior.

## Frontend Rules

Avoid raw `fetch()` repeated across presentational components when a shared client exists. Keep privileged credentials and server-only upstream calls on trusted server boundaries.

## Type Rules

Do not assume TypeScript types validate runtime data. Validate untrusted external responses when correctness/security requires it.
