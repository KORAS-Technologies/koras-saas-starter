# FW-HARDEN-001 — derived telemetry summary

**Not yet finalised, as of 2026-09-21, and that is the contract being followed
rather than an omission.**

FW-GAP-010's amendment — made by this cycle — declares the derived summary a
closure artifact, finalised immediately before the terminal transition and
after every gate, human and escalation event. This run has not reached that
transition: the human merge gate is open, and the remote gates have not run.

Writing the numbers now would be the exact defect the amendment exists to
prevent, and the exact defect FW-GAP-003 recorded before it: a summary written
ahead of the events it summarises is a prediction stored where a fact goes.
A cycle that amended the contract and then broke it on its own run would be
worth less than no amendment.

The record meanwhile is `../telemetry-events.md`, which is append-only and is
the source of truth in any disagreement. Everything a reader needs is there.

## What will be derived here, and from what

| Line | Source |
|------|--------|
| execution_mode, risk signals fired and rejected | `../execution-plan.md`, event 4 |
| agents_invoked, invocations_per_agent, agents_available_but_not_activated | `../execution-plan.md`, events 5, 10, 18 |
| gates_executed, reused, invalidated, not_applicable | `../testing/`, events 6-23 |
| test_fix_cycles, reviewer_cycles, remediation_cycles, budget_caps_reached, human_escalations | the event log, counted |
| state_reached, states_not_applicable | `.claude/orchestration/lifecycle.yaml` |
| elapsed_time_if_available | the event log's own timestamps |

Per `telemetry.yaml`, a count with no event behind it is reported UNKNOWN and
never as zero. Zero is a measurement.
