# G7R2-F01 — telemetry summary

Derived from `../telemetry-events.md` and `../telemetry-amendments.md` on
2026-09-21, after the last applicable pre-merge event. **This is a reading of the
record, not the record.** Where this file and the event log disagree, the log wins.

Counts come from events. A metric no event supports is `UNKNOWN`, not `0` — zero is a
measurement and means the thing was watched for and did not happen.

## Routing

| | |
|---|---|
| execution_mode | **FAST** |
| risk_signals_fired | **0** — all ten floor signals and all eight elevating signals were walked individually and each recorded as not fired |
| risk_signals_rejected | **3** named explicitly: `multi_step_user_workflow`, `security_boundary`, `architecture_impact` — each with the boundary it names and what in the change does not touch it |
| mode_overridden_by_human | no |
| selection_rule | `no_signal_and_every_fast_requirement_holds` |

## Agents

| | |
|---|---|
| agents_available | **40**, all discoverable in a fresh runtime (run `2026-09-21-02`) |
| agents_invoked | **6** as separate processes: `product-planner`, `impact-analysis`, `ux-ui-designer`, `developer-1`, `code-reviewer`, and `engineering-orchestrator` as this session |
| agents_activated | **17** of 40, per the execution plan, counting the roles the Orchestrator carried where no separate process was warranted |
| agents_available_but_not_activated | **23** |
| invocations_per_agent | `ux-ui-designer` 2 (at `same_agent_max_invocations`); every other agent 1 |

**The one number the framework is judged on.** 23 of 40 agents were available and not
activated. The independent review looked specifically for work the excluded agents would
have found — security, tenancy, data, architecture — and found none, so the routing was
minimal rather than merely smaller.

## Gates

| | |
|---|---|
| gates_executed | **12** |
| gates_closed_owner_optional | **2** — `requirements_ready`, `architecture_ready`, each with all seven required fields recorded in the plan before the gate came due |
| gates_reused | **0** |
| gates_invalidated | **0** |
| gates_not_applicable | **7** — `api_integration_tests_pass`, `architecture_review`, `security_review`, `privacy_review`, `ai_evaluation`, `regression_pass`, `domain_review`, each with the unmet condition named |
| gates_not_applicable_by_policy | **0** |
| gates_pending | **3** post-merge: `ci_verified`, `deployment_preflight`, `environment_verified` |

**Zero reuse, and that is the honest number rather than a disappointing one.** Reuse
requires a prior recorded PASS for this feature whose input classes the change did not
touch. This feature had no prior run — every gate ran for the first time. Reuse is a
claim about a second pass, and there was no second pass to make it in.

**The invalidation that did not happen is the more interesting record.** Between the
frozen commit and the green suite the whole worktree was deleted and re-checked-out with
a different line-ending setting. `git status` was clean on both sides and no tracked
content changed, so no gate input changed and nothing was invalidated — which is exactly
what the rule says should happen, and the only way to tell is that the rule was applied
rather than assumed.

## Loops

| | |
|---|---|
| test_fix_cycles | **1** of 2 — the documentation-gate remediation |
| reviewer_cycles | **1** of 2 — one review, PASS, no fix cycle, no re-review |
| documentation_audits | recorded below once run |
| final_acceptance_attempts | recorded below once run |
| retries | **1** — `automated_tests_pass` re-run after the line-ending re-checkout, with nothing changed in the tree. A retry, not a cycle, and the failing first attempt is retained. |
| remediation_cycles | **1** — targeted, root cause established, scope stated by change class |
| budget_caps_reached | **1** — `ux-ui-designer` reached `same_agent_max_invocations` at 2 |
| human_escalations | **0** |

**One cap was reached and it did not stop anything**, which is the useful case to record:
`ux-ui-designer` was invoked twice because the first invocation's write was refused by the
permission set and it returned a summary instead of the document. The second invocation,
with write tools denied and the document asked for on standard output, produced it. Had a
third been needed the budget would have forced a stop.

## Lifecycle

| | |
|---|---|
| state_reached | `PLANNED` → `IMPLEMENTING` → `TESTING` → `LOCAL_ACCEPTANCE_READY` |
| freeze points | `code_freeze` at `e677b54`; `quality_freeze` at `e677b54` |
| states_not_applicable | `DEV_DEPLOYED` and `DEV_VERIFIED` — the factory deploys nothing of its own |
| deployment_components_by_state | **UNKNOWN** — no deployment applies, and no event records a component state |

## Effort

| | |
|---|---|
| elapsed_time_if_available | **UNKNOWN.** No event records a duration. The log carries timestamps to the minute, from which an elapsed wall-clock figure could be inferred — but an inferred figure is not a measurement, and this framework has already had one number written from a plan rather than from an event. |

## Amendments

**1.** The probe-1 discovery shortfall was first classified with two tokens this
repository does not declare, taken from the G7 R2 brief rather than from
`agent-registry.yaml`. Corrected to `SESSION_OR_TOOL_HEALTH`, with the previous value
left visible. Caught by `tests/docs/identifiers.test.ts`, which is what it is for.

## What this summary cannot tell you

Whether the mode was right. That comparison — the mode selected against the gates that
turned out to matter — needs several runs, and `telemetry.yaml` says so explicitly:
automating a comparison before anybody has read two reports by hand is how the wrong
thing gets measured precisely. This is the second report. The first is G7 R1's, in
`docoris`.
