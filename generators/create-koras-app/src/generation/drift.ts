import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
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
 * The wider set, compared only when asked for (`--all`) and never counted as a
 * failure.
 *
 * These files are generator-owned in the sense that the template ships them,
 * but a healthy project edits them: workflows grow real deploy steps where the
 * template has a stub, terraform.tfvars holds values where the template holds
 * placeholders, the Makefile gains project targets. Measured against a working
 * project, comparing them flags eighteen files, and most of those are the
 * project being ahead rather than behind -- which no content comparison can
 * distinguish, since a replaced stub and a missing fix look identical.
 *
 * So this is a "show me what has moved" tool for when drift is already
 * suspected, not a gate. Treating it as one would train people to ignore the
 * findings that do matter.
 */
const REVIEWABLE_PREFIXES = ['infrastructure/', 'local/', '.github/']
const REVIEWABLE_FILES = [
  'Makefile',
  'turbo.json',
  'pnpm-workspace.yaml',
  'tsconfig.base.json',
  'eslint.config.mjs',
  '.gitignore',
  '.gitattributes',
]

function isReviewable(path: string): boolean {
  return REVIEWABLE_PREFIXES.some((p) => path.startsWith(p)) || REVIEWABLE_FILES.includes(path)
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
 */
function missingRenderedFiles(
  rendered: Map<string, unknown>,
  projectRoot: string,
): DriftFinding[] {
  const findings: DriftFinding[] = []
  for (const path of rendered.keys()) {
    if (existsSync(join(projectRoot, path))) continue
    findings.push({
      subject: path,
      detail:
        'Missing from the project. The generator would write it and the component ' +
        'it belongs to is enabled, so this is a file the project never received ' +
        'rather than one it chose not to have.',
    })
  }
  return findings
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

  if (options.all) {
    for (const [path, expected] of rendered) {
      if (OWNED_PATHS.includes(path) || !isReviewable(path)) continue
      const actualPath = join(projectRoot, path)
      // Missing files are a finding, not a review note; see missingRenderedFiles.
      if (!existsSync(actualPath)) continue
      const difference = describeDifference(readFileSync(actualPath, 'utf8'), expected.toString())
      if (difference) reviewable.push({ subject: path, detail: difference })
    }
  }

  return { findings, selectionsUnknown, reviewable }
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
 * The `--all` section, kept visually separate and never counted as a failure.
 *
 * A replaced stub and a missing fix look identical to a content comparison, so
 * these are for a human to read when drift is already suspected.
 */
function formatReviewable(report: DriftReport): string[] {
  if (report.reviewable.length === 0) return []

  const lines = [
    '',
    `${report.reviewable.length} generator-owned file(s) differ — for review, not failure:`,
    '',
  ]
  for (const finding of report.reviewable) {
    lines.push(`  ${finding.subject}`)
    lines.push(`    ${finding.detail}`)
  }
  lines.push('')
  lines.push('A healthy project edits most of these: a workflow replaces a stub with a real')
  lines.push('pipeline, terraform.tfvars holds values where the template holds placeholders.')
  lines.push('Read them; do not gate on them.')
  return lines
}

export function formatDriftReport(report: DriftReport, projectSlug: string): string {
  const lines: string[] = []

  if (report.findings.length === 0) {
    lines.push(`\n✓ ${projectSlug} matches what the generator would produce for it.`)
  } else {
    lines.push('')
    lines.push(`${report.findings.length} difference(s) between ${projectSlug}/ and the starter:`)
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
  return lines.join('\n')
}
