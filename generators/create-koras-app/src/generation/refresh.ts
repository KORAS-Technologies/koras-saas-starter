import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { GenerationContext } from './context.js'
import { collectSharedAssets } from './engine.js'
import { writeFiles } from './writer.js'

export interface RefreshResult {
  /** Files whose bytes differ from the starter's copy, or that do not exist yet. */
  changed: string[]
  /** Files already identical — the common case, and reported as a count only. */
  unchanged: number
  /** False when --dry-run asked for the list without writing it. */
  written: boolean
}

/**
 * Re-copies the manifest's shared asset directories into a project that already
 * exists on disk.
 *
 * A generated project owns a private copy of `infrastructure/terraform/modules`,
 * which is what makes `--provision-only` reproducible: the plan reflects the
 * code in the project, not whatever the starter happens to contain today. The
 * cost is that a module fixed in the starter never reaches a project generated
 * before the fix, and nothing says so — the stale copy plans perfectly happily
 * and fails at apply, or worse, succeeds against the wrong definition.
 *
 * Scope is deliberately narrow. Only paths the profile declares as shared
 * assets are touched, so nothing an operator edited in their own project can be
 * overwritten by this: everything else in the tree is theirs.
 */
export function refreshSharedAssets(
  ctx: GenerationContext,
  projectRoot: string,
): RefreshResult {
  const assets = collectSharedAssets(ctx)

  const changed: string[] = []
  let unchanged = 0

  for (const file of assets) {
    const target = join(projectRoot, file.outputPath)
    if (!existsSync(target)) {
      changed.push(file.outputPath)
      continue
    }
    const current = readFileSync(target)
    const incoming = Buffer.isBuffer(file.content) ? file.content : Buffer.from(file.content)
    if (current.equals(incoming)) unchanged += 1
    else changed.push(file.outputPath)
  }

  // Nothing to do is worth saying out loud rather than writing identical bytes
  // over a tree and reporting a number.
  if (ctx.dryRun || changed.length === 0) {
    return { changed, unchanged, written: false }
  }

  writeFiles(
    ctx,
    assets.filter((file) => changed.includes(file.outputPath)),
  )

  return { changed, unchanged, written: true }
}

export function formatRefreshResult(result: RefreshResult): string {
  if (result.changed.length === 0) {
    return `\nShared modules are already up to date (${result.unchanged} files).`
  }

  const verb = result.written ? 'Refreshed' : 'Would refresh'
  const lines = [
    '',
    `${verb} ${result.changed.length} shared module file(s); ${result.unchanged} already current:`,
    ...result.changed.map((path) => `  ${path}`),
  ]
  if (!result.written) lines.push('', '--dry-run: nothing was written.')
  return lines.join('\n')
}
