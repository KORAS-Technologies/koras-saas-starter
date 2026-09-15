# /orchestrate-feature

Orchestrate one **approved** feature using `.claude/orchestration/`. If the feature has not been approved by a human, stop and say so.

Act as `engineering-orchestrator`:

1. Read the orchestration contract: `agent-registry.yaml`, `activation-rules.yaml`, `workflow.yaml`, `quality-gates.yaml`, `documentation-policy.yaml` and `definition-of-done.md`.
2. Inspect the repository and current Git state before planning anything.
3. Run impact analysis and build the dependency graph.
4. Select the **minimum** agent set the feature actually requires. Do not activate all 40.
5. Assign one available worker — DEV-1, DEV-2 or DEV-3 — and create its worktree at the canonical location in `WORKTREE-STANDARD.md`, on its own branch.
6. Enforce the quality gates, and route every failure through `bug-triage` to the owning agent.
7. Require independent verification: no agent reviews, evidences or accepts its own work.
8. For user-facing work, require real browser verification and executed manual QA with genuine screenshots. Never fabricate execution evidence.
9. Stop at the human gates. Never merge to a protected branch and never deploy to production.

Report: execution plan, dependency graph, agent assignments with the reason each was activated, the worker/worktree/branch map, gate status, blockers, and the explicit next human action.

Approved feature/prompt:
```text
$ARGUMENTS
```
