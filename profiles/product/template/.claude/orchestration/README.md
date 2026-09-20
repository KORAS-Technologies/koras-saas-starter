# Koras Multi-Agent Engineering Orchestration

The shared orchestration contract for a KORAS **product** repository. The
Control Plane profile does not carry it, and a test asserts that it does not.

## What this is

Forty reusable role definitions and the rules that decide which of them run.
They are **definitions, not processes** — nothing is running in the background,
and almost all of them stay dormant for any given feature.

```text
orchestration/
  conditions.yaml          The one applicability vocabulary - every other file's conditions come from here
  risk-model.yaml          Which execution mode a change gets, from the boundaries it touches
  execution-modes.yaml     FAST, STANDARD and FULL - routing strategies, not quotas
  agent-registry.yaml      The 40 agents, what each is for, and whether each may modify production code
  activation-rules.yaml    Which agents a feature actually needs
  execution-budget.yaml    How many times the framework may try before it asks a person
  gate-invalidation.yaml   When a passed gate may be trusted again, and when it must run again
  lifecycle.yaml           Where a feature is, from approval to closed - including after the merge
  deployment-awareness.yaml  What a push triggers, and what a partial deployment left behind
  telemetry.yaml           What a run reports about itself when it finishes
  workflow.yaml            How an approved feature moves through them, and the two freeze points
  quality-gates.yaml       The gates, and the four human decisions
  documentation-policy.yaml  The canonical feature documentation structure - authoritative
  definition-of-done.md    What "done" means, condition by condition
  WORKTREE-STANDARD.md     One canonical worktree location, outside the repository
  product-profile.example.yaml  Per-product configuration, copy and edit
```

## The shape of a cycle

1. **Plan.** `product-planner` inspects the repository and recommends the next
   three ready features. It does not start anything.
2. **Approve.** A human authorizes one. This gate is not optional and no agent
   can satisfy it.
3. **Classify.** `engineering-orchestrator` decides FAST, STANDARD or FULL
   from the boundaries the change actually touches -- not from what it is
   about -- and publishes the execution plan, including the gates that do
   not apply and why.
4. **Orchestrate.** It builds the dependency graph, runs file-overlap
   analysis, selects the minimum agent set by asking what capability is
   needed before which agent, and assigns DEV-1, DEV-2 or DEV-3 to isolated
   worktrees.
5. **Implement.** Up to three workers implement dependency-safe features
   concurrently, each in its own worktree and branch.
6. **Verify independently.** No agent verifies or accepts its own work.
   User-facing features require real browser verification and executed manual
   QA with genuine screenshot evidence.
7. **Accept.** `final-acceptance` walks the Definition of Done and reports
   READY or NOT READY -- about the local tree, and no further.
8. **Human gates.** Merge and production release remain human decisions, and
   nobody is asked to approve a push without being told what it triggers.
9. **Close.** CI, the deployment and the environment check report for
   themselves. A feature that needs them is not closed until they have.

## Five things this contract exists to prevent

- **Over-activation.** Running all 40 agents for a one-line change is a defect
  in orchestration. `activation-rules.yaml` is the answer to "which of these
  actually apply", and `conditions.yaml` is where the question itself is
  defined -- once, for the agents, the gates and the documents alike.
- **Self-approval.** An implementation agent cannot review, evidence or accept
  its own work. The gates marked `independent` in `quality-gates.yaml` enforce
  it.
- **Re-running what nothing touched.** V2 recorded nothing about a gate
  beyond whether it had passed, so "did anything relevant change?" had no
  answer -- and with no answer the only safe habit is to re-run everything.
  Each gate now declares the change classes its result depends on, and
  `gate-invalidation.yaml` derives the rest: a browser-test correction
  invalidates the browser gate and acceptance, and reuses the other nineteen.
- **Unbounded loops.** V2 could not stop. Nothing capped a retry, so the only
  thing deciding whether to go round again was whether the next attempt looked
  promising -- and it always does. `execution-budget.yaml` caps every loop,
  and the two freeze points in `workflow.yaml` decide what a late change
  costs, so that correcting a sentence in a document no longer re-opens the
  engineering lifecycle.
- **Fabricated evidence.** A PASS is the cheapest thing in the pipeline to
  produce. Manual QA executes against a real environment or reports BLOCKED;
  `qa-reviewer` audits that the evidence is real.

## Domain knowledge

Product-specific business rules live in `.claude/domain/`, never in these 40
agents. The shared catalog is identical in every KORAS product; the domain
overlay is what makes a product's agents know its business. See
`.claude/domain/README.md`.
