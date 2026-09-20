# Koras Worktree Standard

One canonical location for every runtime worktree, deliberately **outside the
repository**.

```text
<repository-parent>/.koras-worktrees/<repository>/<feature-id>/
```

For a repository at `C:\repos\Projects\my-product`, DEV-2 working on `DOC-127`
uses:

```text
C:\repos\Projects\.koras-worktrees\my-product\DOC-127\
```

Branch naming is separate and follows `feature/<feature-id>-<slug>`.

## Why outside the repository

`.claude/` is copied verbatim into every generated project as a shared asset.
A worktree created *inside* the repository — and inside `.claude/` in
particular — is therefore copied too: a second full checkout, its own `.git`
file, and whatever that agent happened to be working on, shipped inside a
customer's repository.

This is not hypothetical. One existed in the starter on 2026-09-15 and broke
three tests by being there. The broken tests were the mild version; the real
version is a product shipping with somebody's half-finished branch in it.

Placing worktrees outside the repository root means no walk of the repository
can reach them, under any name.

## Rules

1. One worker, one worktree, one branch, one feature at a time.
2. Two workers never share a working directory or a branch.
3. The Orchestrator creates or verifies the worktree **before** the worker
   starts, and records the worker-to-worktree-to-branch map.
4. The Orchestrator performs file-overlap and contract-overlap analysis before
   assigning concurrent work. Features that overlap are sequenced.
5. A worker never merges, rebases onto a protected branch, force-pushes or
   deploys from its worktree.
6. Worktrees are removed when the feature closes. A stale worktree is a
   dependency-analysis hazard, because it makes a branch look active.

## Creating one

```bash
git worktree add ../.koras-worktrees/<repository>/<feature-id> -b feature/<feature-id>-<slug>
```

## Before the worker starts

A worktree is a checkout, not an environment. It arrives with whatever
`node_modules` and virtual environments the branch's lockfiles imply and
nothing installed, and the failure that follows is misleading rather than
obvious: a build fails locally, passes in CI, and the difference is a
dependency the branch added and this directory never installed. One feature
lost a cycle to exactly that.

So, in order, and before any build or test:

1. Create or reuse the worktree, at the canonical location.
2. Verify the branch is the one intended, and the tree is clean.
3. Compare the lockfiles against the last install in this worktree —
   `pnpm-lock.yaml` and `uv.lock`.
4. Synchronise only if they differ. A reinstall that was not needed costs
   minutes on every cycle and hides nothing.
5. Verify the tooling the branch needs is present.
6. Only then build or test.

A local failure that has not passed step 3 is not yet evidence of anything.

## Stopping what the worktree started

Stopping a dev command stops the command, not what it started. Every one of
them has something below it: `dev-service` spawns `uv`, which spawns Python,
and on Windows goes through `cmd.exe` as well; `dev-app` spawns Node running
Next, which forks its own workers.

One session ended with an orphaned worker holding port 8000 and an open
handle on the API executable, which blocked removing the whole worktree —
long after the process that appeared to own it had gone.

Teardown is therefore, in order:

1. Stop the QA services.
2. Terminate the **process tree**, not the visible parent.
   `local/scripts/process-tree.mjs` is what the dev wrappers use: a process
   group on POSIX, `taskkill /T /F` on Windows.
3. Verify the ports are released.
4. Verify no handle remains on files inside the worktree, where the platform
   makes that visible.
5. Remove the worktree.
6. `git worktree prune`.
7. Verify the directory is gone.

Never kill by name, and never kill a process this worktree did not start. The
target is the tree below a known pid, not everything that looks similar.

## Removing one

```bash
git worktree remove ../.koras-worktrees/<repository>/<feature-id>
git worktree prune
```

## Defence in depth

The standard puts worktrees out of reach. The generator does not rely on that
alone:

- `SKIP_ENTRIES` in `generators/create-koras-app/src/generation/skip.ts` skips
  `worktrees` and `.koras-worktrees` by name wherever they appear in a source
  tree, so a worktree created in the wrong place still cannot be copied.
- The generator's own validation refuses to emit a file whose path contains a
  worktree segment, and the orchestration test asserts that no generated
  project contains one.

Both halves exist because the standard is a rule that a person or an agent can
break, and the skip list is a mechanism that they cannot.
