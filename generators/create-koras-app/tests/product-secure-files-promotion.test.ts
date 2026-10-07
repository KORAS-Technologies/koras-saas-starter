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
 * `secure_files` (ADR 0013), layer 6b: the promotion tooling, rendered with and without the
 * capability.
 *
 * The tooling is generic and read-only; what is a product's is configuration
 * (`local/config/promotion.yaml`), never code. The behaviour is the generated product's own suites
 * (`tests/unit/test_promotion_*.py`, `tests/integration/test_f1_detector_real.py`,
 * `tests/integration/test_provider_qualification_extra.py`), which the generator-integration
 * workflow runs; what is asserted here is what only the generator can get wrong: which files
 * exist in which mode, that the configuration is rendered for the right product and agrees with
 * the generated CI, that no product's name or finding ever reaches the Starter's code, and that a
 * product without the capability is exactly what it was.
 */

const ROOT = join(tmpdir(), `koras-sf-promotion-${process.pid}-${Date.now()}`)

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

const SECURE = ['secure_files', 'clamd', 'worker']
const on = render('promoon', { with: SECURE })
const onImport = render('promoimp', { with: [...SECURE, 'data_import'] })
const off = render('promooff', { with: ['worker'] })
const offImport = render('promoffimp', { with: ['worker', 'data_import'] })

const TOOLING = [
  'tooling/promotion/__init__.py',
  'tooling/promotion/__main__.py',
  'tooling/promotion/activation.py',
  'tooling/promotion/adapters.py',
  'tooling/promotion/config.py',
  'tooling/promotion/f1.py',
  'tooling/promotion/gate.py',
  'tooling/promotion/provider_qualification.py',
  'tooling/promotion/register.py',
  'tooling/promotion/result.py',
]
const CONFIG = [
  'local/config/promotion.yaml',
  'local/config/f1-dispositions.yaml',
  'local/scripts/qualify-storage-provider.sh',
  'local/.qualification/.gitignore',
  'docs/security/SECURITY-REGISTER.md',
  '.github/workflows/promotion-gate.yml',
]
const SUITES = [
  'tests/unit/promotion_support.py',
  'tests/unit/test_promotion_config.py',
  'tests/unit/test_promotion_adapters.py',
  'tests/unit/test_promotion_register.py',
  'tests/unit/test_promotion_f1.py',
  'tests/unit/test_promotion_gate.py',
  'tests/unit/test_promotion_provider_qualification.py',
  'tests/integration/test_provider_qualification_extra.py',
  'tests/integration/test_f1_detector_real.py',
]
const ACTIVATION_SUITE = 'tests/unit/test_promotion_activation.py'
const ALL = [...TOOLING, ...CONFIG, ...SUITES, ACTIVATION_SUITE]

type Promotion = {
  version: number
  secret_store: { provider: string; project: string }
  deploy: { provider: string }
  environments: Record<string, { secret_store_config: string; apps: Record<string, string> }>
  scanner: { backend_setting: string; required_backend: string }
  database: { admin_url_setting: string }
  ci: { provider: string; required_jobs: string[] }
  register: { path: string; id_pattern: string; chain_ids: string[] }
  f1: { dispositions: string }
  qualification: { directory: string; max_age_days: number }
  activation?: { declaration: string; activatable_environments: string[] }
}
const load = (files: Map<string, string>): Promotion =>
  yaml.load(text(files, 'local/config/promotion.yaml')) as Promotion

describe('secure_files on: the promotion tooling is generated', () => {
  it.each([...TOOLING, ...CONFIG, ...SUITES])('%s exists', (path) => {
    expect(on.has(path), path).toBe(true)
    expect(onImport.has(path), path).toBe(true)
  })

  it('the activation suite exists only when data_import is on as well', () => {
    expect(onImport.has(ACTIVATION_SUITE)).toBe(true)
    expect(on.has(ACTIVATION_SUITE)).toBe(false)
  })

  it('the configuration is rendered for the product and names every environment once', () => {
    const cfg = load(on)
    expect(cfg.version).toBe(1)
    expect(cfg.secret_store).toEqual({ provider: 'doppler', project: 'promoon' })
    expect(cfg.deploy.provider).toBe('fly')
    expect(Object.keys(cfg.environments).sort()).toEqual(['dev', 'prod', 'stg', 'test'])
    for (const [env, entry] of Object.entries(cfg.environments)) {
      expect(entry.secret_store_config).toBe(env)
      expect(entry.apps).toEqual({
        api: `promoon-api-${env}`,
        worker: `promoon-worker-${env}`,
        clamd: `promoon-clamd-${env}`,
      })
    }
    expect(cfg.scanner).toEqual({ backend_setting: 'FILE_SCAN_BACKEND', required_backend: 'clamd' })
    expect(cfg.database.admin_url_setting).toBe('DATABASE_ADMIN_URL')
    expect(cfg.qualification.max_age_days).toBe(14)
  })

  it('every setting the gate reads is one the product declares', () => {
    const cfg = load(on)
    const manifest = text(on, 'local/config/secrets.manifest')
    for (const name of [cfg.scanner.backend_setting, cfg.database.admin_url_setting]) {
      expect(manifest, name).toMatch(new RegExp(`^${name} `, 'm'))
    }
    for (const name of ['STORAGE_ENDPOINT', 'STORAGE_BUCKET', 'STORAGE_ACCESS_KEY', 'STORAGE_SECRET_KEY']) {
      expect(manifest, name).toMatch(new RegExp(`^${name} `, 'm'))
    }
  })

  it('the CI jobs the gate requires are the CI jobs the product generates', () => {
    const cfg = load(on)
    const ci = yaml.load(text(on, '.github/workflows/ci.yml')) as {
      jobs: Record<string, { name?: string }>
    }
    const names = Object.values(ci.jobs).map((j) => j.name)
    for (const job of cfg.ci.required_jobs) expect(names, job).toContain(job)
    expect(new Set(cfg.ci.required_jobs).size).toBe(cfg.ci.required_jobs.length)
  })

  it('the register the configuration names is generated, parses as empty on purpose and names no finding', () => {
    const cfg = load(on)
    const register = text(on, cfg.register.path)
    expect(register).toContain('<!-- koras:register-empty -->')
    expect(register).toMatch(/^\| ID \| Type \| Severity \| Status \| Title \|$/m)
    expect(register).not.toMatch(/^\| [A-Z]+-\d+ \|/m)
  })

  it('the paths the configuration names exist in the product', () => {
    const cfg = load(onImport)
    for (const path of [cfg.register.path, cfg.f1.dispositions, cfg.activation!.declaration]) {
      expect(onImport.has(path), path).toBe(true)
    }
  })

  it('the F1 dispositions ship empty: they are a product decision, never Starter content', () => {
    const doc = yaml.load(text(on, 'local/config/f1-dispositions.yaml')) as {
      version: number
      dispositions: unknown[]
    }
    expect(doc).toEqual({ version: 1, dispositions: [] })
  })

  it('the qualification records are git-ignored in their own directory', () => {
    expect(text(on, 'local/.qualification/.gitignore')).toMatch(/^\*$/m)
    expect(load(on).qualification.directory).toBe('local/.qualification')
  })

  it('the interpreter finds the tooling: pytest runs with tooling on its path', () => {
    expect(text(on, 'pyproject.toml')).toContain('pythonpath = ["services/worker", "tooling"]')
  })
})

describe('data_import: the activation section is rendered, and activates nothing', () => {
  it('has an activation section only with data_import, naming the declaration', () => {
    expect(load(on).activation).toBeUndefined()
    const cfg = load(onImport)
    expect(cfg.activation).toBeDefined()
    expect(cfg.activation!.declaration).toBe('local/config/import-activation.yaml')
    expect(onImport.has(cfg.activation!.declaration)).toBe(true)
  })

  it('ships no activatable environment: the declaration alone can never activate one', () => {
    expect(load(onImport).activation!.activatable_environments).toEqual([])
    const declared = yaml.load(text(onImport, 'local/config/import-activation.yaml')) as {
      environments: Record<string, { import_activation: string }>
    }
    for (const entry of Object.values(declared.environments)) {
      expect(entry.import_activation).toBe('disabled')
    }
  })
})

describe('secure_files off: none of it is generated', () => {
  it.each(ALL)('%s is absent', (path) => {
    expect(off.has(path), path).toBe(false)
    expect(offImport.has(path), path).toBe(false)
  })

  it('pytest is configured exactly as it was', () => {
    expect(text(off, 'pyproject.toml')).toContain('pythonpath = ["services/worker"]')
    expect(text(off, 'pyproject.toml')).not.toContain('tooling')
  })

  it('no promotion tooling directory exists at all', () => {
    expect([...off.keys()].filter((p) => p.startsWith('tooling/promotion'))).toEqual([])
    expect([...offImport.keys()].filter((p) => p.startsWith('tooling/promotion'))).toEqual([])
  })
})

describe('a product without the capability is what it was', () => {
  const workflows = (files: Map<string, string>) =>
    [...files.keys()].filter((p) => p.startsWith('.github/workflows/')).sort()

  it('has the same workflows, and the capability adds exactly the one', () => {
    expect(workflows(on)).toEqual([...workflows(off), '.github/workflows/promotion-gate.yml'].sort())
  })

  it('every workflow both products share is identical: the deploy is not made to depend on the gate', () => {
    for (const path of workflows(off)) {
      expect(text(on, path), path).toBe(text(off, path))
    }
  })

  it('names no promotion step in the deploy workflow', () => {
    expect(text(on, '.github/workflows/deploy.yml')).not.toContain('promotion')
  })
})

describe('the gate workflow only reads', () => {
  const workflow = () => text(on, '.github/workflows/promotion-gate.yml')

  it('is a valid workflow that can be run by hand and called from a deploy', () => {
    const doc = yaml.load(workflow()) as {
      name: string
      on: Record<string, unknown>
      permissions: Record<string, string>
      jobs: Record<string, { steps: { run?: string }[] }>
    }
    expect(Object.keys(doc.on).sort()).toEqual(['workflow_call', 'workflow_dispatch'])
    expect(doc.permissions).toEqual({ contents: 'read', checks: 'read' })
    expect(Object.keys(doc.jobs)).toEqual(['gate'])
  })

  it('runs the gate and nothing that writes', () => {
    const body = workflow()
    expect(body).toContain('python -m promotion gate --env')
    for (const verb of ['secrets set', 'secrets unset', 'secrets import', 'flyctl deploy', 'fly deploy', 'doppler secrets set', 'git push', 'gh pr merge', 'gh api -X', '--method POST']) {
      expect(body, verb).not.toContain(verb)
    }
  })
})

describe('the tooling is generic', () => {
  const sources = (files: Map<string, string>) =>
    [...TOOLING, ...CONFIG, ...SUITES].map((p) => [p, text(files, p)] as const)

  it('names no product, secret-store project, app or finding of the product it was proven in', () => {
    for (const [path, content] of sources(onImport)) {
      expect(content, path).not.toMatch(/docoris/i)
      expect(content, path).not.toMatch(/\bGR-\d+/)
      expect(content, path).not.toMatch(/\bOD-\d+/)
      expect(content, path).not.toMatch(/922f70e3|0635c8d1|ebf7e73b|6efb6968/)
    }
  })

  it('issues only read commands: the adapters carry no write verb', () => {
    const adapters = text(on, 'tooling/promotion/adapters.py')
    for (const verb of ['"set"', '"unset"', '"delete"', '"import"', '"deploy"', '"destroy"', '"stop"', '"restart"']) {
      expect(adapters, verb).not.toContain(verb)
    }
    for (const read of ['"doppler"', '"secrets"', '"get"', '"flyctl"', '"list"', '"machines"']) {
      expect(adapters, read).toContain(read)
    }
  })

  it('imports nothing from an application and nothing that is not in the standard library, the repository or a declared development dependency', () => {
    for (const path of TOOLING) {
      const imports = [...text(on, path).matchAll(/^(?:from|import) ([a-zA-Z_][\w]*)/gm)].map((m) => m[1])
      for (const name of imports) {
        expect(
          [
            '__future__', 'argparse', 'asyncio', 'collections', 'dataclasses', 'datetime', 'hashlib',
            'importlib', 'json', 'os', 'pathlib', 're', 'shutil', 'subprocess', 'sys', 'time',
            'typing', 'urllib', 'uuid', 'yaml', 'asyncpg', 'koras_api', 'koras_import', 'enum',
          ],
          `${path} imports ${name}`,
        ).toContain(name)
      }
    }
  })
})

describe('the provider qualification list and the suites agree', () => {
  const guardBlock = (): string => {
    const body = text(on, 'tooling/promotion/provider_qualification.py')
    const block = body.slice(body.indexOf('GUARD_FILES: tuple[str, ...] = ('))
    return block.slice(0, block.indexOf('\n)\n'))
  }

  it('every guard file exists in the product, and the three suites and the harness are guard files', () => {
    const block = guardBlock()
    const paths = [...block.matchAll(/"([\w./-]+\.py)"/g)].map((m) => m[1])
    expect(paths.length).toBeGreaterThan(5)
    for (const path of paths) expect(on.has(path), path).toBe(true)
    for (const suite of ['CHECKSUM_SUITE', 'FINALIZE_SUITE', 'EXTRA_SUITE']) {
      expect(block).toContain(suite)
    }
    expect(paths).toContain('tooling/promotion/provider_qualification.py')
    const body = text(on, 'tooling/promotion/provider_qualification.py')
    for (const [name, path] of [
      ['CHECKSUM_SUITE', 'tests/integration/test_upload_checksum_provider.py'],
      ['FINALIZE_SUITE', 'tests/integration/test_upload_finalization_provider.py'],
      ['EXTRA_SUITE', 'tests/integration/test_provider_qualification_extra.py'],
    ]) {
      expect(body).toContain(`${name} = "${path}"`)
      expect(on.has(path), path).toBe(true)
    }
  })

  it('every required test the harness runs is a test that exists in the suites', () => {
    const body = text(on, 'tooling/promotion/provider_qualification.py')
    const suites: Record<string, string> = {
      CHECKSUM_SUITE: text(on, 'tests/integration/test_upload_checksum_provider.py'),
      FINALIZE_SUITE: text(on, 'tests/integration/test_upload_finalization_provider.py'),
      EXTRA_SUITE: text(on, 'tests/integration/test_provider_qualification_extra.py'),
    }
    const nodes = [...body.matchAll(/_n\(\s*(CHECKSUM_SUITE|FINALIZE_SUITE|EXTRA_SUITE),\s*"(test_\w+)"/g)]
    const fixed = [...body.matchAll(/(_FIN_IN_FLIGHT|_FIN_FINAL_KEY) = "(test_\w+)"/g)]
    expect(nodes.length + fixed.length).toBeGreaterThanOrEqual(13)
    for (const [, suite, name] of nodes) expect(suites[suite], name).toContain(`def ${name}(`)
    for (const [, , name] of fixed) expect(suites.FINALIZE_SUITE, name).toContain(`def ${name}(`)
  })

  it('the forged-provenance case is required, and is built from an unguarded ticket in the harness only', () => {
    const body = text(on, 'tooling/promotion/provider_qualification.py')
    expect(body).toContain('"m12_forged_nonempty_provenance"')
    expect(body).toMatch(/HARNESS_VERSION = [2-9]/)
    const extra = text(on, 'tests/integration/test_provider_qualification_extra.py')
    expect(extra).toContain('def test_Q13_a_forged_nonempty_provenance_on_an_unguarded_copy_source_ticket_is_refused(')
    expect(extra).toContain('guarded=False')
    // no production file offers an unguarded ticket
    for (const path of [
      'services/api/koras_api/routers/files.py',
      'services/worker/koras_worker/uploads/finalize.py',
      'python-packages/koras-storage/src/koras_storage/__init__.py',
    ]) {
      expect(text(on, path), path).not.toContain('guarded=False')
    }
  })

  it('the finalizer still requires provenance EQUAL to the expected upload identity', () => {
    const finalize = text(on, 'services/worker/koras_worker/uploads/finalize.py')
    expect(finalize).toContain('stored_upload != upload_id')
    expect(finalize).not.toMatch(/if not stored_upload/)
  })
})
