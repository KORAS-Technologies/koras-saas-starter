# /manual-test-doc

Produce the manual test evidence package for a feature, in two stages.

**Stage 1 — `manual-qa` executes.** Run the approved manual cases against a real, running, identified environment. Record the environment, the build or commit under test, and the account and tenant used. For each case record expected result and actual result separately, and a verdict of PASS, FAIL or BLOCKED. Capture screenshots from the actual executed steps at:

```text
docs/features/<feature-id>-<slug>/testing/manual/screenshots/<test-case-id>/step-<nn>-<description>.png
```

**Capture where it proves something, not at every click.** A starting state a later image needs, the transition the case exists to show, a validation or error state with its actual message, the final result, a permission boundary behaving as specified, a visual accessibility condition. Not navigation, not a click whose only outcome is the next screen, and not the same state twice. There is no maximum — a high-risk workflow may justify a dozen — and where a capture's purpose is not obvious from the step, write in a phrase what it proves. One real feature produced about 164 screenshots for 20 cases, and the cost was not storage: a reviewer could not tell which images proved anything, so the evidence got skimmed.

Append each execution at `testing/runs/<run-id>/`, recording the command, the commit, the result, the timestamp and the environment. A run directory is written once and never edited. A failed run stays.

If the environment is unavailable or access is missing, mark the affected cases **BLOCKED** with the reason documented. Never fabricate a screenshot, never record a PASS for a case that was not executed, and never change code or data to turn a FAIL into a PASS.

**Stage 2 — `test-documentation` writes it up.** From the evidence Manual QA actually produced, write `testing/manual/manual-test-guide.md` (repeatable instructions) and `testing/manual/manual-test-results.md` (the record of this run). Every case carries: test case ID, objective, priority, preconditions, test data, numbered steps, expected result, actual result, PASS/FAIL/BLOCKED, and its evidence reference.

Follow `.claude/orchestration/documentation-policy.yaml`, which is authoritative for paths and naming. Hand the result to `qa-reviewer` for an independent evidence audit.

Target:
```text
$ARGUMENTS
```
