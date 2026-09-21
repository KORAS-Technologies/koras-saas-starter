# FW-HARDEN-001 — derived telemetry summary

Finalised 2026-09-21, immediately before closure and after every gate, human
and escalation event — which is the rule this cycle wrote into
`telemetry.yaml` and is here following on its own run.

Derived from `../telemetry-events.md` and its amendments. **Not the record.**
Where this disagrees with the log, the log wins.

## Routing

| | |
|---|---|
| execution_mode | STANDARD |
| selection rule | `any_elevating_signal` |
| risk_signals_fired | `cross_feature_convergence` — a contract more than one feature reads |
| risk_signals_rejected | `platform_contract`, considered and argued down: the orchestration files are configuration copied in at generation time, not a payload another repository's code parses at runtime |
| floor signals fired | 0 |
| mode_overridden_by_human | no |

## Agents

| | |
|---|---|
| registered | 40 |
| discoverable | 40 |
| planned for activation | 11 |
| agents_available_but_not_activated | 29 |

**Invocations, and an honest qualification the contract's own "UNKNOWN is a
value" rule demands.** Two roles were executed as genuinely independent
agents that did not write the code: `code-reviewer` (1 invocation) and
`final-acceptance` (2). The other nine planned roles were performed by the
orchestrating session rather than by separate agents. Recording 11 independent
invocations would be false, and recording UNKNOWN would be worse — the number
is known and it is two.

That is the single largest gap between this run and the framework as written,
and it is stated here rather than left to be inferred from a count.

## Gates

| | |
|---|---|
| gates_executed | 21 |
| gates_reused | 0 |
| gates_invalidated | 0 — nothing was reused, so nothing needed invalidating |
| gates_not_applicable | 11, all from `user_interface` and the risk triggers being unmet |
| gates_not_applicable_by_policy | 0 |

Zero reuse is a measurement, not an omission: this was one continuous change
with three remediation rounds, and every round moved code that the gates
depended on.

## Loops

| | |
|---|---|
| test_fix_cycles | 1 — the documentation gates failing on this cycle's own evidence |
| reviewer_cycles | 1 |
| final_acceptance_attempts | 2 — FAIL, then PASS |
| remediation_cycles | 3 |
| retries | 0 |
| budget_caps_reached | 1 — the repository owner stopped a further confirmation run of the generator suite |
| human_escalations | 2 — the budget stop, and FW-DEF-003 recorded rather than fixed |

## Lifecycle

| | |
|---|---|
| state_reached | CLOSED |
| states_not_applicable | `DEV_DEPLOYED`, `DEV_VERIFIED` — nothing deploys |
| deployment_components_by_state | not applicable |

## Effort

| | |
|---|---|
| elapsed, first event to closure | about 3 hours 20 minutes, 15:25Z to 18:45Z, plus the merge and remote verification |
| full generator suite runs | 7 locally, 3 in an isolated CRLF worktree |
| remote gates | CI, Security and Generator Integration, all green at attempt 1 on `62780bc` |

## What is worth comparing, per the contract

- **Gates reused against gates executed: 0 of 21.** The reuse machinery this
  cycle repaired was not itself exercised by this cycle, which is worth being
  plain about. FW-GAP-006's fix is proven against G7 R2's historical diff, not
  against a reuse decision made here.
- **Reviewer cycles against the cap: 1.** The cap did not bind.
- **The mode against the gates that mattered:** STANDARD was right. No
  security, tenancy or data gate would have found anything, and the review —
  asked to contradict that — agreed. What found the defects was measurement,
  not additional gates.
- **Agents activated against agents that produced a finding: 2 of 2.** Both
  independent agents returned blocking findings, and both were correct. The
  29 excluded would each have found nothing.

## The number this run exists to have produced

**Three remedies created three next defects**, and two of them were invisible
to a fully green suite. `independent_code_review` and `final_acceptance` each
found one that the stage before had made. On the evidence of this run, the
independent gates are the only thing that caught the class of defect this
cycle was about.
