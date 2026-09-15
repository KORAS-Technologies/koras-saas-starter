# /manual-test-doc

Produce the manual test evidence package for a feature, in two stages.

**Stage 1 — `manual-qa` executes.** Run the approved manual cases against a real, running, identified environment. Record the environment, the build or commit under test, and the account and tenant used. For each case record expected result and actual result separately, and a verdict of PASS, FAIL or BLOCKED. Capture screenshots from the actual executed steps at:

```text
docs/features/<feature-id>-<slug>/testing/manual/screenshots/<test-case-id>/step-<nn>-<description>.png
```

If the environment is unavailable or access is missing, mark the affected cases **BLOCKED** with the reason documented. Never fabricate a screenshot, never record a PASS for a case that was not executed, and never change code or data to turn a FAIL into a PASS.

**Stage 2 — `test-documentation` writes it up.** From the evidence Manual QA actually produced, write `testing/manual/manual-test-guide.md` (repeatable instructions) and `testing/manual/manual-test-results.md` (the record of this run). Every case carries: test case ID, objective, priority, preconditions, test data, numbered steps, expected result, actual result, PASS/FAIL/BLOCKED, and its evidence reference.

Follow `.claude/orchestration/documentation-policy.yaml`, which is authoritative for paths and naming. Hand the result to `qa-reviewer` for an independent evidence audit.

Target:
```text
$ARGUMENTS
```
