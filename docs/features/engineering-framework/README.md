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
- **One generated product has now run a feature through V2.1.** Docoris,
  G7 R1, 2026-09-20. It is validated by its own tests, by generation, and by
  exactly one real lifecycle -- which found four things, below. One case
  study is not a sample.

## What the first real lifecycle found

G7 R1 ran a feature end to end in a generated product. Nothing it hit was a
wrong rule. All four were a question the framework had not written down, which
an agent then answered by judgement -- correctly each time, and invisibly each
time. A judgement nobody can see is indistinguishable from a skipped step.

- **A gate whose owner the mode did not staff.** FAST staffs neither
  `business-analyst` nor `solution-architect`; `requirements_ready` and
  `architecture_ready` both apply `always`. The Orchestrator resolved both and
  left no record. Now `owner_optional_in` declares the exception per gate, and
  `owner_optional_closure` demands the seven fields that make the closure
  arguable. Agent sets were never a way to switch gates off, and that is now
  stated where a reader of either file will meet it.
- **The strongest proof was the least governed artefact.** A before-and-after
  console capture carried the whole claim, and nothing required it to be
  declared, retained or independently looked at. `primary_evidence` names it
  in the plan before the validating action, retains it under the existing
  `evidence_runs` policy, and requires a verifier who did not produce it --
  reading the capture, not necessarily re-running the scenario.
- **A final count written before the event it counted.** Not fabricated: the
  plan was stored where the history goes. Telemetry is now an append-only
  event log, corrections are amendments rather than edits, and the summary is
  derived after the last applicable event. UNKNOWN is a value; 0 is a
  measurement.
- **Agents that were there and then were not.** A long-lived session listed 25
  of the 40; a fresh process listed all 40 from the same commit with no file
  changed. `runtime_discovery` says to check the agents the plan needs before
  a lifecycle, classify a shortfall as session health, and restart rather than
  reorganise -- because flattening the category directories would have
  "fixed" it and broken the catalog.

Also corrected, and not a framework defect: a generated product's `CLAUDE.md`
listed `.claude/agents/` as the four legacy files and mentioned the forty
nowhere, so a reader of the product concluded its catalog was four. The four
are retained -- `/feature`, `/review`, `/test` and `/ui-review` read them, and
they carry no frontmatter so Claude Code never registered them as agents --
and the generator template now says which set is which. The canonical count
was 40 before G7 and is 40 after it.

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

## Extension: acceptance batching (2026-09-23)

A process-change request asked for LOW/MEDIUM-risk features to defer
manual QA, screenshots, the evidence audit, the full E2E suite, the
documentation audit and Final Acceptance to a later batch, while keeping
every risk-triggered gate immediate. `docs/adr/0011-koras-engineering-
framework-build-validate.md` is the decision; `acceptance-batching.yaml` is
the file; `docs/ENGINEERING_FRAMEWORK.md`'s "Build now, validate later"
section is the summary.

It is additive to V2.1 rather than a new phase of it: no existing gate, mode,
condition or agent changed meaning. What changed is `quality-gates.yaml`
(seven gates flagged `deferrable_in_build`), `lifecycle.yaml` (one new state,
`IMPLEMENTED_PENDING_VALIDATION`), `workflow.yaml` (one note at the
suspension point, not a second stage list), `documentation-policy.yaml` and
`definition-of-done.md` (cross-references only), plus a new command,
`/validate-batch`, and an extended `/plan-next` that states an execution
mode and a deferred-gate list per recommendation.

Not yet done, and not this pass: no generated product has run a BUILD
feature through `IMPLEMENTED_PENDING_VALIDATION` to a validation batch and
back. Doing that once, in a generated product, the way G7 R1 did for V2.1
above, is the case study this extension does not yet have.
