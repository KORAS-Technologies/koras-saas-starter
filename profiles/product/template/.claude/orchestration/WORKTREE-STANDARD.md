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
