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
import { refreshSharedAssets, formatRefreshResult } from '../src/generation/refresh.js'

const ROOT = join(tmpdir(), `koras-refresh-${process.pid}-${Date.now()}`)

beforeEach(() => mkdirSync(ROOT, { recursive: true }))
afterEach(() => { if (existsSync(ROOT)) rmSync(ROOT, { recursive: true, force: true }) })

/** Generates a project the way the CLI does, and returns its root. */
function generate(profile: ProfileName, slug: string, dryRun = false) {
  const { manifest, defaults } = loadProfile(profile)
  const ctx = buildContext({
    projectName: slug,
    projectSlug: slug,
    profile,
    manifest,
    defaults,
    selections: resolveSelections(manifest, defaults),
    outputDir: ROOT,
    dryRun,
    provision: false,
  })
  writeFiles(ctx, renderTemplate(ctx))
  return { ctx, projectRoot: join(ROOT, slug) }
}

const A_MODULE_FILE = 'infrastructure/terraform/modules/upstash/main.tf'

describe('refreshSharedAssets', () => {
  it('reports nothing to do for a project just generated', () => {
    const { ctx, projectRoot } = generate('product', 'fresh')
    const result = refreshSharedAssets(ctx, projectRoot)

    expect(result.changed).toEqual([])
    expect(result.unchanged).toBeGreaterThan(0)
    expect(result.written).toBe(false)
    expect(formatRefreshResult(result)).toContain('already up to date')
  })

  it('restores a module the project had drifted from', () => {
    // The situation this exists for: a module fixed in the starter after the
    // project was generated, which --provision-only would silently plan against.
    const { ctx, projectRoot } = generate('product', 'stale')
    const target = join(projectRoot, A_MODULE_FILE)
    const pristine = readFileSync(target, 'utf8')
    writeFileSync(target, '# stale copy\n')

    const result = refreshSharedAssets(ctx, projectRoot)

    expect(result.changed).toEqual([A_MODULE_FILE])
    expect(result.written).toBe(true)
    expect(readFileSync(target, 'utf8')).toBe(pristine)
  })

  it('restores a module file that was deleted outright', () => {
    const { ctx, projectRoot } = generate('product', 'deleted')
    const target = join(projectRoot, A_MODULE_FILE)
    rmSync(target)

    const result = refreshSharedAssets(ctx, projectRoot)

    expect(result.changed).toContain(A_MODULE_FILE)
    expect(existsSync(target)).toBe(true)
  })

  it('touches nothing outside the declared shared assets', () => {
    // Everything else in a generated project belongs to whoever owns it.
    const { ctx, projectRoot } = generate('product', 'scoped')
    const owned = join(projectRoot, 'apps/web/src/app/page.tsx')
    writeFileSync(owned, '// hand-edited\n')
    const tfvars = join(projectRoot, 'infrastructure/terraform/terraform.tfvars')
    const tfvarsBefore = readFileSync(tfvars, 'utf8')

    const result = refreshSharedAssets(ctx, projectRoot)

    expect(readFileSync(owned, 'utf8')).toBe('// hand-edited\n')
    expect(readFileSync(tfvars, 'utf8')).toBe(tfvarsBefore)
    for (const path of result.changed) {
      expect(path.startsWith('infrastructure/terraform/modules/')).toBe(true)
    }
  })

  it('lists without writing under --dry-run', () => {
    const { projectRoot } = generate('product', 'dry')
    const target = join(projectRoot, A_MODULE_FILE)
    writeFileSync(target, '# stale copy\n')

    // Same context, but dry.
    const { manifest, defaults } = loadProfile('product')
    const ctx = buildContext({
      projectName: 'dry', projectSlug: 'dry', profile: 'product', manifest, defaults,
      selections: resolveSelections(manifest, defaults),
      outputDir: ROOT, dryRun: true, provision: false,
    })

    const result = refreshSharedAssets(ctx, projectRoot)

    expect(result.changed).toEqual([A_MODULE_FILE])
    expect(result.written).toBe(false)
    expect(readFileSync(target, 'utf8')).toBe('# stale copy\n')
    expect(formatRefreshResult(result)).toContain('nothing was written')
  })

  it('works for both profiles', () => {
    for (const [profile, slug] of [
      ['product', 'both-product'],
      ['control-plane', 'both-cp'],
    ] as Array<[ProfileName, string]>) {
      const { ctx, projectRoot } = generate(profile, slug)
      expect(refreshSharedAssets(ctx, projectRoot).unchanged).toBeGreaterThan(0)
    }
  })
})
