# /agent-status

Report current orchestration state from actual repository and Git evidence — branches, worktrees, commits, test results and gate reports. Do not infer state and do not claim that background agents are running: agent definitions are dormant and invoked on demand.

Report:

- developer worker assignments: which of DEV-1/2/3 is allocated, to what, and idle otherwise
- active feature branches and their worktree paths
- each feature's current stage against `workflow.yaml`
- gate status per feature, and which gates have not yet run
- blocking CRITICAL/HIGH findings and their owners
- the ready queue and the blocked queue, with what each is blocked on
- the next human gate awaiting a decision

If a worktree exists outside the canonical location in `WORKTREE-STANDARD.md`, or inside the repository, report it as a defect to be cleaned up.
