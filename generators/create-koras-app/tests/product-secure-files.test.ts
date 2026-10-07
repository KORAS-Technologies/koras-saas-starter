import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { createHash } from 'node:crypto'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { mkdirSync, rmSync, existsSync, readFileSync } from 'node:fs'
import yaml from 'js-yaml'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import {
  resolveSelections,
  applyComponentOverrides,
  validateSelections,
} from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'
import { parseArgs } from '../src/cli/args.js'
import { secureFilesRecommendation } from '../src/cli/index.js'
import { templatePath } from './template-path.js'

/**
 * `secure_files` (ADR 0013), layer 1: the capability exists, is off by default,
 * and a product generated without it is what it always was.
 *
 * What the capability gates is asserted from the manifest rather than from a
 * list in this file, so a later layer that appends a path to `template_map`
 * is covered without editing a test, and a path that does not exist is caught.
 */

const ROOT = join(tmpdir(), `koras-sf-gen-${process.pid}-${Date.now()}`)

beforeAll(() => mkdirSync(ROOT, { recursive: true }))
afterAll(() => {
  if (existsSync(ROOT)) rmSync(ROOT, { recursive: true, force: true })
})

function select(profile: ProfileName, args: { with?: string[]; without?: string[] }) {
  const { manifest, defaults } = loadProfile(profile)
  const selections = resolveSelections(manifest, defaults)
  applyComponentOverrides(manifest, selections, args)
  validateSelections(manifest, selections)
  return { manifest, defaults, selections }
}

function render(slug: string, args: { with?: string[]; without?: string[] } = {}) {
  const { manifest, defaults, selections } = select('product', args)
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
  const files = new Map(
    renderTemplate(ctx).map((f) => [
      f.outputPath.replace(/\\/g, '/'),
      typeof f.content === 'string' ? f.content : f.content.toString('utf8'),
    ]),
  )
  return { ctx, files }
}

const ON = ['secure_files', 'clamd', 'worker']
const API_MODULE = 'services/api/koras_api/core/secure_files.py'
const WORKER_MODULE = 'services/worker/koras_worker/secure_files.py'
const PY_TEST = 'tests/unit/test_secure_files_config.py'

const digest = (files: Map<string, string>, only?: (p: string) => boolean) =>
  createHash('sha256')
    .update(
      [...files.entries()]
        .filter(([p]) => (only ? only(p) : true))
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([p, c]) => `${p}\0${c}`)
        .join('\0\0'),
    )
    .digest('hex')

function manifestOf() {
  return loadProfile('product').manifest
}

function gated(): string[] {
  const entry = manifestOf().template_map.capabilities.secure_files
  return typeof entry === 'string' ? [entry] : (entry ?? [])
}

/**
 * What the capability gates **and nothing else gates as well**. A file listed under another
 * capability too (layer 5: the restore suite that needs the assistant) is generated only where
 * both are on, so a product generated with `secure_files` alone does not have it.
 */
function gatedAlone(): string[] {
  const { capabilities } = manifestOf().template_map
  const others = Object.entries(capabilities)
    .filter(([name]) => name !== 'secure_files' && name !== 'storage_governance')
    .flatMap(([, entry]) => (typeof entry === 'string' ? [entry] : (entry ?? [])))
  return gated().filter((path) => !others.includes(path))
}

describe('declared like every other capability', () => {
  it('is in the manifest and off in the defaults', () => {
    const { manifest, defaults } = loadProfile('product')
    expect(manifest.capabilities.secure_files).toBe(true)
    expect(defaults.capabilities?.secure_files).toBe(false)
  })

  it('requires storage, tenancy, rls, the worker and clamd -- services as well as capabilities', () => {
    expect(manifestOf().requires.secure_files).toEqual([
      'storage',
      'tenancy',
      'rls',
      'worker',
      'clamd',
    ])
  })

  it('gates a real set of files, and every gated path exists in the template', () => {
    expect(gated().length).toBeGreaterThan(0)
    for (const path of gated()) {
      // A listed path is an *output* path: the template may carry it as is, with `.hbs`, or (a
      // directory) as a tree. At least one has to exist.
      const found = [path, `${path}.hbs`].some((candidate) => {
        try {
          templatePath('product', candidate)
          return true
        } catch {
          return false
        }
      })
      expect(found, `${path} is listed under secure_files and exists nowhere in the template`).toBe(
        true,
      )
    }
  })

  it('is not a capability of the control plane, which refuses it by name', () => {
    expect(() => select('control-plane', { with: ['secure_files'] })).toThrow(
      /Unknown component "secure_files"/,
    )
  })
})

describe('the default product is what it was', () => {
  const { ctx, files } = render('sfdefault')
  const paths = [...files.keys()]

  it('has the capability off', () => {
    expect(ctx.selections.capabilities.secure_files).toBe(false)
  })

  it('renders the constant False in both services', () => {
    expect(files.get(API_MODULE)).toMatch(/^SECURE_FILES = False$/m)
    expect(files.get(WORKER_MODULE)).toMatch(/^SECURE_FILES = False$/m)
  })

  it('carries no secure_files-only artefact', () => {
    for (const path of gated()) {
      expect(paths.filter((p) => p === path || p.startsWith(`${path}/`)), path).toEqual([])
    }
    expect(files.has('docs/SECURE_FILES.md')).toBe(false)
  })

  it('wires nothing into the API, the worker, its settings or its secrets', () => {
    for (const path of [
      'services/api/koras_api/main.py',
      'services/api/koras_api/core/settings.py',
      'services/worker/koras_worker/worker.py',
      'local/config/secrets.manifest',
    ]) {
      const text = files.get(path) ?? ''
      expect(text, path).not.toMatch(/secure_files|file_scan|FILE_SCAN/i)
    }
  })

  it('does not record the capability as enabled', () => {
    const recorded = yaml.load(files.get('.koras/project.yaml') ?? '') as {
      components: { capabilities: string[] }
    }
    expect(recorded.components.capabilities).not.toContain('secure_files')
  })

  it('carries the both-modes unit test, which asserts the generated constant is False', () => {
    expect(files.get(PY_TEST)).toContain('def test_the_generated_constant_is_false')
    expect(files.get(PY_TEST)).not.toContain('def test_the_generated_constant_is_true')
  })

  it('--without secure_files is exactly the default', () => {
    const explicit = render('sfdefault', { without: ['secure_files'] })
    expect(digest(explicit.files)).toBe(digest(files))
  })
})

describe('a product generated WITH secure_files', () => {
  const { ctx, files } = render('sfsame', { with: ON })
  const paths = [...files.keys()]

  it('has the capability on', () => {
    expect(ctx.selections.capabilities.secure_files).toBe(true)
  })

  it('renders the constant True in both services', () => {
    expect(files.get(API_MODULE)).toMatch(/^SECURE_FILES = True$/m)
    expect(files.get(WORKER_MODULE)).toMatch(/^SECURE_FILES = True$/m)
  })

  it('includes everything the capability gates', () => {
    for (const path of gatedAlone()) {
      expect(
        paths.some((p) => p === path || p.startsWith(`${path}/`)),
        path,
      ).toBe(true)
    }
    expect(files.get(PY_TEST)).toContain('def test_the_api_refuses_to_start_without_a_scanner')
  })

  it('refuses to start in the API and in the worker, before anything else', () => {
    const main = files.get('services/api/koras_api/main.py') ?? ''
    expect(main).toContain('validate_secure_files_settings(settings)')
    expect(main.indexOf('validate_secure_files_settings(settings)')).toBeLessThan(
      main.indexOf('await verify_rls_enforcement()'),
    )
    const worker = files.get('services/worker/koras_worker/worker.py') ?? ''
    expect(worker).toContain('enforce_secure_files_at_startup()')
    expect(worker.indexOf('enforce_secure_files_at_startup()')).toBeLessThan(
      worker.indexOf('if not settings.database_url'),
    )
  })

  it('declares the scanner settings and their secrets', () => {
    expect(files.get('services/api/koras_api/core/settings.py')).toContain('file_scan_backend')
    const secrets = files.get('local/config/secrets.manifest') ?? ''
    expect(secrets).toMatch(/^FILE_SCAN_BACKEND supplied - enum:clamd$/m)
    expect(secrets).toMatch(/^FILE_SCAN_CLAMD_HOST supplied - nonempty$/m)
  })

  it('records the capability in .koras/project.yaml', () => {
    const recorded = yaml.load(files.get('.koras/project.yaml') ?? '') as {
      components: { capabilities: string[]; services: string[] }
    }
    expect(recorded.components.capabilities).toContain('secure_files')
    expect(recorded.components.services).toEqual(expect.arrayContaining(['worker', 'clamd']))
  })

  it('differs from the same product without it only where the capability acts', () => {
    // clamd on in both, so the only difference is secure_files itself.
    const base = render('sfsame', { with: ['clamd'] }).files
    const wired = new Set([
      'services/api/koras_api/main.py',
      'services/api/koras_api/core/settings.py',
      'services/worker/koras_worker/worker.py',
      'local/config/secrets.manifest',
      API_MODULE,
      WORKER_MODULE,
      PY_TEST,
      '.koras/project.yaml',
      // Layer 2: what is rendered by the capability rather than gated by it. Each of these is
      // asserted, both ways, in `product-secure-files-upload.test.ts`.
      'services/api/koras_api/routers/files.py',
      'services/api/koras_api/core/errors.py',
      'services/worker/Dockerfile',
      'services/worker/pyproject.toml',
      'apps/web/src/app/dashboard/files/FilesPanel.tsx',
      'apps/web/src/app/dashboard/files/actions.ts',
      // Layer 4: the release layer renders these by the capability, and asserts each half in
      // `product-secure-files-release.test.ts`.
      'apps/web/src/app/dashboard/files/page.tsx',
      'services/api/koras_api/core/file_hooks.py',
      'tests/unit/test_files_release_api.py',
      'tests/unit/test_file_hooks.py',
      'apps/web/src/app/dashboard/imports/ImportPanel.tsx',
      'apps/web/src/app/dashboard/imports/actions.ts',
      'tests/unit/test_upload_ticket_contract.py',
      // Layer 5: the restore worker task and its unit test are rendered by the capability;
      // `product-secure-files-restore.test.ts` asserts each half.
      'services/worker/koras_worker/tasks/storage_restore.py',
      'tests/unit/test_storage_restore.py',
      'tests/unit/test_release_bypass_guards.py',
      'tests/unit/test_scan_task.py',
      // The round-trip harness names the settings a secure API refuses to start without.
      'playwright.config.ts',
    ])
    // The recorded component list is written into several generated files.
    const unlisted = (text: string) =>
      text.replace(/'secure_files', /g, '').replace(/`secure_files` /g, '').replace(/\s*"secure_files",/g, '')
    for (const [path, content] of base) {
      if (wired.has(path)) continue
      expect(unlisted(files.get(path) ?? ''), path).toBe(unlisted(content))
    }
    const added = paths.filter((p) => !base.has(p)).sort()
    // Each gated path is a file or a directory, and every one of them is among what was added.
    for (const path of gatedAlone()) {
      expect(
        added.some((p) => p === path || p.startsWith(`${path}/`)),
        `${path} is gated but was not added by the capability`,
      ).toBe(true)
    }
  })
})

describe('the validator refuses a configuration missing what it stands on', () => {
  it('--with secure_files alone names clamd', () => {
    expect(() => select('product', { with: ['secure_files'] })).toThrow(
      /Component "secure_files" requires "clamd"\. Enable it as well: --with secure_files,clamd/,
    )
  })

  it('names every missing component, services included', () => {
    expect(() => select('product', { with: ['secure_files'], without: ['worker'] })).toThrow(
      /requires "worker", "clamd"/,
    )
  })

  it('--with secure_files --without storage is refused, naming storage', () => {
    expect(() =>
      select('product', { with: ['secure_files', 'clamd'], without: ['storage'] }),
    ).toThrow(/requires "storage"/)
  })

  it('--without tenancy and --without rls are refused too', () => {
    expect(() => select('product', { with: ON, without: ['tenancy'] })).toThrow(/"tenancy"/)
    expect(() => select('product', { with: ON, without: ['rls'] })).toThrow(/"rls"/)
  })

  it('accepts the full set', () => {
    expect(() => select('product', { with: ON })).not.toThrow()
  })
})

describe('the command line', () => {
  it('parses --with and --without secure_files', () => {
    const base = ['node', 'create-koras-app', 'new-app']
    expect(parseArgs([...base, '--with', 'secure_files,clamd']).with).toEqual([
      'secure_files',
      'clamd',
    ])
    expect(parseArgs([...base, '--without=secure_files']).without).toEqual(['secure_files'])
  })

  it('recommends it when files are stored and it is off, and only then', () => {
    const off = select('product', {}).selections
    expect(secureFilesRecommendation(off)).toMatch(/--with secure_files,clamd,worker/)
    expect(secureFilesRecommendation(select('product', { with: ON }).selections)).toBeNull()
    expect(
      secureFilesRecommendation(select('product', { without: ['storage'] }).selections),
    ).toBeNull()
    // The control plane has no such capability, so says nothing.
    expect(secureFilesRecommendation(select('control-plane', {}).selections)).toBeNull()
  })
})

describe('the two generated modules share one set of checks', () => {
  const shared = (text: string) => {
    const a = text.indexOf('# BEGIN SHARED')
    const b = text.indexOf('# END SHARED')
    expect(a).toBeGreaterThan(-1)
    expect(b).toBeGreaterThan(a)
    return text.slice(a, b)
  }
  const read = (p: string) =>
    readFileSync(templatePath('product', p), 'utf8').split(String.fromCharCode(13)).join('')

  it('is byte-identical between the API and the worker', () => {
    expect(shared(read(WORKER_MODULE + '.hbs'))).toBe(shared(read(API_MODULE + '.hbs')))
  })
})