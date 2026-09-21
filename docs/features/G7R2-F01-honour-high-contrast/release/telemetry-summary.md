# G7R2-F01 — telemetry summary

Derived from `../telemetry-events.md` (50 events) and `../telemetry-amendments.md`
(5 amendments) on 2026-09-21, at closure.

**This is a reading of the record, not the record.** Where this file and the event log
disagree, the log wins. Counts come from events; a metric no event supports is `UNKNOWN`,
not `0`, because zero is a measurement and means the thing was watched for and did not
happen.

**When this file is written, and why that needed a ruling.** It is finalised **after**
final acceptance, as the last step of the lifecycle. An earlier version was written before
acceptance and was stale the moment acceptance ran — it reported zero escalations in a run
whose defining act was an escalation, which acceptance attempt 3 correctly refused to pass.
The contract cannot have it both ways: it requires the summary to come after the last
applicable gate event, and acceptance is a gate. That deadlock is FW-GAP-010, and the
repository owner ruled this document a closure artifact on 2026-09-21. The ruling is
recorded here because a reader who finds this file dated after the acceptance it
summarises should know it was meant to be.

## Routing

| | |
|---|---|
| execution_mode | **FAST** |
| risk_signals_fired | **0** — ten floor and eight elevating signals each walked and recorded as not fired |
| risk_signals_rejected | **3** named: `multi_step_user_workflow`, `security_boundary`, `architecture_impact` |
| mode_overridden_by_human | no |
| selection_rule | `no_signal_and_every_fast_requirement_holds` |

The mode was never revisited, and nothing found later contradicted it: the independent
review looked for security, tenancy, data and architecture concerns and found none.

## Agents

| | |
|---|---|
| agents_available | **40**, all discoverable in a fresh runtime |
| agents_invoked | **8** as separate processes: `product-planner`, `impact-analysis`, `ux-ui-designer` ×2, `developer-1`, `code-reviewer`, `qa-reviewer`, `final-acceptance` ×3 |
| agents_activated | **17** of 40 |
| agents_available_but_not_activated | **23** |
| invocations_per_agent | `final-acceptance` 3, `ux-ui-designer` 2, all others 1 |

23 of 40 available and not activated, and the review hunted specifically for work the
excluded agents would have found and found none.

## Gates

| | |
|---|---|
| gates_executed | **17** |
| gates_closed_owner_optional | **2** — `requirements_ready`, `architecture_ready`, seven fields each |
| gates_reused | **0** — no prior run existed to reuse from |
| gates_invalidated | **2** — `documentation_audit` and `final_acceptance`, by the post-audit documentation corrections |
| gates_not_applicable | **7**, each with the unmet condition named |
| gates_not_applicable_by_policy | **0** |
| gates_pending | **3** post-merge: `ci_verified`, and `deployment_preflight`/`environment_verified` which are NOT_APPLICABLE — the factory deploys nothing of its own |
| gates_closed_by_human_ruling | **1** — `final_acceptance`. Recorded distinctly, because a gate closed by a person is not the same evidence as one an agent returned READY on |

## Loops

| | |
|---|---|
| test_fix_cycles | **2 of 2** — the documentation-gate remediation, then FW-GAP-009 |
| reviewer_cycles | **1 of 2** — one review, PASS, no fix cycle, no re-review |
| documentation_audits | **1 of 1** |
| final_acceptance_attempts | **3** — two against a budget of 2, then one under a granted extension |
| retries | **1 of 1** — the suite re-run after the line-ending re-checkout, nothing changed |
| remediation_cycles | **2** |
| budget_caps_reached | **2** — `ux-ui-designer` at `same_agent_max_invocations`, and `max_final_acceptance_attempts` |
| human_escalations | **2** — both `budget_exhausted → HUMAN_REVIEW`, both answered by the owner with a recorded reason |

**The budget bound, twice, and both times the stop was a stop.** That is the number this
report exists to carry. A budget that never binds is a formality; this one halted the run
at the point where it had stopped converging on the record, and a person decided what
changed. Neither escalation was about the code.

## Lifecycle

| | |
|---|---|
| state_reached | `PLANNED` → `IMPLEMENTING` → `TESTING` → **`LOCAL_ACCEPTANCE_READY`** |
| freeze points | `code_freeze` at `e677b54`; `quality_freeze` at `e677b54` |
| states_not_applicable | `DEV_DEPLOYED`, `DEV_VERIFIED` — the factory has no environment of its own |
| states_outstanding | `MERGE_READY`, `MERGED`, `CI_VERIFIED` |
| deployment_components_by_state | **UNKNOWN** — no deployment applies and no event records a component state |

## Effort

| | |
|---|---|
| elapsed_time_if_available | **UNKNOWN.** No event records a duration. Timestamps could be subtracted, but an inferred figure is not a measurement, and this framework has already had one number written from a plan rather than from an event. |

## Amendments

Five, all appended, none an edit in place:

1. Two tokens from the G7 R2 brief were used to classify a probe result; neither is
   declared in this repository. Corrected to `SESSION_OR_TOOL_HEALTH`.
2. Event 17's pointer named a run directory holding no Playwright output. Corrected to
   the retained capture.
3. Events 14 and 16 named one file for two different runs, and the first run's output had
   not been retained at all. Both retained, both renamed.
4. Event 32 said the post-audit commit made no executable change. It changed a `.test.ts`.
5. The amendment at 19:40Z named event 33, which never carried the phrase it corrected.
   Corrected to event 32 — an amendment correcting an amendment.

**Four of the five are corrections to this run's own record rather than to the feature.**
That ratio is the most useful thing in this report: the framework's gates found almost
nothing wrong with two files of CSS and TypeScript, and found six things wrong with what
was written about them.

## What this summary cannot tell you

Whether the mode was right. That comparison needs several runs, and `telemetry.yaml` says
so: automating it before anybody has read two reports by hand is how the wrong thing gets
measured precisely. This is the second report; the first is G7 R1's, in `docoris`.
