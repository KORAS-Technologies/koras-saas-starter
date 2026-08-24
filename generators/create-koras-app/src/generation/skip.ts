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
])
