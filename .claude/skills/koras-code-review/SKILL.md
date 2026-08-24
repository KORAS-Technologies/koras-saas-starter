---
name: koras-code-review
description: Koras Code Review guidance for Koras applications.
---

# Koras Code Review

Use this skill for final diff review or pull-request review.

## Scope

Review changed code first. Read surrounding code only as needed to understand behavior and established patterns.

## Categories

Review for:

1. correctness
2. architecture and dependency direction
3. React/Next.js quality
4. TypeScript/type safety
5. security
6. authentication/authorization
7. tenant isolation
8. performance
9. accessibility
10. UX/error states
11. testing quality
12. duplication/maintainability
13. observability
14. unintended or unrelated changes

## Severity

Use:

```text
CRITICAL
HIGH
MEDIUM
LOW
```

For each finding include:

- file/location
- problem
- impact
- concrete recommended fix

Do not invent findings to fill categories. If no issues are found, say so and describe residual test/risk gaps.

## React Review Prompts

Check for:

- unnecessary client components
- unnecessary `useEffect`
- duplicated derived state
- request waterfalls
- heavy bundle imports
- unstable keys
- broad rerender triggers
- excessively boolean-driven component APIs
- duplicated UI primitives

## Security Review Prompts

Search changed code for:

- raw authorization decisions in client-only code
- untrusted tenant IDs
- unsafe redirects
- privileged secrets exposed to client
- unsafe HTML rendering
- unvalidated uploads/paths
- raw SQL or unsafe query construction
- missing webhook verification
- sensitive logging

## Completion Gate

Do not approve completion while unresolved CRITICAL or HIGH findings remain.
