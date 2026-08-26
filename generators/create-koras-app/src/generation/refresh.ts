import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { GenerationContext } from './context.js'
import { collectSharedAssets, renderTemplate } from './engine.js'
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
 * The declared assets are the Terraform modules and the common Claude Code
 * configuration in `.claude`. A generated project owns a private copy of
 * `infrastructure/terraform/modules`,
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

/**
 * What --refresh-modules did *not* do.
 *
 * It refreshes shared assets and nothing else, which is correct and is not
 * obvious. A change spanning a Terraform module and the rendered file that
 * passes a variable into it lands half-applied: the module is current, the
 * caller still holds the old signature, and the failure shows up at plan time
 * looking like something unrelated to refreshing.
 *
 * That happened. A ZITADEL fix landed in `modules/zitadel` while
 * `infrastructure/terraform/main.tf` kept the old module call, and two rounds
 * of re-running the plan went by before anyone read the files. Saying so here
 * costs a few lines and removes the trap.
 */
const REFRESH_FOOTER = [
  '',
  'Shared assets only. Files rendered from the profile template -- main.tf,',
  'variables.tf, workflows, Dockerfiles -- are untouched by this flag.',
  'If a fix spans both, name them too:',
  '',
  '  --check-drift --all       what is behind',
  '  --refresh <path>          bring one rendered file forward',
]

export function formatRefreshResult(result: RefreshResult): string {
  if (result.changed.length === 0) {
    return [
      '',
      `Shared files are already up to date (${result.unchanged} files).`,
      ...REFRESH_FOOTER,
    ].join(String.fromCharCode(10))
  }

  const verb = result.written ? 'Refreshed' : 'Would refresh'
  const lines = [
    '',
    `${verb} ${result.changed.length} shared file(s); ${result.unchanged} already current:`,
    ...result.changed.map((path) => `  ${path}`),
    ...REFRESH_FOOTER,
  ]
  if (!result.written) lines.push('', '--dry-run: nothing was written.')
  return lines.join(String.fromCharCode(10))
}

export interface RefreshPathResult {
  updated: string[]
  unchanged: string[]
  /** Named but not produced by this profile -- a typo, or a path from the other profile. */
  unknown: string[]
  written: boolean
}

/**
 * Overwrites named template-owned files with the generator's rendering.
 *
 * `refreshSharedAssets` cannot do this. Shared assets are copied verbatim from
 * the starter and belong to it, so recopying the directory is always safe.
 * Everything else in a generated project is rendered from the profile template
 * and then lived in: a workflow, a Dockerfile, a service module. A fix to one of
 * those in the starter has no route into an existing project at all, which is
 * how a worker whose queue address was corrected in one repository stayed broken
 * in the template, and every project generated afterwards inherited the fault.
 *
 * The reason this takes explicit paths rather than a directory, or everything,
 * is that those same files legitimately diverge. Overwriting the set would
 * discard real work. Naming a path is the operator saying this one is the
 * generator's -- so discovery (`--check-drift --all`) and overwriting stay two
 * decisions rather than one.
 */
export function refreshRenderedPaths(
  ctx: GenerationContext,
  projectRoot: string,
  paths: string[],
): RefreshPathResult {
  const rendered = new Map(renderTemplate(ctx).map((file) => [file.outputPath, file]))

  const updated: string[] = []
  const unchanged: string[] = []
  const unknown: string[] = []
  const toWrite = []

  for (const path of paths) {
    const file = rendered.get(path)
    if (file === undefined) {
      unknown.push(path)
      continue
    }

    const target = join(projectRoot, path)
    const incoming = Buffer.isBuffer(file.content) ? file.content : Buffer.from(file.content)
    if (existsSync(target) && readFileSync(target).equals(incoming)) {
      unchanged.push(path)
      continue
    }
    updated.push(path)
    toWrite.push(file)
  }

  if (ctx.dryRun || toWrite.length === 0) {
    return { updated, unchanged, unknown, written: false }
  }

  writeFiles(ctx, toWrite)
  return { updated, unchanged, unknown, written: true }
}

export function formatRefreshPathResult(result: RefreshPathResult): string {
  const lines: string[] = ['']

  if (result.unknown.length > 0) {
    lines.push('This profile renders no such file:')
    lines.push(...result.unknown.map((path) => `  ${path}`))
    lines.push('  (--check-drift --all lists what it does render.)')
  }

  if (result.updated.length > 0) {
    lines.push(`${result.written ? 'Refreshed' : 'Would refresh'} ${result.updated.length} file(s):`)
    lines.push(...result.updated.map((path) => `  ${path}`))
  }

  if (result.unchanged.length > 0) {
    lines.push(`${result.unchanged.length} already current.`)
  }

  if (!result.written && result.updated.length > 0) {
    lines.push('', '--dry-run: nothing was written.')
  }

  return lines.join('\n')
}
