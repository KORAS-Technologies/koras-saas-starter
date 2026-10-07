import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { mkdirSync, rmSync, existsSync } from 'node:fs'
import yaml from 'js-yaml'
import { loadProfile } from '../src/profiles/index.js'
import {
  resolveSelections,
  applyComponentOverrides,
  validateSelections,
} from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'

/**
 * Import activation (ADR 0013 section 7), rendered both ways.
 *
 * A product generated with `data_import` carries the gate (API, worker, settings, the shared
 * parse rule), the per-environment declaration with every environment `disabled`, the drift
 * script and the suites that hold them. A product generated without it carries none of that.
 * The behaviour is the generated product's own tests, which the generator-integration workflow
 * runs; what is asserted here is what only the generator can get wrong -- which files exist in
 * which mode, and that nothing ships a default of "on".
 */

const ROOT = join(tmpdir(), `koras-import-activation-${process.pid}-${Date.now()}`)

beforeAll(() => mkdirSync(ROOT, { recursive: true }))
afterAll(() => {
  if (existsSync(ROOT)) rmSync(ROOT, { recursive: true, force: true })
})

function render(slug: string, args: { with?: string[]; without?: string[] } = {}) {
  const { manifest, defaults } = loadProfile('product')
  const selections = resolveSelections(manifest, defaults)
  applyComponentOverrides(manifest, selections, args)
  validateSelections(manifest, selections)
  const ctx = buildContext({
    projectName: slug,
    projectSlug: slug,
    profile: 'product',
    manifest,
    defaults,
    selections,
    outputDir: ROOT,
    dryRun: false,
    provision: false,
  })
  return new Map(
    renderTemplate(ctx).map((f) => [
      f.outputPath.replace(/\\/g, '/'),
      typeof f.content === 'string' ? f.content : f.content.toString('utf8'),
    ]),
  )
}

const CR = String.fromCharCode(13)
const text = (files: Map<string, string>, path: string): string => {
  const found = files.get(path)
  expect(found, `${path} was not generated`).toBeDefined()
  return found!.split(CR).join('')
}

const on = render('actison', { with: ['data_import', 'worker'] })
const off = render('actisoff', { with: ['worker'] })
const withSecureFiles = render('actissf', {
  with: ['secure_files', 'clamd', 'worker', 'data_import'],
})

const API = 'services/api/koras_api'
const GATED = [
  'local/config/import-activation.yaml',
  'local/scripts/import-activation-drift.sh',
  'tests/unit/test_import_activation_gate.py',
  'tests/unit/test_import_activation_declaration.py',
  'python-packages/koras-import/src/koras_import/activation.py',
  'python-packages/koras-import/tests/test_activation.py',
]

describe('data_import on: the gate and the declaration are generated', () => {
  it.each(GATED)('%s exists', (path) => {
    expect(on.has(path)).toBe(true)
    expect(withSecureFiles.has(path)).toBe(true)
  })

  it('the declaration names the four environments and ships every one disabled', () => {
    const declared = yaml.load(text(on, 'local/config/import-activation.yaml')) as {
      environments: Record<string, { import_activation: string }>
    }
    expect(Object.keys(declared.environments).sort()).toEqual(['dev', 'prod', 'stg', 'test'])
    for (const [environment, entry] of Object.entries(declared.environments)) {
      expect(entry.import_activation, environment).toBe('disabled')
    }
  })

  it('the API settings default the switch to off and parse it with the shared rule', () => {
    const settings = text(on, `${API}/core/settings.py`)
    expect(settings).toContain('imports_enabled: bool = False')
    expect(settings).toContain('from koras_import import parse_import_activation')
    expect(settings).toContain('return parse_import_activation(value)')
  })

  it('every import route is behind one router-level dependency', () => {
    const router = text(on, `${API}/routers/imports.py`)
    expect(router).toContain('dependencies=[Depends(require_import_activation)]')
    expect(router).toContain('if settings.imports_enabled:')
    expect(text(on, `${API}/core/errors.py`)).toContain('IMPORT_NOT_ENABLED = "import_not_enabled"')
  })

  it('both worker tasks refuse first, and the worker holds the same rule', () => {
    const task = text(on, 'services/worker/koras_worker/tasks/imports.py')
    expect(task).toContain('imports_enabled: bool = False')
    expect(task).toContain('return parse_import_activation(value)')
    expect(task).toContain('_refuse_while_disabled(envelope, "validate")')
    expect(task).toContain('_refuse_while_disabled(envelope, "commit")')
  })

  it('the setting is declared optional (never supplied) in the secrets manifest', () => {
    const manifest = text(on, 'local/config/secrets.manifest')
    expect(manifest).toMatch(/^IMPORTS_ENABLED optional - bool$/m)
    expect(manifest).not.toMatch(/^IMPORTS_ENABLED supplied/m)
  })

  it('the round-trip harness switches imports on for its own disposable API, and only there', () => {
    const config = text(on, 'playwright.config.ts')
    expect(config).toContain("IMPORTS_ENABLED: 'true'")
    const hits = [...on.entries()].filter(
      ([path, content]) =>
        /IMPORTS_ENABLED\s*[=:]\s*["']?(true|1|yes|on)\b/i.test(content) &&
        !/(^|\/)(tests?|e2e)\//.test(path) &&
        path !== 'playwright.config.ts',
    )
    expect(hits.map(([path]) => path)).toEqual([])
  })

  it('the deploy refuses drift through the declaration, so it is a no-op without one', () => {
    const deploy = text(on, '.github/workflows/deploy.yml')
    expect(deploy).toContain('local/config/import-activation.yaml')
    expect(deploy).toContain('bash local/scripts/import-activation-drift.sh')
  })

  it('names no product the capability was proven in', () => {
    for (const path of GATED) {
      const content = text(on, path)
      // A comment may say the design was proven in a product; no path, name or limit of one.
      expect(content.replace(/Proven in Docoris/g, ''), path).not.toMatch(/docoris/i)
      expect(content, path).not.toMatch(/\bGR-\d+/)
    }
  })

  it('the web layer can say why a refusal happened', () => {
    expect(text(on, 'apps/web/src/lib/api-errors.ts')).toContain("case 'import_not_enabled':")
  })
})

describe('data_import off: none of it is generated', () => {
  it.each(GATED)('%s is absent', (path) => {
    expect(off.has(path)).toBe(false)
  })

  it('settings, manifest and the harness carry no trace of it', () => {
    expect(text(off, `${API}/core/settings.py`)).not.toContain('imports_enabled')
    expect(text(off, `${API}/core/settings.py`)).not.toContain('koras_import')
    expect(text(off, 'local/config/secrets.manifest')).not.toContain('IMPORTS_ENABLED')
    expect(text(off, 'playwright.config.ts')).not.toContain('IMPORTS_ENABLED')
    expect(off.has(`${API}/routers/imports.py`)).toBe(false)
  })

  it('the deploy step is still present and is a no-op, because it keys off the declaration file', () => {
    const deploy = text(off, '.github/workflows/deploy.yml')
    expect(deploy).toContain('if [ -f local/config/import-activation.yaml ]; then')
    expect(deploy).toContain('nothing to check')
  })
})
