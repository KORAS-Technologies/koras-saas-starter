# /orchestrate-feature

Orchestrate one **approved** feature using `.claude/orchestration/`. If the feature has not been approved by a human, stop and say so.

Act as `engineering-orchestrator`:

1. Read the orchestration contract: `conditions.yaml`, `risk-model.yaml`, `execution-modes.yaml`, `agent-registry.yaml`, `activation-rules.yaml`, `workflow.yaml`, `quality-gates.yaml`, `documentation-policy.yaml` and `definition-of-done.md`.
2. Inspect the repository and current Git state before planning anything.
3. Run impact analysis and build the dependency graph.
4. Classify risk against `risk-model.yaml`, and select FAST, STANDARD or FULL. A signal fires only when the **boundary** it names is actually touched — not because the change is *about* storage, payments or AI. Name every signal that fired, every signal the change resembled and why it did not fire, and the rule that chose the mode.
5. Select the **minimum** agent set: what capability is needed, then which agent supplies it. Do not activate all 40, and do not treat FULL as an instruction to.
6. **Publish the execution plan before implementing anything**, with every row the Orchestrator's output contract lists — including the gates that do *not* apply and the condition each of them failed to meet.
7. Assign one available worker — DEV-1, DEV-2 or DEV-3 — and create its worktree at the canonical location in `WORKTREE-STANDARD.md`, on its own branch.
8. Enforce the quality gates, and route every failure through `bug-triage` to the owning agent.
9. Require independent verification: no agent reviews, evidences or accepts its own work.
10. For user-facing work, require real browser verification and executed manual QA with genuine screenshots. Never fabricate execution evidence.
11. Stop at the human gates. Never merge to a protected branch and never deploy to production.

Report: the execution plan, the risk classification and mode with its rationale, the dependency graph, agent assignments with the capability and condition behind each, the worker/worktree/branch map, gate status, blockers, and the explicit next human action.

Approved feature/prompt:
```text
$ARGUMENTS
```
