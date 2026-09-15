# Koras Multi-Agent Engineering Orchestration

The shared orchestration contract for a KORAS **product** repository. The
Control Plane profile does not carry it, and a test asserts that it does not.

## What this is

Forty reusable role definitions and the rules that decide which of them run.
They are **definitions, not processes** — nothing is running in the background,
and almost all of them stay dormant for any given feature.

```text
orchestration/
  agent-registry.yaml      The 40 agents, their definitions and whether each may modify production code
  activation-rules.yaml    Which agents a feature actually needs
  workflow.yaml            How an approved feature moves through them
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
3. **Orchestrate.** `engineering-orchestrator` builds the dependency graph,
   runs file-overlap analysis, selects the minimum agent set from the registry,
   and assigns DEV-1, DEV-2 or DEV-3 to isolated worktrees.
4. **Implement.** Up to three workers implement dependency-safe features
   concurrently, each in its own worktree and branch.
5. **Verify independently.** No agent verifies or accepts its own work.
   User-facing features require real browser verification and executed manual
   QA with genuine screenshot evidence.
6. **Accept.** `final-acceptance` walks the Definition of Done and reports
   READY or NOT READY.
7. **Human gates.** Merge and production release remain human decisions.

## Three things this contract exists to prevent

- **Over-activation.** Running all 40 agents for a one-line change is a defect
  in orchestration. `activation-rules.yaml` is the answer to "which of these
  actually apply".
- **Self-approval.** An implementation agent cannot review, evidence or accept
  its own work. The gates marked `independent` in `quality-gates.yaml` enforce
  it.
- **Fabricated evidence.** A PASS is the cheapest thing in the pipeline to
  produce. Manual QA executes against a real environment or reports BLOCKED;
  `qa-reviewer` audits that the evidence is real.

## Domain knowledge

Product-specific business rules live in `.claude/domain/`, never in these 40
agents. The shared catalog is identical in every KORAS product; the domain
overlay is what makes a product's agents know its business. See
`.claude/domain/README.md`.
