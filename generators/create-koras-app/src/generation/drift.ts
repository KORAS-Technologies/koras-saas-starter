import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
import type { GenerationContext } from './context.js'
import { renderTemplate } from './engine.js'
import {
  PROJECT_MANIFEST_PATH,
  parseProjectManifest,
  resolveTemplateDigest,
} from './project-manifest.js'
import { readProjectTfvars } from '../terraform/inputs.js'

/**
 * Reports where a project on disk no longer matches what the generator would
 * produce for it.
 *
 * Read-only, always. Nothing here writes, and that is the point: the root
 * Terraform config is not a shared asset, so it cannot be refreshed the way
 * modules can, and a project silently planning against a stale copy is how a
 * missing provider block becomes a failed apply half an hour later.
 *
 * Scope is limited to files the generator owns outright. Application code is
 * expected to diverge — that is what a generated project is for.
 */

/**
 * Files where "differs from the generator" reliably means something is wrong.
 *
 * The root Terraform config is rendered wholly from the profile and has no
 * reason to diverge: a difference here is a provider, variable or output the
 * project has not picked up, which fails at plan time rather than review time.
 */
const OWNED_PATHS = [
  'infrastructure/terraform/providers.tf',
  'infrastructure/terraform/variables.tf',
  'infrastructure/terraform/main.tf',
  'infrastructure/terraform/backend.tf',
]

/**
 * Everything else the template ships, compared only when asked for (`--all`)
 * and never counted as a failure.
 *
 * This was a three-prefix allowlist -- `infrastructure/`, `local/`, `.github/`
 * plus seven root files -- on the reasoning that a healthy project edits the
 * rest, so comparing it says nothing. That reasoning is sound and the scope
 * drawn from it was still wrong: it excluded `services/`, `packages/`,
 * `python-packages/`, `apps/`, `tests/` and `supabase/`, which is where a
 * hand survey of `koras-control-plane` found forty of its forty-seven real
 * differences. The check reported fourteen files and there were nearly fifty.
 *
 * The noise the allowlist was avoiding is real, but it has a shape, and the
 * shape is nameable: the template ships a scaffold, the project replaces it
 * with the actual implementation. `packages/config/src/index.ts` is
 * `// config -- implement as needed`; the project's is the real module.
 * Reporting that as drift is what trains people to ignore the check.
 *
 * So the scope is now everything, and scaffolds are classified out instead of
 * being excluded by the directory they happen to live in. A replaced scaffold
 * is counted and not listed; anything the generator would *add* is listed,
 * because that is the direction that means the project is behind.
 */
function isScaffold(templateContent: string): boolean {
  const body = templateContent
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l !== '')

  if (body.length === 0) return true
  if (body.some((l) => /implement as needed/i.test(l))) return true

  // One or two lines that are only a comment, an `export {}`, or a single
  // directive: `apps/admin/src/app/globals.css` is one `@import "tailwindcss"`.
  if (body.length <= 2) return true

  return false
}

/**
 * Files the project has that no template produces.
 *
 * The third of the three lists, and the one that did not exist. Nothing in the
 * generator could answer "what is here that upstream has never seen", which is
 * the question the promotion backlog is made of: `koras-control-plane` has
 * roughly 291 such files, and every one of that count was produced by hand
 * from shell pipelines, which is why the survey happened once.
 *
 * Tracked files only, via `git ls-files`. A filesystem walk would have to
 * re-implement `.gitignore` to avoid reporting `.venv`, `.next` and every
 * build output as a promotion candidate, and the project is a git repository
 * by construction -- the generator runs `git init` in it. Where git is absent
 * or the directory is not a repository, the list is skipped and said to be
 * skipped, rather than being silently empty and read as "nothing to promote".
 */
function repoOnlyFiles(projectRoot: string, rendered: Set<string>): string[] | undefined {
  let tracked: string
  try {
    tracked = execFileSync('git', ['ls-files', '-z'], {
      cwd: projectRoot,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
      maxBuffer: 64 * 1024 * 1024,
    })
  } catch {
    return undefined
  }

  return tracked
    .split('\0')
    .filter((path) => path !== '' && !rendered.has(path))
    .sort()
}

/**
 * A directory rollup, because 291 paths is not a list anybody reads.
 *
 * Grouped two segments deep where there are two -- `services/api`,
 * `packages/ui` -- so the answer to "what has this project grown" is legible
 * at a glance and the per-file detail stays available behind `--verbose`.
 */
function rollUp(paths: string[]): Array<{ scope: string; count: number }> {
  const counts = new Map<string, number>()
  for (const path of paths) {
    const segments = path.split('/')
    const scope =
      segments.length === 1
        ? '(root)'
        : segments.slice(0, segments.length > 2 ? 2 : 1).join('/')
    counts.set(scope, (counts.get(scope) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([scope, count]) => ({ scope, count }))
    .sort((a, b) => b.count - a.count || a.scope.localeCompare(b.scope))
}

/**
 * Absent is not the same as edited, and is checked everywhere rather than only
 * across the reviewable set.
 *
 * The reason the content comparison is narrow is that a healthy project edits
 * application code constantly, so a diff there says nothing. None of that
 * applies to a file the generator would write and the project does not have:
 * people change `apps/web/src/app/page.tsx`, they do not delete
 * `apps/admin/next.config.ts`. The renderer already respects the project's
 * selections, so a disabled component is never rendered and never missing.
 *
 * This was added because `apps/admin/next.config.ts` was absent from a
 * generated product for four days. The application was enabled, `apps/web` had
 * its config, and every drift run reported the project as matching -- `apps/`
 * was in neither path set, so nothing looked. A project generated before a file
 * was added to the template never receives it: `--refresh-modules` only touches
 * declared shared assets, and that is the whole class this catches.
 *
 * A file the project renamed is not that. `koras-control-plane` moved its API
 * from `services/api/src/core/` to `services/api/koras_api/core/` and its Next
 * configs from `.ts` to `.mjs`, and the first version of this check reported
 * sixteen of those as files the project "never received" -- the opposite of
 * true, and enough noise to bury the four findings that were real. So a
 * basename found elsewhere under the same top-level directory is reported as a
 * probable rename, separately and without the accusation.
 */
function missingRenderedFiles(
  rendered: Map<string, unknown>,
  projectRoot: string,
): DriftFinding[] {
  const findings: DriftFinding[] = []
  for (const path of rendered.keys()) {
    if (existsSync(join(projectRoot, path))) continue

    const moved = findRenamed(projectRoot, path)
    findings.push({
      subject: path,
      detail: moved
        ? `Not at this path; the project has ${moved}. Probably a rename rather ` +
          'than a gap, but the generator will keep writing the original path, so ' +
          'the two will diverge until the template follows or the project does.'
        : 'Missing from the project. The generator would write it and the component ' +
          'it belongs to is enabled, so this is a file the project never received ' +
          'rather than one it chose not to have.',
    })
  }
  return findings
}

/**
 * The same basename somewhere else under the same top-level directory.
 *
 * Scoped to the component the file belongs to -- `apps/portal`, `services/api`
 * -- rather than to `apps` or to the whole tree. `__init__.py` and `index.ts`
 * appear everywhere, and a wider search reported `apps/portal/next.config.ts`
 * as renamed to `apps/admin/next.config.mjs`: a real file, the wrong component,
 * and a confident sentence about it. Stem-only matching covers an extension
 * change, which is how `next.config.ts` became `next.config.mjs`.
 */
function findRenamed(projectRoot: string, path: string): string | undefined {
  const segments = path.split('/')
  if (segments.length < 2) return undefined

  // Two segments where there are two: `apps/portal` and `services/api` are
  // components, `apps` is a category.
  const scope = segments.length > 2 ? segments.slice(0, 2) : segments.slice(0, 1)
  const name = segments[segments.length - 1]
  const stem = name.replace(/\.[^.]+$/, '')
  const root = join(projectRoot, ...scope)
  if (!existsSync(root)) return undefined

  const SKIP = new Set(['node_modules', '.next', '.turbo', '.venv', 'dist', '.git'])
  const found: string[] = []

  const walk = (directory: string, depth: number): void => {
    if (depth > 6 || found.length > 0) return
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (SKIP.has(entry.name)) continue
      const full = join(directory, entry.name)
      if (entry.isDirectory()) walk(full, depth + 1)
      else if (entry.name === name || entry.name.replace(/\.[^.]+$/, '') === stem) {
        found.push(relative(projectRoot, full).split(sep).join('/'))
        return
      }
    }
  }
  walk(root, 0)
  return found[0]
}

export interface DriftFinding {
  /** What disagrees, as a path or a short identifier. */
  subject: string
  detail: string
}

export interface DriftReport {
  findings: DriftFinding[]
  /** True when the manifest predates the components field, so selections are unverifiable. */
  selectionsUnknown: boolean
  /** Populated only with `--all`. Informational: never affects the exit code. */
  reviewable: DriftFinding[]
  /**
   * Files the project has that no template produces — the promotion queue.
   * `undefined` means it could not be established (not a git repository, or no
   * git on PATH), which is not the same as empty and is reported differently.
   */
  repoOnly?: string[]
  /**
   * Whether the repo-only list was attempted at all. Distinct from `repoOnly`
   * being `undefined`, which means it was attempted and could not be
   * established -- a difference the report has to keep, or "not a git
   * repository" renders as silence and reads as "nothing to promote".
   */
  repoOnlyChecked: boolean
  /**
   * Template scaffolds the project has replaced with a real implementation.
   * Counted rather than listed: this is the healthy case, and naming forty of
   * them is how the findings that matter get buried.
   */
  scaffoldsReplaced: number
}

/**
 * Summarises how two versions of a file differ, or undefined when they do not.
 *
 * Line endings are normalised first: a project checked out on Windows carries
 * CRLF while the renderer emits LF, and reporting every line as changed teaches
 * the operator to ignore the check.
 *
 * A bare "differs" is nearly as useless. What an operator needs is which lines
 * the generator would add — that is what distinguishes a missing provider block
 * from a cosmetic edit.
 */
function describeDifference(actual: string, expected: string): string | undefined {
  const lines = (t: string): string[] => t.replace(/\r\n/g, '\n').trimEnd().split('\n')

  const have = lines(actual)
  const want = lines(expected)
  if (have.join('\n') === want.join('\n')) return undefined

  const haveSet = new Set(have.map((l) => l.trim()))
  const wantSet = new Set(want.map((l) => l.trim()))

  const missing = want.filter((l) => l.trim() !== '' && !haveSet.has(l.trim()))
  const extra = have.filter((l) => l.trim() !== '' && !wantSet.has(l.trim()))

  const parts: string[] = []
  if (missing.length > 0) parts.push(`${missing.length} line(s) the generator would add`)
  if (extra.length > 0) parts.push(`${extra.length} line(s) only in the project`)

  const sample = missing.slice(0, 3).map((l) => `      + ${l.trim()}`)
  if (missing.length > sample.length) {
    sample.push(`      + ... and ${missing.length - sample.length} more`)
  }

  return [`${parts.join(', ')}.`, ...sample].join('\n')
}

export function checkDrift(
  ctx: GenerationContext,
  projectRoot: string,
  options: { all?: boolean } = {},
): DriftReport {
  const findings: DriftFinding[] = []
  const reviewable: DriftFinding[] = []

  // ── The manifest, which is what makes the rest trustworthy ────────────────

  const manifestPath = join(projectRoot, PROJECT_MANIFEST_PATH)
  let selectionsUnknown = true

  if (!existsSync(manifestPath)) {
    findings.push({
      subject: PROJECT_MANIFEST_PATH,
      detail: 'Missing. This project cannot be identified by KORAS tooling.',
    })
  } else {
    const manifest = parseProjectManifest(readFileSync(manifestPath, 'utf8'), PROJECT_MANIFEST_PATH)

    if (manifest.project.profile !== ctx.profile) {
      findings.push({
        subject: PROJECT_MANIFEST_PATH,
        detail:
          `Records profile "${manifest.project.profile}", but "${ctx.profile}" was requested.`,
      })
    }

    // The profile tree this project came from, compared against the one on
    // disk now. `starter_version` cannot answer this: it reads a release number
    // out of package.json, and across every change the starter made in its
    // first weeks it stayed at 0.1.0 — so a project generated a month earlier
    // was indistinguishable from a current one.
    //
    // A digest mismatch is not itself a defect. It says the definition moved,
    // which is why it is reported alongside what actually differs rather than
    // instead of it. Absent, the manifest predates the field, and that is worth
    // saying once rather than treating as a match.
    const expectedDigest = resolveTemplateDigest(ctx.profile)
    if (manifest.generator.template_digest === undefined) {
      findings.push({
        subject: PROJECT_MANIFEST_PATH,
        detail:
          'No `template_digest` — written by an older starter, so how far this ' +
          'project has fallen behind the profile cannot be established from the ' +
          'manifest alone. Regenerating it records the current one.',
      })
    } else if (manifest.generator.template_digest !== expectedDigest) {
      findings.push({
        subject: `${PROJECT_MANIFEST_PATH} template_digest`,
        detail:
          `Generated from profile "${ctx.profile}" at ${manifest.generator.template_digest.slice(0, 12)}, ` +
          `which is now ${expectedDigest.slice(0, 12)}. The profile has changed since ` +
          'this project was generated; the files below say whether any of it reached here.',
      })
    }

    if (manifest.components) {
      selectionsUnknown = false
      findings.push(...compareSelections(manifest.components, projectRoot))
    } else {
      findings.push({
        subject: PROJECT_MANIFEST_PATH,
        detail:
          'No `components:` block — written by an older starter. Until it is backfilled, ' +
          'the selections this project was generated with cannot be verified.',
      })
    }
  }

  // ── Generator-owned Terraform config ──────────────────────────────────────

  const rendered = new Map(renderTemplate(ctx).map((f) => [f.outputPath, f.content]))

  findings.push(...missingRenderedFiles(rendered, projectRoot))

  for (const path of OWNED_PATHS) {
    const expected = rendered.get(path)
    if (expected === undefined) continue

    // Absence is already reported by missingRenderedFiles, for every rendered
    // file rather than only these four. Reporting it twice would make the count
    // in the header disagree with the list under it.
    const actualPath = join(projectRoot, path)
    if (!existsSync(actualPath)) continue

    const difference = describeDifference(readFileSync(actualPath, 'utf8'), expected.toString())
    if (difference) {
      findings.push({ subject: path, detail: difference })
    }
  }

  let scaffoldsReplaced = 0

  if (options.all) {
    for (const [path, expected] of rendered) {
      if (OWNED_PATHS.includes(path)) continue
      const actualPath = join(projectRoot, path)
      // Missing files are a finding, not a review note; see missingRenderedFiles.
      if (!existsSync(actualPath)) continue

      const template = expected.toString()
      const difference = describeDifference(readFileSync(actualPath, 'utf8'), template)
      if (!difference) continue

      // The project filling in a placeholder is the system working. Counted so
      // the number is visible, not listed so it drowns the rest.
      if (isScaffold(template)) {
        scaffoldsReplaced += 1
        continue
      }
      reviewable.push({ subject: path, detail: difference })
    }
  }

  const repoOnly = options.all ? repoOnlyFiles(projectRoot, new Set(rendered.keys())) : undefined

  return {
    findings,
    selectionsUnknown,
    reviewable,
    repoOnly,
    repoOnlyChecked: options.all ?? false,
    scaffoldsReplaced,
  }
}

/**
 * The manifest and `terraform.tfvars` must agree on which components are on.
 *
 * They are separate records of the same fact, and tfvars is an input an operator
 * can edit. A rename applied to one and not the other changes a Terraform
 * `for_each` key, which reads as destroy-and-recreate rather than as a rename.
 */
function compareSelections(
  components: NonNullable<import('./project-manifest.js').KorasProjectManifest['components']>,
  projectRoot: string,
): DriftFinding[] {
  const tfvarsPath = join(projectRoot, 'infrastructure/terraform/terraform.tfvars')
  if (!existsSync(tfvarsPath)) return []

  const onDisk = readProjectTfvars(readFileSync(tfvarsPath, 'utf8'))
  const findings: DriftFinding[] = []

  const compare = (label: string, manifestValue: string[], tfvarsValue?: string[]): void => {
    if (tfvarsValue === undefined) return
    const a = [...manifestValue].sort()
    const b = [...tfvarsValue].sort()
    if (a.join(',') !== b.join(',')) {
      findings.push({
        subject: `terraform.tfvars ${label}`,
        detail:
          `Manifest records [${a.join(', ')}], terraform.tfvars enables [${b.join(', ')}]. ` +
          'A component key is a Terraform for_each key: changing one without the other ' +
          'plans a destroy, not a rename.',
      })
    }
  }

  compare('enabled_apps', components.applications, onDisk.enabledApps)
  compare('enabled_services', components.services, onDisk.enabledServices)
  return findings
}

/**
 * The `--all` sections, kept visually separate and never counted as a failure.
 *
 * A replaced stub and a missing fix look identical to a content comparison, so
 * these are for a human to read when drift is already suspected.
 *
 * Ordered by how many lines the generator would add, descending. That is the
 * direction that means the project is behind, and it is the only ordering that
 * puts the file worth opening at the top: a hand survey ranked by total diff
 * size instead and led with `koras-auth/__init__.py` at "312 lines changed",
 * where the real difference was one line of indentation and the rest was CRLF.
 */
function templateAddedCount(detail: string): number {
  const match = /^(\d+) line\(s\) the generator would add/.exec(detail)
  return match ? Number(match[1]) : 0
}

function formatReviewable(report: DriftReport): string[] {
  if (report.reviewable.length === 0) return []

  const ordered = [...report.reviewable].sort(
    (a, b) => templateAddedCount(b.detail) - templateAddedCount(a.detail),
  )
  const behind = ordered.filter((f) => templateAddedCount(f.detail) > 0).length

  const lines = [
    '',
    `DRIFTED — ${report.reviewable.length} file(s) the template also ships differ` +
      `${behind > 0 ? `, ${behind} with lines the generator would add` : ''}` +
      ' — for review, not failure:',
    '',
  ]
  for (const finding of ordered) {
    lines.push(`  ${finding.subject}`)
    lines.push(`    ${finding.detail}`)
  }
  lines.push('')
  lines.push('A healthy project edits most of these: a workflow replaces a stub with a real')
  lines.push('pipeline, terraform.tfvars holds values where the template holds placeholders.')
  lines.push('Read them; do not gate on them. Those listed first are the ones where the')
  lines.push('generator has lines the project does not, which is the direction worth reading.')
  return lines
}

/**
 * The promotion queue, as a rollup.
 *
 * Deliberately not a file list. The number this replaces was 291, produced by
 * hand once, and a 291-line block appended to every nightly run is a block
 * nobody reads twice.
 */
function formatRepoOnly(report: DriftReport, verbose: boolean): string[] {
  if (report.repoOnly === undefined) {
    return [
      '',
      'REPO-ONLY — not established. The project is not a git repository, or git is',
      'not on PATH. That is not the same as having nothing to promote.',
    ]
  }
  if (report.repoOnly.length === 0) {
    return ['', 'REPO-ONLY — none. Every tracked file in the project comes from a template.']
  }

  const lines = [
    '',
    `REPO-ONLY — ${report.repoOnly.length} tracked file(s) exist here and in no template:`,
    '',
  ]
  for (const { scope, count } of rollUp(report.repoOnly)) {
    lines.push(`  ${String(count).padStart(4)}  ${scope}`)
  }
  lines.push('')
  if (verbose) {
    for (const path of report.repoOnly) lines.push(`    ${path}`)
  } else {
    lines.push('  (--verbose lists them individually)')
  }
  lines.push('')
  lines.push('Most of this is correct and belongs only here — a profile ships a starting')
  lines.push('point, not a finished product. The question this list exists to make cheap is')
  lines.push('which of it is profile-agnostic and should have gone upstream.')
  return lines
}

function formatScaffolds(report: DriftReport): string[] {
  if (report.scaffoldsReplaced === 0) return []
  return [
    '',
    `${report.scaffoldsReplaced} template scaffold(s) replaced by real implementations — not drift.`,
  ]
}

export function formatDriftReport(
  report: DriftReport,
  projectSlug: string,
  options: { verbose?: boolean } = {},
): string {
  const lines: string[] = []

  if (report.findings.length === 0) {
    lines.push(`\n✓ ${projectSlug} matches what the generator would produce for it.`)
  } else {
    lines.push('')
    lines.push(
      `TEMPLATE-ONLY / MANIFEST — ${report.findings.length} difference(s) between ` +
        `${projectSlug}/ and the starter:`,
    )
    lines.push('')
    for (const finding of report.findings) {
      lines.push(`  ${finding.subject}`)
      lines.push(`    ${finding.detail}`)
    }
    lines.push('')
    lines.push('Shared Terraform modules can be updated with --refresh-modules.')
    lines.push('The root config is rendered from the profile template and is not a shared')
    lines.push('asset, so differences there are reconciled by hand — deliberately, since a')
    lines.push('project may have edited them for a reason.')
  }

  lines.push(...formatReviewable(report))
  lines.push(...formatScaffolds(report))
  if (report.repoOnlyChecked) {
    lines.push(...formatRepoOnly(report, options.verbose ?? false))
  }
  return lines.join('\n')
}
