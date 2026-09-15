import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFileSync } from 'node:child_process'
import { mkdirSync, rmSync, existsSync, writeFileSync, readFileSync } from 'node:fs'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'
import { writeFiles } from '../src/generation/writer.js'
import { checkDrift, formatDriftReport } from '../src/generation/drift.js'
import { PROJECT_MANIFEST_PATH } from '../src/generation/project-manifest.js'

const ROOT = join(tmpdir(), `koras-drift-${process.pid}-${Date.now()}`)

beforeEach(() => mkdirSync(ROOT, { recursive: true }))
afterEach(() => { if (existsSync(ROOT)) rmSync(ROOT, { recursive: true, force: true }) })

async function generate(profile: ProfileName, slug: string) {
  const { manifest, defaults } = loadProfile(profile)
  const ctx = buildContext({
    projectName: slug,
    projectSlug: slug,
    profile,
    manifest,
    defaults,
    selections: resolveSelections(manifest, defaults),
    outputDir: ROOT,
    dryRun: false,
    provision: false,
  })
  await writeFiles(ctx, renderTemplate(ctx))
  return { ctx, projectRoot: join(ROOT, slug) }
}

describe('checkDrift', () => {
  // The heaviest test in the repository: two whole projects generated and both
  // walked against git. The package's 60-second budget is enough for it on an
  // idle machine and not on a busy one, and a number that depends on what else
  // is running is the number to state here rather than to raise for everything.
  it('reports nothing for a project the generator just wrote', { timeout: 180_000 }, async () => {
    for (const [profile, slug] of [
      ['product', 'fresh-product'],
      ['control-plane', 'fresh-cp'],
    ] as Array<[ProfileName, string]>) {
      const { ctx, projectRoot } = await generate(profile, slug)
      const report = checkDrift(ctx, projectRoot)

      expect(report.findings).toEqual([])
      expect(report.selectionsUnknown).toBe(false)
      expect(formatDriftReport(report, slug)).toContain('matches what the generator would produce')
    }
  })

  it('names the lines a stale root config is missing', async () => {
    // The failure this exists for: a provider block added to the starter after
    // the project was generated, which only surfaces when a plan dies after
    // `init` has already downloaded every provider.
    const { ctx, projectRoot } = await generate('product', 'stale-root')
    const providers = join(projectRoot, 'infrastructure/terraform/providers.tf')
    const original = readFileSync(providers, 'utf8')
    writeFileSync(providers, original.replace(/provider "upstash" \{[^}]*\}/, ''))

    const report = checkDrift(ctx, projectRoot)
    const finding = report.findings.find((f) => f.subject.endsWith('providers.tf'))

    expect(finding).toBeDefined()
    expect(finding!.detail).toContain('the generator would add')
    expect(finding!.detail).toContain('upstash')
  })

  it('catches a component key renamed in tfvars but not the manifest', async () => {
    // Exactly the koras-control-plane incident: enabled_apps was edited by hand,
    // state kept the old key, and the mismatch only surfaced as a Terraform
    // destroy that prevent_destroy refused.
    const { ctx, projectRoot } = await generate('control-plane', 'renamed-key')
    const tfvars = join(projectRoot, 'infrastructure/terraform/terraform.tfvars')
    writeFileSync(
      tfvars,
      readFileSync(tfvars, 'utf8').replace('"platform_admin"', '"admin"'),
    )

    const report = checkDrift(ctx, projectRoot)
    const finding = report.findings.find((f) => f.subject.includes('enabled_apps'))

    expect(finding).toBeDefined()
    expect(finding!.detail).toContain('platform_admin')
    expect(finding!.detail).toContain('for_each')
  })

  it('says selections are unverifiable when the manifest predates the field', async () => {
    const { ctx, projectRoot } = await generate('product', 'old-manifest')
    const manifestPath = join(projectRoot, PROJECT_MANIFEST_PATH)
    writeFileSync(
      manifestPath,
      readFileSync(manifestPath, 'utf8').replace(/components:[\s\S]*$/, ''),
    )

    const report = checkDrift(ctx, projectRoot)

    expect(report.selectionsUnknown).toBe(true)
    expect(report.findings.some((f) => f.detail.includes('components:'))).toBe(true)
  })

  it('reports a profile the manifest disagrees with', async () => {
    const { projectRoot } = await generate('product', 'wrong-profile')
    const { manifest, defaults } = loadProfile('control-plane')
    const cpCtx = buildContext({
      projectName: 'wrong-profile', projectSlug: 'wrong-profile', profile: 'control-plane',
      manifest, defaults, selections: resolveSelections(manifest, defaults),
      outputDir: ROOT, dryRun: false, provision: false,
    })

    const report = checkDrift(cpCtx, projectRoot)
    expect(report.findings.some((f) => f.detail.includes('Records profile "product"'))).toBe(true)
  })

  it('writes nothing', async () => {
    const { ctx, projectRoot } = await generate('product', 'readonly')
    const main = join(projectRoot, 'infrastructure/terraform/main.tf')
    writeFileSync(main, '# emptied\n')

    checkDrift(ctx, projectRoot)

    // A check that repairs what it finds is a refresh wearing a disguise.
    expect(readFileSync(main, 'utf8')).toBe('# emptied\n')
  })

  it('is not confused by CRLF line endings', async () => {
    // A project checked out on Windows carries CRLF; the renderer emits LF.
    const { ctx, projectRoot } = await generate('product', 'crlf')
    const main = join(projectRoot, 'infrastructure/terraform/main.tf')
    //
    // Normalized to LF before converting, rather than converting whatever is
    // there. `.tf` is not in the renderer's unix-line-endings set, so a
    // rendered main.tf carries whatever the *template* had -- and with
    // core.autocrlf=true every template in the working tree is CRLF.
    // Doubling that produced a CR CR LF sequence, which survives
    // normalization as a trailing CR and failed this test for a reason it
    // was not testing. It passed only where the working tree held LF.
    const asLf = readFileSync(main, 'utf8').split(String.fromCharCode(13) + String.fromCharCode(10)).join(String.fromCharCode(10))
    writeFileSync(main, asLf.split(String.fromCharCode(10)).join(String.fromCharCode(13) + String.fromCharCode(10)))

    expect(checkDrift(ctx, projectRoot).findings).toEqual([])
  })
})

describe('the wider --all scope', () => {
  it('is empty unless asked for', async () => {
    const { ctx, projectRoot } = await generate('control-plane', 'all-off')
    expect(checkDrift(ctx, projectRoot).reviewable).toEqual([])
  })

  it('never turns a reviewable difference into a failure', async () => {
    // A workflow that replaced the template's stub with a real pipeline looks
    // exactly like a workflow missing a fix. Gating on that would train people
    // to ignore the findings that do matter.
    const { ctx, projectRoot } = await generate('control-plane', 'all-informational')
    writeFileSync(join(projectRoot, '.github/workflows/ci.yml'), 'name: replaced\n')

    const report = checkDrift(ctx, projectRoot, { all: true })

    expect(report.reviewable.some((f) => f.subject.endsWith('ci.yml'))).toBe(true)
    expect(report.findings).toEqual([])
    expect(formatDriftReport(report, 'all-informational')).toContain('for review, not failure')
  })

  it('does not repeat what the gating scope already reported', async () => {
    const { ctx, projectRoot } = await generate('product', 'all-nodupes')
    writeFileSync(join(projectRoot, 'infrastructure/terraform/main.tf'), '# emptied\n')

    const report = checkDrift(ctx, projectRoot, { all: true })

    expect(report.findings.some((f) => f.subject.endsWith('main.tf'))).toBe(true)
    expect(report.reviewable.some((f) => f.subject.endsWith('main.tf'))).toBe(false)
  })
})

/**
 * The three lists TS-16 asks for: template-only, drifted, repo-only.
 *
 * The first two existed. `repoOnly` did not, and its absence is why the
 * promotion backlog was counted by hand once and never again.
 */
describe('the three lists', () => {
  it('finds nothing repo-only in a project that is only what the generator wrote', async () => {
    const { ctx, projectRoot } = await generate('control-plane', 'three-lists-clean')
    execFileSync('git', ['init', '-q'], { cwd: projectRoot })
    execFileSync('git', ['add', '-A'], { cwd: projectRoot })

    const report = checkDrift(ctx, projectRoot, { all: true })
    expect(report.repoOnly).toEqual([])
    expect(formatDriftReport(report, 'three-lists-clean', {})).toContain('REPO-ONLY — none')
  })

  it('reports a file the project added and no template produces', async () => {
    const { ctx, projectRoot } = await generate('control-plane', 'three-lists-added')
    mkdirSync(join(projectRoot, 'services/api/koras_api/routers'), { recursive: true })
    writeFileSync(join(projectRoot, 'services/api/koras_api/routers/entitlements.py'), 'x = 1\n')
    execFileSync('git', ['init', '-q'], { cwd: projectRoot })
    execFileSync('git', ['add', '-A'], { cwd: projectRoot })

    const report = checkDrift(ctx, projectRoot, { all: true })
    expect(report.repoOnly).toContain('services/api/koras_api/routers/entitlements.py')

    // Rolled up by directory, not listed, unless asked.
    const rolled = formatDriftReport(report, 'three-lists-added', {})
    expect(rolled).toContain('services/api')
    expect(rolled).not.toContain('routers/entitlements.py')
    expect(formatDriftReport(report, 'three-lists-added', { verbose: true })).toContain(
      'services/api/koras_api/routers/entitlements.py',
    )
  })

  /**
   * An untracked file is a build output, not a promotion candidate. Reporting
   * `.next/` and `.venv/` as things to send upstream is how a list of 291
   * becomes a list nobody opens.
   */
  it('ignores untracked files', async () => {
    const { ctx, projectRoot } = await generate('control-plane', 'three-lists-untracked')
    execFileSync('git', ['init', '-q'], { cwd: projectRoot })
    execFileSync('git', ['add', '-A'], { cwd: projectRoot })
    writeFileSync(join(projectRoot, 'not-committed.txt'), 'build output\n')

    const report = checkDrift(ctx, projectRoot, { all: true })
    expect(report.repoOnly).not.toContain('not-committed.txt')
  })

  /**
   * Not a git repository is not the same as nothing to promote, and the
   * difference has to survive into the report or an empty list reads as a
   * clean bill of health.
   */
  it('says so when the repo-only list cannot be established', async () => {
    const { ctx, projectRoot } = await generate('control-plane', 'three-lists-nogit')
    const report = checkDrift(ctx, projectRoot, { all: true })

    expect(report.repoOnly).toBeUndefined()
    expect(formatDriftReport(report, 'three-lists-nogit', {})).toContain('not established')
  })

  /**
   * The scope widening. A file under `services/` was invisible to the old
   * three-prefix allowlist, which is where forty of forty-seven real
   * differences in `koras-control-plane` were living.
   */
  it('compares files outside infrastructure/, local/ and .github/', async () => {
    const { ctx, projectRoot } = await generate('control-plane', 'three-lists-scope')
    const target = join(projectRoot, 'services/api/koras_api/core/settings.py')
    writeFileSync(target, `${readFileSync(target, 'utf8')}\n# edited by the project\n`)

    const report = checkDrift(ctx, projectRoot, { all: true })
    expect(report.reviewable.map((f) => f.subject)).toContain(
      'services/api/koras_api/core/settings.py',
    )
  })

  /**
   * The noise the old allowlist was avoiding, classified out by shape rather
   * than by directory: the template ships `// implement as needed`, the
   * project ships the real module, and that is the system working.
   */
  it('counts a replaced scaffold rather than listing it as drift', async () => {
    const { ctx, projectRoot } = await generate('control-plane', 'three-lists-scaffold')
    const scaffold = join(projectRoot, 'packages/config/src/index.ts')
    expect(readFileSync(scaffold, 'utf8')).toContain('implement as needed')
    writeFileSync(scaffold, 'export const config = { real: true }\n')

    const report = checkDrift(ctx, projectRoot, { all: true })
    expect(report.reviewable.map((f) => f.subject)).not.toContain('packages/config/src/index.ts')
    expect(report.scaffoldsReplaced).toBeGreaterThan(0)
  })
})
