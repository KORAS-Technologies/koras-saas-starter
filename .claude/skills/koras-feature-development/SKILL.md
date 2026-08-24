---
name: koras-feature-development
description: Koras Feature Development guidance for Koras applications.
---

# Koras Feature Development

Use this skill for new features and meaningful behavior changes.

## Required Flow

### 1. Discover

Search first for:

- similar features
- relevant routes/pages
- reusable UI
- hooks
- schemas
- API clients
- services
- auth/permission helpers
- tenant-context helpers
- tests
- documentation

### 2. Define Impact

Identify:

- acceptance criteria
- affected apps/packages/services
- API changes
- database/migration impact
- auth/permission impact
- tenant-isolation impact
- UI states
- telemetry/audit impact
- tests required

### 3. Plan

For a non-trivial feature, write a concise implementation plan before editing. Prefer a small number of coherent steps.

### 4. Implement

- Keep the change scoped.
- Reuse existing conventions.
- Avoid unrelated refactors.
- Add explicit error handling.
- Add validation at trust boundaries.
- Preserve compatibility unless the task explicitly requires a breaking change.

### 5. Required User-Facing States

Consider all applicable states:

```text
loading
empty
success
error
validation error
unauthenticated
unauthorized/forbidden
disabled
submitting
retry/recovery
```

### 6. Verify

Run repository-standard lint, typecheck, test, and build scripts. For user-facing flows, run Playwright against the critical path, inspect the browser console, and verify at least one desktop and one mobile viewport.

### 7. Review

Review the final diff for:

- correctness
- architecture
- React/Next.js quality
- security
- tenant isolation
- accessibility
- performance
- duplication
- tests
- unrelated changes

### 8. Document

Update feature/package documentation if behavior, configuration, public APIs, setup, or operator workflows changed.
