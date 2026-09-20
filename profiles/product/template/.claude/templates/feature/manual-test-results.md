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

| Step | Action | Expected result | Actual result | Evidence | What it proves |
|------|--------|-----------------|---------------|----------|----------------|
| 1 | <action> | <expected> | <what actually happened> | `screenshots/<TEST-CASE-ID>/step-01-<description>.png` | <a phrase, where the capture's purpose is not obvious> |
| 2 | | | | | |

Not every step carries a screenshot. Capture where it proves something a
sentence could not — a starting state a later image needs, the transition
this case exists to show, a validation or error state with its actual
message, the final result, a permission boundary behaving as specified, or a
visual accessibility condition. Not navigation, and not a click whose only
outcome is the next screen. There is no maximum; a high-risk workflow may
justify a dozen. A capture whose purpose cannot be written in a phrase is one
that proves nothing.

**If BLOCKED — reason:** <why execution was impossible: environment, access, data, upstream failure. Required.>

---

## Raw runs

Each execution is appended at `testing/runs/<run-id>/` and is never edited
afterwards. This document points at the latest valid run; it does not replace
it, and a failed run stays where it is — it is the evidence that a defect
existed.

| Run | Commit | Result | Runs directory |
|-----|--------|--------|----------------|
| <YYYY-MM-DD>-01 | <sha> | <PASS / FAIL / BLOCKED> | `testing/runs/<run-id>/` |

## Defects raised

| # | Test case | Defect | Severity | Routed to |
|---|-----------|--------|----------|-----------|

## Re-verification after fixes

| Defect | Fixed in | Re-executed by | Date | Verdict |
|--------|----------|----------------|------|---------|

Re-verification is performed by the agent that found the defect, never by
whoever fixed it.
