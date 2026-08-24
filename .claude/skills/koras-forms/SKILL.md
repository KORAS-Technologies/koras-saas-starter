---
name: koras-forms
description: Koras Forms guidance for Koras applications.
---

# Koras Forms

Use this skill for React forms, validation, editable workflows, and form-state problems.

## Preferred Stack

Use the repository-standard form stack. When available, prefer:

```text
React Hook Form + Zod + shared schema
```

## Schema Ownership

If validation represents a business rule used across boundaries, place it in the shared validation layer and use it server-side as well as client-side where practical.

## Required Behaviors

Explicitly handle:

- default values
- edit-mode initial values
- async defaults if applicable
- dirty state
- reset/cancel
- client validation
- server validation
- submit loading state
- duplicate-submit protection
- successful submit state
- server/network error state
- unsaved changes behavior where material

## Field Requirements

Each field should have:

- programmatic label
- input/control
- optional help text
- validation message
- `aria-invalid` when invalid
- `aria-describedby` when help/error text is present

## State Rules

Do not mirror every form value into local `useState`. Avoid competing sources of truth between React Hook Form and component state.

Use `watch`/`useWatch` only for values that genuinely influence rendering or behavior. Avoid broad watching that rerenders an entire form unnecessarily.

## Server Trust Boundary

Client validation improves UX but is not authoritative. Revalidate server-side before trusted writes or privileged operations.

## Dynamic Forms

For conditional fields:

- define what happens to hidden values
- unregister or preserve intentionally
- validate only applicable business rules
- ensure dependencies are testable

## Destructive or Financial Actions

Provide stronger confirmation and duplicate-submit protection where appropriate.
