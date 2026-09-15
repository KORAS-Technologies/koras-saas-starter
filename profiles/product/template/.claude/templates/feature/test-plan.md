# <FEATURE-ID> — Test Plan

## Scope

<What is being verified, and what is deliberately not.>

## Traceability

| Acceptance criterion | Verification | Level |
|----------------------|--------------|-------|
| AC-1 | <case or suite> | unit / integration / e2e / manual |

Every criterion has at least one verification. A criterion with none is a gap,
not an omission.

## Test data

| Fixture | Purpose |
|---------|---------|
| Tenant A | Primary tenant |
| Tenant B | Exists so cross-tenant access can be tested negatively |
| Principal with no access | Refusal cases |

## Automated coverage

| Level | What it covers |
|-------|----------------|
| Unit | |
| API / integration | |
| E2E | |

## Manual coverage

<Cases that require a person, and why automation does not cover them.>

## Security cases

<Abuse cases from the threat model, where one exists.>

## Environment

<Which environment the manual and E2E runs require, and what access is needed.>

## Out of scope

<What this plan does not verify, and where that is covered instead.>
