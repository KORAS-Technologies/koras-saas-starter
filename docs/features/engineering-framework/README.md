# Engineering framework — V2.1

| | |
|---|---|
| **What** | The product profile's multi-agent orchestration contract, optimised from V2 without changing the 40-agent catalogue. |
| **Where** | `profiles/product/template/.claude/orchestration/` |
| **Architecture** | `docs/ENGINEERING_FRAMEWORK.md` |
| **Decision** | `docs/adr/0010-koras-engineering-framework-v2-1.md` |
| **Delta** | `docs/features/engineering-framework/v2-to-v2-1.md` |
| **Upgrade** | `docs/features/engineering-framework/adoption.md` |
| **Shipped** | 2026-09-19 |

## Why it was done

V2 delivered its first complete real feature lifecycle successfully, and the
execution was expensive in a specific, measurable way. That lifecycle ran
roughly five accessibility cycles, five code reviews, five browser runs, five
evidence audits, six manual QA passes and three final acceptances, and
produced about 164 screenshots for 20 manual cases.

None of it was carelessness. Every individual decision to go round again was
defensible. The framework had no point at which judgement was required,
because it could not answer two questions:

1. **Did anything relevant to this gate change?** Nothing was recorded about
   a gate beyond whether it had passed, so the only safe habit was re-running
   everything.
2. **When do we stop?** Nothing capped any loop, so the only thing deciding
   whether to try again was whether the next attempt looked promising — and
   it always does.

V2.1 answers both without weakening a single gate.

## What was not changed

- The 40 agents. None added, removed, renamed or merged.
- Independence. No agent reviews, evidences or accepts its own work.
- The four human gates.
- Manual QA's verdicts, evidence rules and no-fabrication rules — a test
  asserts each of them survived this work.
- Control Plane isolation. The framework remains product-only, asserted in
  both directions.

## The phases, as executed

| Phase | What it added | Tests after |
|-------|---------------|------------:|
| P1 | One applicability vocabulary (`conditions.yaml`) | 415 |
| P2 | Risk model, execution modes, capability routing, execution plan | 438 |
| P3 | Execution budget, freeze points, escalation | 454 |
| P4 | Gate result model, invalidation, targeted remediation | 477 |
| P5 | Lifecycle, push impact, deployment acceptance, partial deployment | 499 |
| P6 | Documentation timing, append-only evidence, manual QA aim, screenshots, epics | 511 |
| P7 | Process-tree teardown, generated-file hygiene, typed preflight | 527 |
| P8 | Telemetry, Planner integration, documentation, audit | see below |

Counts are the `orchestration` and `claude-config` suites together. The
baseline before P1 was 406.

Each phase was mutation-checked: a deliberate defect was introduced, the
suite was required to fail on it, and the tree was restored. Two of those
checks initially passed against an unmutated tree because the mutation script
used the wrong line endings, which is recorded in the delta document rather
than quietly fixed.

## Known limits

- **Nothing executes any of this.** Every rule is followed by an agent
  reading it. The routing, the reuse decision and the budget are contracts,
  not mechanisms.
- **The gate-result record is specified, not written.** Reuse is a claim an
  agent makes against the record's fields; nothing persists them.
- **The screenshot policy is judgement, guided.** What can be checked is that
  the policy exists, that `evidence_purpose` is a required field, and that
  the template carries the column.
- **Change classes are path globs an agent matches by reading a diff.** A
  file in an unconventional location can be classed wrongly.
- **Typed preflight covers 15 product settings and 2 Control Plane
  settings** as of 2026-09-19. Everything untyped is unreadable to that tool
  by design, and extending coverage is incremental.
- **No generated product has run a feature through V2.1 yet.** The framework
  is validated by its own tests and by generation; it has not been exercised
  by a real lifecycle.

## Recommended next, in order

1. **Make the contract executable.** A `koras orchestrate` command in
   `tooling/koras-cli` that computes conditions, mode, agent set and gate
   reuse from these files, turning a contract an agent may follow into one it
   cannot skip.
2. **Persist gate results.** A per-feature store under
   `docs/features/<id>/testing/runs/`, written by that command, so reuse is
   verifiable rather than asserted.
3. **Compare telemetry across features.** Once several runs exist, check the
   mode selected against the gates that turned out to matter, and tune the
   risk model from evidence instead of from one case study.

All three were deliberately left out of V2.1: building the store before the
contract is how a store comes to record the wrong fields, and automating a
comparison before anybody has read two reports by hand is how the wrong thing
gets measured precisely.
