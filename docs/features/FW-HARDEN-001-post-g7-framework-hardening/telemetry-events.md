# FW-HARDEN-001 — telemetry event log

Append-only, per `.claude/orchestration/telemetry.yaml`. An event is written
when it occurs and is never edited afterwards; a correction is an amendment
below, naming what it corrects. The summary in `release/telemetry-summary.md`
is derived from this file, finalised immediately before closure, and is not the
record.

**Honest limitation, stated once and for the same reason G7 R2 stated it.** The
first three events occurred before this log existed — the safety snapshot, the
reading of the G7 R2 evidence and the two reproductions all happened while the
cycle had no identifier and therefore no directory. They are appended in the
order they occurred, and their `at` is the time they were appended, marked as
such. Everything from event 4 onward carries its real occurrence time.

All times 2026-09-21.

## Events

| # | event | subject | outcome | at | source |
|---|-------|---------|---------|----|--------|
| 1 | lifecycle_state_reached | safety snapshot | branch develop, HEAD 7199f85 = origin/develop, 0/0, tree clean, 2 pre-existing worktrees | 15:25Z (appended; occurred earlier) | `git status`, `git worktree list` |
| 2 | gate_executed | FW-DEF-002 reproduction | 41 failed, 458 passed (499) in a CRLF worktree of 7199f85 — the same count G7 R2 recorded | 15:29Z (appended; occurred earlier) | `testing/runs/2026-09-21-01/` |
| 3 | gate_executed | FW-GAP-006 reproduction | every factory-resident product path classified null; 4 needed gates reusable | 15:45Z (appended; occurred earlier) | `testing/runs/2026-09-21-01/` |
| 4 | mode_selected | FW-HARDEN-001 | STANDARD, by rule `any_elevating_signal` — `cross_feature_convergence` fired | 15:52Z | `execution-plan.md` |
| 5 | agent_invoked | impact-analysis | 3 findings scoped; 2 adjacent holes found and deliberately excluded | 15:52Z | `design/technical-design.md` |
| 6 | gate_executed | impact_analyzed | PASS | 15:52Z | `design/technical-design.md` |
| 7 | gate_executed | requirements_ready | PASS | 15:53Z | `requirements/user-story.md` |
| 8 | gate_executed | architecture_ready | PASS — the path-domain decision, with the rejected alternative recorded | 15:54Z | `design/technical-design.md` |
| 9 | lifecycle_state_reached | worktree standard | DEVIATION — the repository's write guard refuses file-tool edits outside the project root, so the isolated worktree could not be used for implementation. See the amendment below. | 15:58Z | this log |
| 10 | agent_invoked | unit-test | the frontmatter parser, the classifier matrix, the lifecycle assertions | 16:00Z | `generators/create-koras-app/tests/orchestration.test.ts` |
| 11 | gate_executed | implementation_complete | PASS — 552 passing, up from 499 | 16:04Z | commit `575acaf` |
| 12 | gate_executed | mutation proof, round 1 | PASS — 16 of 16 mutations killed by a named assertion | 16:05Z | `testing/runs/2026-09-21-02/` |
| 13 | gate_executed | automated_tests_pass | FAIL — attempt 1: 5 documentation-gate failures in this cycle's own evidence | 16:05Z | `testing/automated-test-results.md` |
| 14 | loop_iteration | test_fix_cycle 1 | example paths moved into fenced blocks; two hedges dated | 16:06Z | `testing/automated-test-results.md` |
| 15 | gate_executed | automated_tests_pass | PASS — attempt 2: 2346 generator, 424 docs, 120 CLI, 21 e2e, 7 pytest | 16:12Z | `testing/automated-test-results.md` |
| 16 | lifecycle_state_reached | code_freeze | declared at `575acaf` | 16:14Z | `git log` |
| 17 | gate_executed | FW-DEF-002 Windows proof | PASS — 552 of 552 in a fresh CRLF checkout of `575acaf`, where 7199f85 failed 41 | 16:19Z | `testing/runs/2026-09-21-03/` |
| 18 | agent_invoked | code-reviewer | independent, did not write the code — 3 HIGH, 4 MEDIUM, 5 LOW | 16:25Z | the independent review record beside this file |
| 19 | gate_executed | independent_code_review | **BLOCK** | 16:25Z | the independent review record beside this file |
| 20 | gate_executed | FW-DEF-002 Windows proof, whole generator suite | PASS — 61 files, 2244 tests, fresh CRLF checkout. Refutes review finding HIGH-2. | 16:28Z | `testing/runs/2026-09-21-03/` |
| 21 | loop_iteration | remediation cycle 1 | 3 HIGH: 1 refuted with measurement, 2 fixed. 4 MEDIUM and 5 LOW: all addressed. | 16:33Z | the independent review record beside this file |
| 22 | gate_executed | mutation proof, round 2 | PASS — 22 of 22, including one mutation per review finding | 16:40Z | `testing/runs/2026-09-21-02/` |
| 23 | gate_executed | implementation_complete | PASS — 557 passing after remediation | 16:41Z | `testing/automated-test-results.md` |

## Amendments

Per `telemetry.yaml`, a correction is a new record naming what it corrects. The
wrong value stays visible above.

| # | at | amends | previous value | corrected value | reason | evidence |
|---|----|--------|----------------|-----------------|--------|----------|
| A1 | 16:33Z | event 11, and the design document it produced | "the class is confined to one file" | the class is confined to one file, and two apparent counter-examples are not | The review read two further `\n\n` regexes over source-tree files and called the claim false. Both files define their own reader that strips carriage returns, each with a comment recording that this defect bit them once already. | event 20 — the whole generator suite green on CRLF |
| A2 | 16:33Z | event 11 | the FW-GAP-010 fix is not circular | the first fix WAS circular, and was corrected | Finalising the summary *at* CLOSED while CLOSED required a finalised summary rebuilt the deadlock one step on. Caught by the review of the fix, not by the fix. | review HIGH-1; mutation M20 |
| A3 | 16:33Z | event 11 | "zero unclassified" | 19 unclassified in three declared groups, zero under any application directory | The original measurement covered six chosen roots, not the tree. 42 tracked files matched nothing, against a contract block claiming two. | review MEDIUM-4; mutations M17, M18 |
| A4 | 15:58Z | event 9 | the framework mandates an isolated worktree, and one was created | one was created and then abandoned | The repository's `validate-write-safety` hook refuses file-tool writes outside the project root, so no edit could be made in it. Implementation ran on a feature branch in the main checkout instead; a separate worktree carried the CRLF proof, which is the part the standard's value actually rests on here. Recorded as a deviation rather than presented as compliance. | events 17 and 20 |
