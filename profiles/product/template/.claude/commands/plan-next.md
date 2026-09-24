# /plan-next

Use the Product Planner (`.claude/agents/planning/product-planner.md`) to recommend what to build next. Do not start implementation.

Inspect, before recommending anything: the roadmap; the backlog including deferred items and the stated reason; completed features; the existing code, to establish what is really implemented rather than what is documented as implemented; the architecture and ADRs; documentation gaps; open bugs; technical debt; outstanding security findings; failing or skipped tests; and dependencies against anything already in flight. Also inspect every feature currently sitting at `IMPLEMENTED_PENDING_VALIDATION`, since that pending set is an input to the recommendation below.

Then recommend the **next three ready features**, ranked. For each one give: feature ID, title, business value, technical value, dependencies, readiness, risk, parallel safety, required agent capabilities, rationale, and:

- **Execution mode.** BUILD or IMMEDIATE, from `.claude/orchestration/acceptance-batching.yaml`. Derive it from the risk mode `.claude/orchestration/risk-model.yaml` would select for this feature — IMMEDIATE is the only option whenever any floor signal fires or a declared combination applies; BUILD is available, and the default recommendation, otherwise. State the mode and the rule that produced it, the same way `risk-model.yaml` requires a stated rationale for its own mode.
- **Gates that must run immediately regardless of mode**: implementation, unit and targeted integration tests, one independent code review, and any gate a floor signal makes non-deferrable — named individually, not summarised as "the usual security gates".
- **Gates safely deferred to a validation batch**, if the mode is BUILD: the subset of `manual_qa_pass`, `screenshot_evidence_complete`, `qa_evidence_audit`, `e2e_pass`, `documentation_audit`, `regression_pass` and `final_acceptance` that actually apply to this feature.

For recommendation #1 only, generate a complete, ready-to-run implementation prompt, including its execution mode and the two gate lists above.

**Parallel developer assignment** (DEV-1/DEV-2/DEV-3): recommend running more than one of the three concurrently only when `workflow.yaml`'s `pre_parallel_checks` — dependency graph, file overlap, contract overlap, migration ordering — all come back clear between the candidates. Where they do not, say which check failed and sequence the features instead of parallelising them.

**When to recommend `/validate-batch`.** Look at the accumulated set of features at `IMPLEMENTED_PENDING_VALIDATION` and recommend a validation batch when a risk boundary, a dependency, or a milestone/epic boundary actually justifies it — never on a fixed count of pending features and never on a fixed elapsed time; `acceptance-batching.yaml`'s `validate_batch.triggered_by` and `never_triggered_by` are the list to check against. If none of those hold, say so explicitly rather than silently recommending nothing — a plan that never mentions the pending set is indistinguishable from one that forgot it exists.

Log any gap or defect you find through the repository's existing backlog mechanism — the register, the follow-ups list or the risk register, whichever already owns that class. Do not start a second list.

End with an explicit `WAITING FOR HUMAN APPROVAL`. A recommendation is not an authorization: do not assign a developer worker, do not create a worktree, and do not write production code.

Context/request:
```text
$ARGUMENTS
```
