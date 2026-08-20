import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
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

function generate(profile: ProfileName, slug: string) {
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
  writeFiles(ctx, renderTemplate(ctx))
  return { ctx, projectRoot: join(ROOT, slug) }
}

describe('checkDrift', () => {
  it('reports nothing for a project the generator just wrote', () => {
    for (const [profile, slug] of [
      ['product', 'fresh-product'],
      ['control-plane', 'fresh-cp'],
    ] as Array<[ProfileName, string]>) {
      const { ctx, projectRoot } = generate(profile, slug)
      const report = checkDrift(ctx, projectRoot)

      expect(report.findings).toEqual([])
      expect(report.selectionsUnknown).toBe(false)
      expect(formatDriftReport(report, slug)).toContain('matches what the generator would produce')
    }
  })

  it('names the lines a stale root config is missing', () => {
    // The failure this exists for: a provider block added to the starter after
    // the project was generated, which only surfaces when a plan dies after
    // `init` has already downloaded every provider.
    const { ctx, projectRoot } = generate('product', 'stale-root')
    const providers = join(projectRoot, 'infrastructure/terraform/providers.tf')
    const original = readFileSync(providers, 'utf8')
    writeFileSync(providers, original.replace(/provider "upstash" \{[^}]*\}/, ''))

    const report = checkDrift(ctx, projectRoot)
    const finding = report.findings.find((f) => f.subject.endsWith('providers.tf'))

    expect(finding).toBeDefined()
    expect(finding!.detail).toContain('the generator would add')
    expect(finding!.detail).toContain('upstash')
  })

  it('catches a component key renamed in tfvars but not the manifest', () => {
    // Exactly the koras-control-plane incident: enabled_apps was edited by hand,
    // state kept the old key, and the mismatch only surfaced as a Terraform
    // destroy that prevent_destroy refused.
    const { ctx, projectRoot } = generate('control-plane', 'renamed-key')
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

  it('says selections are unverifiable when the manifest predates the field', () => {
    const { ctx, projectRoot } = generate('product', 'old-manifest')
    const manifestPath = join(projectRoot, PROJECT_MANIFEST_PATH)
    writeFileSync(
      manifestPath,
      readFileSync(manifestPath, 'utf8').replace(/components:[\s\S]*$/, ''),
    )

    const report = checkDrift(ctx, projectRoot)

    expect(report.selectionsUnknown).toBe(true)
    expect(report.findings.some((f) => f.detail.includes('components:'))).toBe(true)
  })

  it('reports a profile the manifest disagrees with', () => {
    const { projectRoot } = generate('product', 'wrong-profile')
    const { manifest, defaults } = loadProfile('control-plane')
    const cpCtx = buildContext({
      projectName: 'wrong-profile', projectSlug: 'wrong-profile', profile: 'control-plane',
      manifest, defaults, selections: resolveSelections(manifest, defaults),
      outputDir: ROOT, dryRun: false, provision: false,
    })

    const report = checkDrift(cpCtx, projectRoot)
    expect(report.findings.some((f) => f.detail.includes('Records profile "product"'))).toBe(true)
  })

  it('writes nothing', () => {
    const { ctx, projectRoot } = generate('product', 'readonly')
    const main = join(projectRoot, 'infrastructure/terraform/main.tf')
    writeFileSync(main, '# emptied\n')

    checkDrift(ctx, projectRoot)

    // A check that repairs what it finds is a refresh wearing a disguise.
    expect(readFileSync(main, 'utf8')).toBe('# emptied\n')
  })

  it('is not confused by CRLF line endings', () => {
    // A project checked out on Windows carries CRLF; the renderer emits LF.
    const { ctx, projectRoot } = generate('product', 'crlf')
    const main = join(projectRoot, 'infrastructure/terraform/main.tf')
    writeFileSync(main, readFileSync(main, 'utf8').replace(/\n/g, '\r\n'))

    expect(checkDrift(ctx, projectRoot).findings).toEqual([])
  })
})

describe('the wider --all scope', () => {
  it('is empty unless asked for', () => {
    const { ctx, projectRoot } = generate('control-plane', 'all-off')
    expect(checkDrift(ctx, projectRoot).reviewable).toEqual([])
  })

  it('never turns a reviewable difference into a failure', () => {
    // A workflow that replaced the template's stub with a real pipeline looks
    // exactly like a workflow missing a fix. Gating on that would train people
    // to ignore the findings that do matter.
    const { ctx, projectRoot } = generate('control-plane', 'all-informational')
    writeFileSync(join(projectRoot, '.github/workflows/ci.yml'), 'name: replaced\n')

    const report = checkDrift(ctx, projectRoot, { all: true })

    expect(report.reviewable.some((f) => f.subject.endsWith('ci.yml'))).toBe(true)
    expect(report.findings).toEqual([])
    expect(formatDriftReport(report, 'all-informational')).toContain('for review, not failure')
  })

  it('does not repeat what the gating scope already reported', () => {
    const { ctx, projectRoot } = generate('product', 'all-nodupes')
    writeFileSync(join(projectRoot, 'infrastructure/terraform/main.tf'), '# emptied\n')

    const report = checkDrift(ctx, projectRoot, { all: true })

    expect(report.findings.some((f) => f.subject.endsWith('main.tf'))).toBe(true)
    expect(report.reviewable.some((f) => f.subject.endsWith('main.tf'))).toBe(false)
  })
})
