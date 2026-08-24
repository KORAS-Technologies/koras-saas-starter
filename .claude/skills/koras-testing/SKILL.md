---
name: koras-testing
description: Koras Testing guidance for Koras applications.
---

# Koras Testing

Use this skill when adding tests, defining verification strategy, or deciding whether a feature is complete.

## Testing Pyramid

Use the smallest test that gives useful confidence:

```text
unit -> integration/component -> E2E
```

Use Playwright for critical user journeys and browser integration, not for every pure function.

## Unit Tests

Use for deterministic logic, parsers, validators, transformations, business rules, and utilities.

## Integration Tests

Use for API/service/database/package boundaries where behavior depends on multiple units working together.

## Component Tests

Use when component behavior is complex enough to warrant isolated interaction verification.

## E2E / Playwright

Cover critical paths such as:

- authentication
- onboarding
- key create/edit/submit flows
- tenant-sensitive navigation/access
- billing/payment handoff where testable
- high-value regression paths

## Behavior over Implementation

Prefer assertions on observable outcomes. Avoid tests that only assert internal setter calls or implementation details.

## Required Failure Cases

Test important failures, not only the happy path:

- invalid input
- unauthorized access
- forbidden cross-tenant access
- server/network error
- duplicate action/idempotency where relevant
- empty state

## Stability

Avoid arbitrary sleeps. Wait for explicit UI/network conditions. Use stable semantic locators such as role/name/label rather than brittle DOM structure selectors.

## Completion

Run the repository-standard lint/typecheck/test/build commands and report which were actually executed. For user-facing features, execute the critical flow in a real browser and inspect console errors.
