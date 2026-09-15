# <FEATURE-ID> — Manual Test Results

A record of one executed run. Nothing here may be written that was not
observed.

| | |
|---|---|
| **Environment** | <name and URL> |
| **Build / commit** | <sha> |
| **Run date** | <YYYY-MM-DD> |
| **Executed by** | <tester> |
| **Guide version** | <manual-test-guide.md as of <sha>> |

## Summary

| Total | PASS | FAIL | BLOCKED |
|-------|------|------|---------|

BLOCKED is never counted as a pass.

## Results

### <TEST-CASE-ID> — <Objective>

| | |
|---|---|
| **Test case ID** | <TEST-CASE-ID> |
| **Objective** | <what this case proves> |
| **Priority** | <Critical / High / Medium / Low> |
| **Preconditions** | <state before step 1> |
| **Test data** | <accounts, records, values> |
| **Verdict** | **PASS** / **FAIL** / **BLOCKED** |

| Step | Action | Expected result | Actual result | Evidence |
|------|--------|-----------------|---------------|----------|
| 1 | <action> | <expected> | <what actually happened> | `screenshots/<TEST-CASE-ID>/step-01-<description>.png` |
| 2 | | | | |

**If BLOCKED — reason:** <why execution was impossible: environment, access, data, upstream failure. Required.>

---

## Defects raised

| # | Test case | Defect | Severity | Routed to |
|---|-----------|--------|----------|-----------|

## Re-verification after fixes

| Defect | Fixed in | Re-executed by | Date | Verdict |
|--------|----------|----------------|------|---------|

Re-verification is performed by the agent that found the defect, never by
whoever fixed it.
