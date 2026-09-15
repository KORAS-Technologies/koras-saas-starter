# /plan-next

Use the Product Planner (`.claude/agents/planning/product-planner.md`) to recommend what to build next. Do not start implementation.

Inspect, before recommending anything: the roadmap; the backlog including deferred items and the stated reason; completed features; the existing code, to establish what is really implemented rather than what is documented as implemented; the architecture and ADRs; documentation gaps; open bugs; technical debt; outstanding security findings; failing or skipped tests; and dependencies against anything already in flight.

Then recommend the **next three ready features**, ranked. For each one give: feature ID, title, business value, technical value, dependencies, readiness, risk, parallel safety, required agent capabilities, and rationale.

For recommendation #1 only, generate a complete, ready-to-run implementation prompt.

End with an explicit `WAITING FOR HUMAN APPROVAL`. A recommendation is not an authorization: do not assign a developer worker, do not create a worktree, and do not write production code.

Context/request:
```text
$ARGUMENTS
```
