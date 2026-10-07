import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import yaml from 'js-yaml'

/**
 * Framework baseline drift: is a product's recorded Starter baseline behind
 * the Starter's accepted one?
 *
 * Read-only and offline-first. It needs a Starter checkout (with the product's
 * baseline commit in its history) and the product's `.koras/project.yaml`.
 * It never upgrades anything. It reports; whether a result fails a command
 * is the caller's `--strict` decision.
 */

export const ACCEPTED_BASELINE_PATH = 'docs/framework-baseline.yaml'
export const PROJECT_MANIFEST_PATH = '.koras/project.yaml'

export type BaselineStatus = 'current' | 'behind' | 'ahead' | 'diverged' | 'unknown'

export interface BaselineReport {
  status: BaselineStatus
  accepted: string
  recorded?: string
  /** Commits the accepted baseline has that the product lacks (behind), or the reverse (ahead). */
  commits?: number
  /** Framework-relevant paths that changed between the two. Only for behind. */
  changedPaths?: string[]
  reason?: string
}

/** A misconfiguration of the check itself, as opposed to a finding about a product. */
export class BaselineUsageError extends Error {}

export type GitRunner = (starterPath: string, args: string[]) => { code: number; stdout: string }

export const runGit: GitRunner = (starterPath, args) => {
  const result = spawnSync('git', ['-C', starterPath, ...args], { encoding: 'utf8' })
  return { code: result.status ?? 1, stdout: result.stdout ?? '' }
}

const SHA_RE = /^[0-9a-f]{7,40}$/i

function loadYaml(path: string): unknown {
  try {
    return yaml.load(readFileSync(path, 'utf8'))
  } catch (err) {
    throw new BaselineUsageError(`Cannot read ${path}: ${err instanceof Error ? err.message : String(err)}`)
  }
}

export function readAcceptedBaseline(starterPath: string): string {
  const file = join(starterPath, ACCEPTED_BASELINE_PATH)
  if (!existsSync(file)) throw new BaselineUsageError(`${file} not found; is --starter-path a Starter checkout?`)
  const raw = loadYaml(file) as { accepted_baseline?: unknown } | null
  const sha = raw?.accepted_baseline
  if (typeof sha !== 'string' || !SHA_RE.test(sha)) {
    throw new BaselineUsageError(`${file}: accepted_baseline must be a commit SHA`)
  }
  return sha
}

/** The product's recorded baseline, or no sha with the reason it is not there. */
export function readRecordedBaseline(productPath: string): { sha?: string; profile?: string; reason?: string } {
  const file = join(productPath, PROJECT_MANIFEST_PATH)
  if (!existsSync(file)) throw new BaselineUsageError(`${file} not found; is --product-path a generated product?`)
  // Parsed directly rather than through create-koras-app's manifest schema,
  // which strips fields it does not declare, the hand-maintained framework
  // block among them.
  const raw = loadYaml(file) as {
    project?: { profile?: string }
    framework?: { source_baseline?: unknown }
  } | null
  const profile = raw?.project?.profile
  const sha = raw?.framework?.source_baseline
  if (sha === undefined || sha === null) {
    return { profile, reason: 'no framework.source_baseline recorded in .koras/project.yaml' }
  }
  if (typeof sha !== 'string' || !SHA_RE.test(sha)) {
    return { profile, reason: 'framework.source_baseline is not a commit SHA (quote it in YAML if it is all digits)' }
  }
  return { sha, profile }
}

/** Starter paths whose change can reach a product: the profile trees and the profile's declared shared assets. */
function frameworkPathspecs(starterPath: string, profile: string | undefined): string[] {
  const specs = ['profiles/']
  if (!profile) return specs
  const manifest = join(starterPath, 'profiles', profile, 'manifest.yaml')
  if (!existsSync(manifest)) return specs
  try {
    const raw = yaml.load(readFileSync(manifest, 'utf8')) as {
      shared_assets?: Array<{ source?: unknown }>
    } | null
    for (const asset of raw?.shared_assets ?? []) {
      if (typeof asset?.source === 'string') specs.push(asset.source)
    }
  } catch {
    // The profile loader reports a malformed manifest far better than this can.
  }
  return specs
}

export function checkBaseline(
  starterPath: string,
  productPath: string,
  git: GitRunner = runGit,
): BaselineReport {
  const accepted = readAcceptedBaseline(starterPath)
  const acceptedResolved = git(starterPath, ['rev-parse', '--verify', '--quiet', `${accepted}^{commit}`])
  if (acceptedResolved.code !== 0) {
    throw new BaselineUsageError(
      `Accepted baseline ${accepted} does not resolve in ${starterPath}; fetch the Starter full history.`,
    )
  }
  const acceptedSha = acceptedResolved.stdout.trim()

  const recorded = readRecordedBaseline(productPath)
  if (!recorded.sha) {
    return { status: 'unknown', accepted: acceptedSha, reason: recorded.reason }
  }
  const recordedResolved = git(starterPath, ['rev-parse', '--verify', '--quiet', `${recorded.sha}^{commit}`])
  if (recordedResolved.code !== 0) {
    return {
      status: 'unknown',
      accepted: acceptedSha,
      recorded: recorded.sha,
      reason: 'recorded baseline is not in the Starter checkout (not fetched, or not a Starter commit)',
    }
  }
  const recordedSha = recordedResolved.stdout.trim()
  const base = { accepted: acceptedSha, recorded: recordedSha }

  if (recordedSha === acceptedSha) return { status: 'current', ...base }

  const isAncestor = (a: string, b: string): boolean =>
    git(starterPath, ['merge-base', '--is-ancestor', a, b]).code === 0
  const count = (range: string): number =>
    Number.parseInt(git(starterPath, ['rev-list', '--count', range]).stdout.trim(), 10)

  if (isAncestor(recordedSha, acceptedSha)) {
    const diff = git(starterPath, [
      'diff',
      '--name-only',
      recordedSha,
      acceptedSha,
      '--',
      ...frameworkPathspecs(starterPath, recorded.profile),
    ])
    const changedPaths = diff.stdout.split('\n').map((l) => l.trim()).filter(Boolean)
    return { status: 'behind', ...base, commits: count(`${recordedSha}..${acceptedSha}`), changedPaths }
  }
  if (isAncestor(acceptedSha, recordedSha)) {
    return { status: 'ahead', ...base, commits: count(`${acceptedSha}..${recordedSha}`) }
  }
  return { status: 'diverged', ...base, reason: 'neither baseline is an ancestor of the other' }
}

const MAX_PATHS = 25

export function formatBaselineReport(report: BaselineReport): string {
  const short = (s?: string): string => (s ? s.slice(0, 12) : '-')
  const lines = [`framework baseline: ${report.status.toUpperCase()}`]
  lines.push(`  product recorded: ${short(report.recorded)}`, `  starter accepted: ${short(report.accepted)}`)
  if (report.status === 'behind') {
    const paths = report.changedPaths ?? []
    lines.push(`  behind by ${report.commits} commit(s); ${paths.length} framework-relevant path(s) changed:`)
    lines.push(...paths.slice(0, MAX_PATHS).map((p) => `    ${p}`))
    if (paths.length > MAX_PATHS) lines.push(`    ... and ${paths.length - MAX_PATHS} more`)
    lines.push('  Informational: adopt deliberately (targeted sync), then update framework.source_baseline.')
  } else if (report.status === 'ahead') {
    lines.push(`  product is ahead of the accepted baseline by ${report.commits} commit(s).`)
  } else if (report.reason) {
    lines.push(`  ${report.reason}`)
  }
  return lines.join('\n')
}

/** Exit code: 0 unless --strict and the product is not current. Ahead is not a failure. */
export function exitCodeFor(report: BaselineReport, strict: boolean): number {
  if (!strict) return 0
  return report.status === 'current' || report.status === 'ahead' ? 0 : 1
}