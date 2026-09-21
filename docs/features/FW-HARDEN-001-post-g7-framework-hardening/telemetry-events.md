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
| 24 | gate_executed | automated_tests_pass | PASS — 2351 generator, 445 docs, 120 CLI, 21 e2e, 7 pytest. The generator figure moved from 2346 at event 15 because the remediation added assertions; both are measurements of their own moment. | 16:45Z | `testing/automated-test-results.md` |
| 25 | gate_executed | FW-DEF-002 Windows proof, at the remediated commit | PASS — 557 of 557 in a fresh CRLF checkout of `939fdd5`. Needed because `939fdd5` changed the parser regex itself, so the proof at `575acaf` no longer covered the tree being accepted. | 17:05Z | `testing/runs/2026-09-21-03/` |
| 26 | agent_invoked | final-acceptance | independent, neither wrote nor reviewed the code — 1 HIGH, 2 MEDIUM, 1 LOW | 17:30Z | the final-acceptance record beside this file |
| 27 | gate_executed | final_acceptance | **FAIL** — 26 product files lost 11 gates to the build-graph globs, and the regression document asserted the opposite | 17:30Z | the final-acceptance record beside this file |
| 28 | loop_iteration | remediation cycle 2 | build-graph globs anchored at the root; a class-movement invariant added; FW-GAP-013 row written; three numbers recounted; the Windows artefact corrected | 17:45Z | the final-acceptance record beside this file |
| 29 | gate_executed | mutation proof, round 3 | PASS — 23 of 23, M23 reproducing the acceptance finding | 17:50Z | `testing/runs/2026-09-21-02/` |
| 30 | gate_executed | automated_tests_pass | PARTIAL — lint, typecheck, docs (448), CLI (120), e2e (21), pytest (7) all pass; the generator suite reports 2344 passed, 8 skipped, one 120s hook timeout under parallel load | 18:10Z | `testing/automated-test-results.md` |
| 31 | gate_executed | product-governance in isolation | PASS — 25 of 25 in 30s, which identifies the timeout as load rather than defect | 18:07Z | `testing/automated-test-results.md` |
| 32 | budget_cap_reached | elapsed time | the repository owner stopped a further confirmation run of the generator suite, on the ground that it would only re-confirm what G7 R2 already recorded about this flake | 18:25Z | this session |
| 33 | escalation_raised | FW-DEF-003 | recorded rather than fixed — a pre-existing environmental flake, not caused by this cycle | 18:25Z | `docs/platform/gap-defect-register.md` |
| 34 | human_gate_reached | merge_to_protected_branch | AWAITING DECISION | 18:30Z | this session |

## Amendments

Per `telemetry.yaml`, a correction is a new record naming what it corrects. The
wrong value stays visible above.

Ordered by when the amendment was **made**, which is monotonic, not by when
the event it corrects occurred. A4 is the one where those differ, and it says
so. Final acceptance caught this table out of order in its first arrangement,
which is a fair thing to catch in the one table whose whole value is order.

| # | at | amends | previous value | corrected value | reason | evidence |
|---|----|--------|----------------|-----------------|--------|----------|
| A1 | 16:33Z | event 11, and the design document it produced | "the class is confined to one file" | the class is confined to one file, and two apparent counter-examples are not | The review read two further `\n\n` regexes over source-tree files and called the claim false. Both files define their own reader that strips carriage returns, each with a comment recording that this defect bit them once already. | event 20 — the whole generator suite green on CRLF |
| A2 | 16:33Z | event 11 | the FW-GAP-010 fix is not circular | the first fix WAS circular, and was corrected | Finalising the summary *at* CLOSED while CLOSED required a finalised summary rebuilt the deadlock one step on. Caught by the review of the fix, not by the fix. | review HIGH-1; mutation M20 |
| A3 | 16:33Z | event 11 | "zero unclassified" | 19 unclassified in three declared groups, zero under any application directory | The original measurement covered six chosen roots, not the tree. 42 tracked files matched nothing, against a contract block claiming two. | review MEDIUM-4; mutations M17, M18 |
| A4 | 16:33Z | event 9, which occurred at 15:58Z | the framework mandates an isolated worktree, and one was created | one was created and then abandoned | The repository's `validate-write-safety` hook refuses file-tool writes outside the project root, so no edit could be made in it. Implementation ran on a feature branch in the main checkout instead; a separate worktree carried the CRLF proof, which is the part the standard's value actually rests on here. Recorded as a deviation rather than presented as compliance. | events 17 and 20 |
| A5 | 17:45Z | event 11, and the regression document it produced | "the class of exactly zero real files changed" and "nothing moved out of another class" | 26 files moved from `frontend_code` to `deployment_config`, losing 11 gates each | The build-graph globs were written with a leading globstar and reached into every package. Found by final acceptance measuring class movement; the document had asserted it without measuring. | the final-acceptance record beside this file; mutation M23 |

## Events, continued

| # | event | subject | outcome | at | source |
|---|-------|---------|---------|----|--------|
| 35 | agent_invoked | final-acceptance | attempt 2, independent, against `bc3ddac` | 18:40Z | the final-acceptance record beside this file |
| 36 | gate_executed | final_acceptance | **PASS** — 0 CRITICAL, 0 HIGH, 0 MEDIUM; 3 LOW, all documentation wording | 18:46Z | the final-acceptance record beside this file |
| 37 | loop_iteration | remediation cycle 3 | the three LOWs corrected: a scale label wrong in three places, a reassurance stronger than the evidence, and an amendment table out of order | 18:50Z | this log |
| 38 | human_gate_reached | merge_to_protected_branch | **APPROVED** by the repository owner | 23:10Z | this session |
| 39 | lifecycle_state_reached | merged | `62780bc`, --no-ff into develop, content identical to the accepted branch | 23:11Z | `git log` |
| 40 | gate_executed | ci_verified | PASS — CI 35666451350, attempt 1, 7m57s, on `62780bc` | 23:20Z | GitHub Actions |
| 41 | gate_executed | security | PASS — Security 35666451418, attempt 1, 1m59s | 23:14Z | GitHub Actions |
| 42 | gate_executed | generator_integration | PASS — Generator Integration 35666451341, attempt 1, 10m7s. FW-DEF-003 did not recur under CI load, and no PLAT-DEF-013 signature appeared. | 23:22Z | GitHub Actions |
| 43 | lifecycle_state_reached | summary finalised | the derived summary written, immediately before the closure transition and after every other event — the rule this cycle wrote, followed on its own run | 23:30Z | `release/telemetry-summary.md` |
| 44 | lifecycle_state_reached | CLOSED | every applicable state reached; no gate left FAIL, PENDING_HUMAN or PENDING_EXTERNAL; the summary finalised and agreeing with this log | 23:31Z | `.claude/orchestration/lifecycle.yaml` |
