# /run-parallel

Plan up to three **approved** features for concurrent execution across DEV-1, DEV-2 and DEV-3.

Before assigning anything, run the dependency and overlap analysis required by `workflow.yaml`:

- dependency graph across the candidate features
- file-level overlap
- contract-level overlap
- migration ordering

Then classify each pair as safe, safe-after-sequencing, or unsafe. **Features that overlap on files, contracts or migrations are sequenced, not parallelized.** If a shared foundation must land first, say so and sequence it; do not parallelize around it.

Assign at most three workers, each to its own worktree and branch at the canonical location in `WORKTREE-STANDARD.md`. Two workers never share a working directory or a branch.

Each feature keeps its own full set of gates: verification, independent review, QA evidence, documentation and acceptance. Parallelism changes the scheduling, not the standard.

Before Final Acceptance on the converged result, run `integration-regression` — three features that each passed their own gates can still have broken each other.

Do not merge and do not deploy.

Approved features:
```text
$ARGUMENTS
```
