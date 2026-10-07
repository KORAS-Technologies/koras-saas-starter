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
import {
  refreshSharedAssets,
  formatRefreshResult,
  refreshRenderedPaths,
  formatRefreshPathResult,
  preserveFrameworkBlock,
} from '../src/generation/refresh.js'
import { collectSharedAssets } from '../src/generation/engine.js'

const ROOT = join(tmpdir(), `koras-refresh-${process.pid}-${Date.now()}`)

beforeEach(() => mkdirSync(ROOT, { recursive: true }))
afterEach(() => { if (existsSync(ROOT)) rmSync(ROOT, { recursive: true, force: true }) })

/** Generates a project the way the CLI does, and returns its root. */
async function generate(profile: ProfileName, slug: string, dryRun = false) {
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
  await writeFiles(ctx, renderTemplate(ctx))
  return { ctx, projectRoot: join(ROOT, slug) }
}

const A_MODULE_FILE = 'infrastructure/terraform/modules/upstash/main.tf'

describe('refreshSharedAssets', () => {
  it('reports nothing to do for a project just generated', async () => {
    const { ctx, projectRoot } = await generate('product', 'fresh')
    const result = await refreshSharedAssets(ctx, projectRoot)

    expect(result.changed).toEqual([])
    expect(result.unchanged).toBeGreaterThan(0)
    expect(result.written).toBe(false)
    expect(formatRefreshResult(result)).toContain('already up to date')
  })

  it('restores a module the project had drifted from', async () => {
    // The situation this exists for: a module fixed in the starter after the
    // project was generated, which --provision-only would silently plan against.
    const { ctx, projectRoot } = await generate('product', 'stale')
    const target = join(projectRoot, A_MODULE_FILE)
    const pristine = readFileSync(target, 'utf8')
    writeFileSync(target, '# stale copy\n')

    const result = await refreshSharedAssets(ctx, projectRoot)

    expect(result.changed).toEqual([A_MODULE_FILE])
    expect(result.written).toBe(true)
    expect(readFileSync(target, 'utf8')).toBe(pristine)
  })

  it('restores a module file that was deleted outright', async () => {
    const { ctx, projectRoot } = await generate('product', 'deleted')
    const target = join(projectRoot, A_MODULE_FILE)
    rmSync(target)

    const result = await refreshSharedAssets(ctx, projectRoot)

    expect(result.changed).toContain(A_MODULE_FILE)
    expect(existsSync(target)).toBe(true)
  })

  it('touches nothing outside the declared shared assets', async () => {
    // Everything else in a generated project belongs to whoever owns it.
    const { ctx, projectRoot } = await generate('product', 'scoped')
    const owned = join(projectRoot, 'apps/web/src/app/page.tsx')
    writeFileSync(owned, '// hand-edited\n')
    const tfvars = join(projectRoot, 'infrastructure/terraform/terraform.tfvars')
    const tfvarsBefore = readFileSync(tfvars, 'utf8')

    const result = await refreshSharedAssets(ctx, projectRoot)

    expect(readFileSync(owned, 'utf8')).toBe('// hand-edited\n')
    expect(readFileSync(tfvars, 'utf8')).toBe(tfvarsBefore)
    for (const path of result.changed) {
      expect(path.startsWith('infrastructure/terraform/modules/')).toBe(true)
    }
  })

  it('lists without writing under --dry-run', async () => {
    const { projectRoot } = await generate('product', 'dry')
    const target = join(projectRoot, A_MODULE_FILE)
    writeFileSync(target, '# stale copy\n')

    // Same context, but dry.
    const { manifest, defaults } = loadProfile('product')
    const ctx = buildContext({
      projectName: 'dry', projectSlug: 'dry', profile: 'product', manifest, defaults,
      selections: resolveSelections(manifest, defaults),
      outputDir: ROOT, dryRun: true, provision: false,
    })

    const result = await refreshSharedAssets(ctx, projectRoot)

    expect(result.changed).toEqual([A_MODULE_FILE])
    expect(result.written).toBe(false)
    expect(readFileSync(target, 'utf8')).toBe('# stale copy\n')
    expect(formatRefreshResult(result)).toContain('nothing was written')
  })

  it('works for both profiles', async () => {
    for (const [profile, slug] of [
      ['product', 'both-product'],
      ['control-plane', 'both-cp'],
    ] as Array<[ProfileName, string]>) {
      const { ctx, projectRoot } = await generate(profile, slug)
      expect((await refreshSharedAssets(ctx, projectRoot)).unchanged).toBeGreaterThan(0)
    }
  })
})

describe('what is never copied out of the starter', () => {
  it('leaves provider caches and state artifacts behind', async () => {
    // Running any Terraform command inside the shared modules leaves a
    // .terraform provider cache there. It is gitignored, so it never appears
    // in review -- but a filesystem walk would ship the binary into every
    // generated project.
    const { ctx } = await generate('product', 'clean')
    const paths = collectSharedAssets(ctx).map((f) => f.outputPath)

    expect(paths.length).toBeGreaterThan(0)
    expect(paths.some((p) => p.includes('/.terraform/'))).toBe(false)
    expect(paths.some((p) => p.endsWith('.exe'))).toBe(false)
    expect(paths.some((p) => p.endsWith('.tfstate') || p.endsWith('tfplan'))).toBe(false)
  })
})

const A_RENDERED_FILE = 'services/worker/koras_worker/worker.py'

describe('refreshRenderedPaths', () => {
  it('reports a freshly generated file as already current', async () => {
    const { ctx, projectRoot } = await generate('product', 'fresh-render')
    const result = await refreshRenderedPaths(ctx, projectRoot, [A_RENDERED_FILE])

    expect(result.unchanged).toEqual([A_RENDERED_FILE])
    expect(result.updated).toEqual([])
    expect(result.written).toBe(false)
  })

  it('restores a template-owned file the project has fallen behind on', async () => {
    // The shape of the defect this exists for: a fix lands in the starter and
    // an existing project keeps the old file, because it is rendered rather
    // than a shared asset and nothing copies it.
    const { ctx, projectRoot } = await generate('product', 'stale-render')
    const target = join(projectRoot, A_RENDERED_FILE)
    const original = readFileSync(target, 'utf8')
    writeFileSync(target, '# an older version\n')

    const result = await refreshRenderedPaths(ctx, projectRoot, [A_RENDERED_FILE])

    expect(result.updated).toEqual([A_RENDERED_FILE])
    expect(result.written).toBe(true)
    expect(readFileSync(target, 'utf8')).toBe(original)
  })

  it('writes nothing under --dry-run, so it can answer "is this stale?"', async () => {
    const { ctx, projectRoot } = await generate('product', 'dry-render', true)
    await writeFiles({ ...ctx, dryRun: false }, renderTemplate(ctx))
    const target = join(projectRoot, A_RENDERED_FILE)
    writeFileSync(target, '# an older version\n')

    const result = await refreshRenderedPaths(ctx, projectRoot, [A_RENDERED_FILE])

    expect(result.updated).toEqual([A_RENDERED_FILE])
    expect(result.written).toBe(false)
    expect(readFileSync(target, 'utf8')).toBe('# an older version\n')
  })

  it('names a path the profile does not render rather than passing over it', async () => {
    // A typo silently doing nothing would read as "already up to date", which
    // is the one answer that must never be wrong here.
    const { ctx, projectRoot } = await generate('product', 'unknown-render')
    const result = await refreshRenderedPaths(ctx, projectRoot, ['services/api/nope.txt'])

    expect(result.unknown).toEqual(['services/api/nope.txt'])
    expect(result.updated).toEqual([])
    expect(formatRefreshPathResult(result)).toContain('renders no such file')
  })
})

describe('refreshing .koras/project.yaml', () => {
  const MANIFEST = '.koras/project.yaml'
  const BLOCK = [
    '# Hand-maintained: the framework this product runs.',
    'framework:',
    '  name: koras-engineering-framework',
    '  source_baseline: 2fe5701edb8f9e6f89e3414f4bddfd9fc4a6e7ed',
    '  # a comment inside the block',
    '  agents: 40',
  ].join('\n')

  it('keeps the hand-maintained framework block, comments included', async () => {
    const { ctx, projectRoot } = await generate('product', 'keep-framework')
    const target = join(projectRoot, MANIFEST)
    const current = readFileSync(target, 'utf8')
    writeFileSync(target, current.replace('\ncomponents:', `\n${BLOCK}\n\ncomponents:`))
    // Make the rendered manifest differ so the file is actually rewritten.
    writeFileSync(target, readFileSync(target, 'utf8').replace(/template_digest: \w+/, 'template_digest: ' + '0'.repeat(64)))

    const result = await refreshRenderedPaths(ctx, projectRoot, [MANIFEST])
    const after = readFileSync(target, 'utf8')

    expect(result.updated).toEqual([MANIFEST])
    expect(after).toContain(BLOCK)
    expect(after).not.toContain('0'.repeat(64))
    expect(after.indexOf('framework:')).toBeLessThan(after.indexOf('components:'))
  })

  it('is idempotent once the block is in place', async () => {
    const { ctx, projectRoot } = await generate('product', 'idem-framework')
    const target = join(projectRoot, MANIFEST)
    writeFileSync(target, readFileSync(target, 'utf8').replace('\ncomponents:', `\n${BLOCK}\n\ncomponents:`))
    await refreshRenderedPaths(ctx, projectRoot, [MANIFEST])
    const second = await refreshRenderedPaths(ctx, projectRoot, [MANIFEST])
    expect(second.unchanged).toEqual([MANIFEST])
  })

  it('changes nothing for a manifest without a framework block', () => {
    expect(preserveFrameworkBlock('schema_version: 1\n', 'schema_version: 1\ncomponents:\n')).toBe(
      'schema_version: 1\ncomponents:\n',
    )
  })
})