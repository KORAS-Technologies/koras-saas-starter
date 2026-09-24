# /validate-batch

Run a validation batch over features currently at `IMPLEMENTED_PENDING_VALIDATION`, per `.claude/orchestration/acceptance-batching.yaml`.

First list every feature at that state. Select into this run the ones a risk boundary, a dependency, or a milestone/epic boundary actually justifies batching now — never a fixed count and never a fixed elapsed time. State the trigger for running the batch now, by name.

For each feature selected, run its own deferred gates — exactly the set `acceptance-batching.yaml` marks `deferrable_in_build` and that this feature's plan named as deferred: manual QA, screenshot evidence, the evidence audit, the full E2E suite, the documentation audit, regression where applicable, and final acceptance. Each gate keeps its own independence, its own evidence requirements from `documentation-policy.yaml`, and its own budget accounting from `execution-budget.yaml` — deferred is a timing decision, never a discount.

Then, once across the whole batch: cross-feature regression on the combined result; one manual workflow pass end to end where the batch has a combined user-facing workflow; a broader accessibility review across the combined surface where any batched feature added or changed one; a security or privacy validation pass across the batch where one is still pending (expect `NOT_APPLICABLE` — no floor-signal feature ever reaches BUILD — and record it as that rather than omitting the check); a documentation consistency pass across the batch.

A feature whose own gates all pass reaches `LOCAL_ACCEPTANCE_READY` and continues through the lifecycle exactly as an immediate feature would — merge, push, CI, deployment, closure, unchanged. A feature with a failing gate is routed to `bug-triage` per the rework rules in `workflow.yaml`, stays pending, and does not hold up the rest of the batch: this is not a transaction, and making it one recreates the serialization cost BUILD exists to avoid.

Report, per feature: which gates ran, their results, and the lifecycle state reached. Report, for the batch: the trigger that justified running it, the batch-wide checks performed and their results, and every feature still pending afterward and why.

Do not close a feature's `IMPLEMENTED_PENDING_VALIDATION` state without having run that feature's own deferred gates. The batch-wide checks test the seams between features; they do not stand in for any one feature's own evidence.

Context/request:
```text
$ARGUMENTS
```
