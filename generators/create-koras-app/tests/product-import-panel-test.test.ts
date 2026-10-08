import { describe, it, expect, afterAll } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { existsSync, readFileSync, rmSync } from 'node:fs'
import { loadProfile } from '../src/profiles/index.js'
import { applyComponentOverrides, resolveSelections, validateSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'
import { writeFiles } from '../src/generation/writer.js'

/**
 * The import panel's component test ships with the capability, and only with it.
 *
 * A product generated with `data_import` carries `ImportPanel.test.mjs`, the harness it runs on
 * (`apps/web/src/test-support`) and a `test` script in `apps/web` that names it, so `pnpm test`
 * (turbo) runs it with no dependency the workspace does not already have. A product generated
 * without the capability carries none of the three: a `test` script naming a file that was not
 * generated would fail every such product's pipeline. The suite itself is executed against a
 * generated product by the `Generator Integration` workflow, not here.
 */

const OUT = join(tmpdir(), `koras-panel-test-${process.pid}-${Date.now()}`)

afterAll(() => {
  if (existsSync(OUT)) rmSync(OUT, { recursive: true, force: true })
})

async function generate(slug: string, overrides: { with?: string[]; without?: string[] } = {}) {
  const { manifest, defaults } = loadProfile('product')
  const selections = resolveSelections(manifest, defaults)
  applyComponentOverrides(manifest, selections, overrides)
  validateSelections(manifest, selections)
  const ctx = buildContext({
    projectName: slug,
    projectSlug: slug,
    profile: 'product',
    manifest,
    defaults,
    selections,
    outputDir: OUT,
    dryRun: false,
    provision: false,
  })
  const { fileList } = await writeFiles(ctx, renderTemplate(ctx))
  return {
    has: (path: string) => fileList.includes(path),
    read: (path: string) => readFileSync(join(OUT, slug, path), 'utf8'),
  }
}

const HARNESS = [
  'apps/web/src/test-support/register.mjs',
  'apps/web/src/test-support/tsx-loader.mjs',
  'apps/web/src/test-support/fake-dom.mjs',
  'apps/web/src/test-support/imports-actions.stub.mjs',
]
const PANEL_TEST = 'apps/web/src/app/dashboard/imports/ImportPanel.test.mjs'

describe('the import panel test ships with data_import', () => {
  it.each([
    ['import-panel-test-on', { with: ['data_import'] }],
    // The upload plumbing differs with secure_files (the checksum comes from browser-upload);
    // the harness must not care.
    ['import-panel-test-secure', { with: ['data_import', 'secure_files', 'clamd', 'worker'] }],
  ])('in a product generated as %s: the test, the harness and a script that names the test', async (slug, overrides) => {
    const gen = await generate(slug, overrides)
    expect(gen.has(PANEL_TEST)).toBe(true)
    for (const file of HARNESS) expect(gen.has(file), file).toBe(true)

    const pkg = JSON.parse(gen.read('apps/web/package.json')) as { scripts: Record<string, string> }
    const script = pkg.scripts.test
    expect(script).toBeDefined()
    expect(script).toContain('--import ./src/test-support/register.mjs')
    // Every file the script names is a file this product has.
    const named = [...script!.matchAll(/(?:--import\s+\.\/|\s)(src\/\S+\.mjs)/g)].map((m) => `apps/web/${m[1]}`)
    expect(named).toContain(PANEL_TEST)
    for (const file of named) expect(gen.has(file), file).toBe(true)
    // The harness reaches the panel's actions module only through the stub it owns.
    expect(gen.read('apps/web/src/test-support/tsx-loader.mjs')).toContain('imports-actions.stub.mjs')
    // No dependency is added for it.
    const full = JSON.parse(gen.read('apps/web/package.json')) as {
      dependencies: Record<string, string>
      devDependencies: Record<string, string>
    }
    expect(Object.keys(full.devDependencies).sort()).toEqual(
      ['@tailwindcss/postcss', '@types/node', '@types/react', '@types/react-dom', 'tailwindcss', 'typescript'],
    )
  })

  it('the shipped test reads no product name: it uses only the files the panel itself has', async () => {
    const gen = await generate('import-panel-test-name', { with: ['data_import'] })
    const text = gen.read(PANEL_TEST)
    expect(text).not.toContain('import-panel-test-name')
    expect(text).toContain("from './ImportPanel.tsx'")
    expect(text).toContain("from './source-state.ts'")
  })
})

describe('a product without data_import carries none of it', () => {
  it('has no test, no harness and no web test script', async () => {
    const gen = await generate('import-panel-test-off')
    expect(gen.has('apps/web/src/app/dashboard/imports/ImportPanel.tsx')).toBe(false)
    expect(gen.has(PANEL_TEST)).toBe(false)
    for (const file of HARNESS) expect(gen.has(file), file).toBe(false)
    const pkg = JSON.parse(gen.read('apps/web/package.json')) as { scripts: Record<string, string> }
    expect(pkg.scripts.test).toBeUndefined()
    expect(pkg.scripts.typecheck).toBe('tsc --noEmit')
  })
})
