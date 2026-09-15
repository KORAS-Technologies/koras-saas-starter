/**
 * Entries that appear inside a source tree but must never be copied out of it.
 *
 * `.terraform` is the one that bites: running any Terraform command inside the
 * shared modules leaves a provider cache there, and a walk of the filesystem
 * then ships a ~50MB `terraform-provider-*.exe` into every generated project.
 * It is gitignored, so it never shows up in review.
 *
 * `.terraform.lock.hcl` is its sibling and slipped through, because skipping a
 * directory named `.terraform` does nothing about a file whose name merely
 * starts the same way. A lock file belongs to a root configuration; the shared
 * modules are not root configurations, so an init run inside one leaves a lock
 * that means nothing -- and `--refresh-modules` then copied it into a real
 * project as though it were part of the module. Generated projects write their
 * own on first init.
 *
 * This lives in its own module because two things now need the same answer and
 * must not diverge: the engine, which decides what gets copied, and the
 * project manifest's digest, which claims to describe what a project received.
 * A digest that hashed a local provider cache would change on every machine and
 * report every project as stale -- the exact failure the line-ending
 * normalisation was added to prevent, arriving by a different route.
 */
export const SKIP_ENTRIES: ReadonlySet<string> = new Set([
  '.terraform',
  '.terraform.lock.hcl',
  '.git',
  'node_modules',
  '.turbo',
  '.next',
  'dist',
  // Python's caches, for the same reason and by the same route. Running pytest
  // or mypy inside `python-packages/` leaves `__pycache__` and `.coverage`
  // behind, and a walk then ships them into every generated project: nine of
  // them reached `profiles/`, where a drift check reported each one as a file
  // the project "never received". Six of twenty-four findings were bytecode.
  '__pycache__',
  '.pytest_cache',
  '.mypy_cache',
  '.ruff_cache',
  // Present in git.ts's own skip set and absent here, which is the divergence
  // the note above warns about rather than a new decision.
  '.venv',
  // A Claude Code agent's scratch checkout. `.claude/` is a `shared_asset`,
  // copied verbatim into every generated project, so a worktree created under
  // it puts a whole second copy of this repository -- 7 MB, its own `.git`
  // file, and whatever that agent was working on -- inside a customer's
  // repository. Found 2026-09-15, when one broke three tests by being there:
  // `drift` reported every file of it as repo-only and `claude-config` found
  // unrendered Handlebars tokens in the templates it had copied. The failing
  // tests are the mild version of this; the real one is a product shipping
  // with somebody's half-finished branch in it.
  'worktrees',
  // The canonical Koras worktree location, named in
  // `.claude/orchestration/WORKTREE-STANDARD.md`. That standard puts worktrees
  // outside the repository, where no walk can reach them -- so this entry is
  // defence in depth rather than the primary control. It matters because the
  // standard is a rule an agent can break and this is a mechanism it cannot:
  // a worker that creates `.koras-worktrees/` in the wrong place still cannot
  // ship it into a customer's repository.
  '.koras-worktrees',
])

/**
 * Path segments that mean "a git worktree lives here", in any position.
 *
 * `SKIP_ENTRIES` stops the walk from descending into one. This set exists for
 * the assertion afterwards: a generated project must contain no such path, by
 * whatever route it arrived. Kept beside the skip list because the two answer
 * the same question and must not drift.
 */
export const WORKTREE_SEGMENTS: ReadonlySet<string> = new Set(['worktrees', '.koras-worktrees'])
