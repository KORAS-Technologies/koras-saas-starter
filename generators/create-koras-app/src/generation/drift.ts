import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { GenerationContext } from './context.js'
import { renderTemplate } from './engine.js'
import { PROJECT_MANIFEST_PATH, parseProjectManifest } from './project-manifest.js'
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

/** Generator-owned files worth comparing. Everything else belongs to the project. */
const OWNED_PATHS = [
  'infrastructure/terraform/providers.tf',
  'infrastructure/terraform/variables.tf',
  'infrastructure/terraform/main.tf',
  'infrastructure/terraform/backend.tf',
]

export interface DriftFinding {
  /** What disagrees, as a path or a short identifier. */
  subject: string
  detail: string
}

export interface DriftReport {
  findings: DriftFinding[]
  /** True when the manifest predates the components field, so selections are unverifiable. */
  selectionsUnknown: boolean
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

export function checkDrift(ctx: GenerationContext, projectRoot: string): DriftReport {
  const findings: DriftFinding[] = []

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

  for (const path of OWNED_PATHS) {
    const expected = rendered.get(path)
    if (expected === undefined) continue

    const actualPath = join(projectRoot, path)
    if (!existsSync(actualPath)) {
      findings.push({ subject: path, detail: 'Missing from the project.' })
      continue
    }

    const difference = describeDifference(readFileSync(actualPath, 'utf8'), expected.toString())
    if (difference) {
      findings.push({ subject: path, detail: difference })
    }
  }

  return { findings, selectionsUnknown }
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

export function formatDriftReport(report: DriftReport, projectSlug: string): string {
  if (report.findings.length === 0) {
    return `\n✓ ${projectSlug} matches what the generator would produce for it.`
  }

  const lines = [
    '',
    `${report.findings.length} difference(s) between ${projectSlug}/ and the starter:`,
    '',
  ]
  for (const finding of report.findings) {
    lines.push(`  ${finding.subject}`)
    lines.push(`    ${finding.detail}`)
  }
  lines.push('')
  lines.push('Shared Terraform modules can be updated with --refresh-modules.')
  lines.push('The root config is rendered from the profile template and is not a shared')
  lines.push('asset, so differences there are reconciled by hand — deliberately, since a')
  lines.push('project may have edited them for a reason.')
  return lines.join('\n')
}
