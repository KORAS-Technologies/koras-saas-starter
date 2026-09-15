# <FEATURE-ID> — Manual Test Guide

Repeatable instructions. This document says how to run the cases; the results
of any particular run belong in `manual-test-results.md`.

## Prerequisites

- **Environment:** <name and URL>
- **Access required:** <roles, accounts>
- **Test data:** <fixtures, and how to create or reset them>

## Accounts

| Account | Tenant | Role | Purpose |
|---------|--------|------|---------|

## Test cases

### <TEST-CASE-ID> — <Objective>

| | |
|---|---|
| **Test case ID** | <TEST-CASE-ID> |
| **Objective** | <what this case proves> |
| **Priority** | Critical / High / Medium / Low |
| **Preconditions** | <state required before step 1> |
| **Test data** | <accounts, records, values> |

**Steps**

1. <action>
   **Expected:** <observable result>
2. <action>
   **Expected:** <observable result>

**Expected final result:** <the outcome that makes this case a pass>

**Evidence to capture:** `testing/manual/screenshots/<TEST-CASE-ID>/step-<nn>-<description>.png` for steps <which>.

---

<Repeat per case. Include the negative cases: unauthorized principal,
cross-tenant access, empty state and invalid input.>
