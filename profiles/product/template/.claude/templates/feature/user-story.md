# <FEATURE-ID> — <Title>

## User story

As a <role>, I want <capability>, so that <outcome>.

## Business context

<Why this is worth building, and what happens if it is not.>

## In scope

- <behaviour>

## Explicitly out of scope

- <behaviour, and where it is tracked instead>

## Acceptance criteria

Each criterion must be independently verifiable by a tester.

| # | Criterion | Verified by |
|---|-----------|-------------|
| AC-1 | <observable behaviour> | <test case or suite> |

## Negative and edge cases

| # | Case | Expected behaviour |
|---|------|--------------------|
| AC-N1 | Unauthorized principal attempts the operation | <refused, with what response> |
| AC-N2 | Principal of another tenant attempts the operation | <not found or refused; never leaks existence> |
| AC-N3 | Empty state | <what the user sees> |
| AC-N4 | Invalid input | <validation behaviour> |

## Tenancy

<Which data is tenant-owned, and what cross-tenant behaviour must be impossible.>

## Entitlements and plan dependencies

<Any capability gated by a plan or entitlement, and where it is enforced server-side.>

## Open questions

| # | Question | Blocks | Owner |
|---|----------|--------|-------|
