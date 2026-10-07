import { describe, it, expect } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { readFileSync } from 'node:fs'
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
 * The review's bounded fixes for `secure_files` (pull request 39), held where they can be held
 * without running a product: what a render contains, and what the Starter's own workflows say.
 * The behaviour each one describes is exercised by the product's own suites and by CI.
 */

const REPO = join(__dirname, '..', '..', '..')
const CR = String.fromCharCode(13)

function render(slug: string, args: { with?: string[]; without?: string[] }): Map<string, string> {
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
    outputDir: join(tmpdir(), `koras-sf-hard-${process.pid}`),
    dryRun: true,
    provision: false,
  })
  return new Map(
    renderTemplate(ctx).map((file) => [
      file.outputPath.split(String.fromCharCode(92)).join('/'),
      typeof file.content === 'string' ? file.content : file.content.toString('utf8'),
    ]),
  )
}

const on = render('sfhardon', { with: ['secure_files', 'clamd', 'worker', 'data_import', 'ai', 'ai_gateway'] })
const off = render('sfhardoff', { with: ['data_import', 'ai', 'ai_gateway'] })

const text = (files: Map<string, string>, path: string): string => {
  const found = files.get(path)
  expect(found, `${path} was not generated`).toBeDefined()
  return found!.split(CR).join('')
}
const repo = (path: string): string => readFileSync(join(REPO, path), 'utf8').split(CR).join('')

describe('the browser ceiling and the hashing status (secure render only)', () => {
  const CLAIM = 'packages/api-client/src/upload-claim.ts'

  it('states one in-memory ceiling and keeps it level with the scan ceiling', () => {
    const claim = text(on, CLAIM)
    const browser = /export const MAX_HASHABLE_BYTES = (\d+) \* 1024 \* 1024/.exec(claim)
    const scan = /^SCAN_CEILING_BYTES = (\d+) \* 1024 \* 1024/m.exec(
      text(on, 'services/api/koras_api/core/secure_files.py'),
    )
    expect(browser, 'MAX_HASHABLE_BYTES').not.toBeNull()
    expect(scan, 'SCAN_CEILING_BYTES').not.toBeNull()
    expect(browser![1]).toBe(scan![1])
    expect(browser![1]).toBe('100')
  })

  it('no longer says the API ceiling bounds what the browser can hold', () => {
    const claim = text(on, CLAIM)
    expect(claim).not.toMatch(/five-gigabyte|5 ?GB|API's size ceiling is what bounds/i)
    expect(claim).toContain('it is bounded HERE, not by the API')
    expect(claim).toContain('if (file.size > limitBytes) throw new FileTooLargeToCheckError')
  })

  it('shows a polite status while the file is hashed, in both panels', () => {
    const files = text(on, 'apps/web/src/app/dashboard/files/FilesPanel.tsx')
    const imports = text(on, 'apps/web/src/app/dashboard/imports/ImportPanel.tsx')
    for (const [name, panel, testId] of [
      ['files', files, 'files-preparing'],
      ['imports', imports, 'imports-preparing'],
    ] as const) {
      expect(panel, name).toContain('setPreparing(true)')
      expect(panel, name).toContain('setPreparing(false)')
      expect(panel, name).toContain('role="status"')
      expect(panel, name).toContain(`data-testid="${testId}"`)
      expect(panel, name).toContain('labels.preparing')
      // The hashing is inside the try that resets it, so a refusal never leaves it showing.
      expect(panel.indexOf('setPreparing(true)')).toBeLessThan(panel.indexOf('await digestOf(file)'))
      expect(panel.indexOf('await digestOf(file)')).toBeLessThan(panel.indexOf('setPreparing(false)'))
    }
  })

  it('has the two sentences in every catalogue, and a default product reads neither', () => {
    // As layer 4's sentences are: in the catalogues of both renders (a catalogue is a plain
    // module that other code imports, so it carries no template syntax), read only by the
    // secure panels.
    for (const locale of ['en', 'de', 'es']) {
      for (const files of [on, off]) {
        const catalogue = text(files, `packages/i18n/src/messages/${locale}.ts`)
        expect(catalogue, locale).toMatch(/'files\.preparing': '[^']+…'/)
        expect(catalogue, locale).toMatch(/'imports\.preparing': '[^']+…'/)
      }
    }
    const readers = [...off.entries()].filter(
      ([path, content]) =>
        !path.startsWith('packages/i18n/') &&
        /files\.preparing|imports\.preparing/.test(content),
    )
    expect(readers.map(([path]) => path)).toEqual([])
  })

  it('adds nothing to the default render of the panels or the labels', () => {
    for (const path of [
      'apps/web/src/app/dashboard/files/FilesPanel.tsx',
      'apps/web/src/app/dashboard/imports/ImportPanel.tsx',
      'apps/web/src/app/dashboard/imports/labels.ts',
      'apps/web/src/app/dashboard/files/page.tsx',
      'apps/web/src/lib/browser-upload.ts',
    ]) {
      const plain = off.get(path)
      if (plain === undefined) continue // the secure-only helper is not generated at all
      expect(plain, path).not.toMatch(/preparing|setPreparing|MAX_HASHABLE_BYTES/)
    }
  })
})

describe('the scanner backend is matched exactly', () => {
  it('in both copies of the check, and the worker settings accept only the literal', () => {
    for (const path of [
      'services/api/koras_api/core/secure_files.py',
      'services/worker/koras_worker/secure_files.py',
    ]) {
      const source = text(on, path)
      expect(source, path).toContain('value in REAL_SCANNER_BACKENDS')
      expect(source, path).not.toMatch(/value\.strip\(\)\.lower\(\) in REAL_SCANNER_BACKENDS/)
    }
    expect(text(on, 'services/worker/koras_worker/scanning/config.py')).toContain(
      'file_scan_backend: Literal["none", "clamd"]',
    )
    expect(text(on, 'services/worker/koras_worker/tasks/scan_sweep.py')).toContain(
      'file_scan_backend: Literal["none", "clamd"]',
    )
  })
})

describe('the migrations and their suites', () => {
  it('the withdrawal suite fails first if the function owner cannot bypass row-level security', () => {
    const suite = text(on, 'supabase/tests/360_file_derived_content_withdrawal.sql')
    expect(suite).toContain('rolsuper or r.rolbypassrls')
    expect(suite).toContain("'public.withdraw_file_derived_content()'::regprocedure")
    expect(suite.indexOf('rolbypassrls')).toBeLessThan(suite.indexOf('insert into public.tenants'))
  })

  it('the matrix has the assistant-enabled-later scenario', () => {
    const matrix = repo('tests/secure_files/migration_matrix.sh')
    expect(matrix).toContain('=== D. a secure product enables the assistant LATER')
    expect(matrix).toContain("'00010_ai_knowledge'")
    expect(matrix).toContain('applied_at')
    expect(matrix).toContain('rls_suites koras_matrix_d')
  })
})

describe('the generated product tells an operator the clamd descriptor is dev-only', () => {
  it('in its own SECURE_FILES.md, and the descriptor really lists dev only', () => {
    const doc = text(on, 'docs/SECURE_FILES.md')
    expect(doc).toContain('lists the dev environment only')
    expect(doc).toMatch(/test, stg and prod each need clamd added/)
    const descriptor = yaml.load(text(on, 'services/clamd/service.yaml')) as {
      environments: string[]
    }
    expect(descriptor.environments).toEqual(['dev'])
  })
})

describe('the Starter workflows are least-privilege and pinned', () => {
  const workflows = ['ci.yml', 'generator-integration.yml', 'secure-files-matrix.yml']

  it.each(workflows)('%s reads the repository and nothing else, and cancels only a pull request', (name) => {
    const source = repo(`.github/workflows/${name}`)
    const doc = yaml.load(source) as {
      permissions: Record<string, string>
      concurrency: { 'cancel-in-progress': string }
    }
    expect(doc.permissions).toEqual({ contents: 'read' })
    expect(doc.concurrency['cancel-in-progress']).toBe("${{ github.event_name == 'pull_request' }}")
    // Nothing here needs a secret, so a pull request from a fork has none to lose or to leak.
    expect(source).not.toMatch(/secrets\./)
    expect(source).not.toMatch(/pull_request_target/)
  })

  it('ci.yml ends with a newline and pins the baseline job to node 20', () => {
    const source = readFileSync(join(REPO, '.github/workflows/ci.yml'), 'utf8')
    expect(source.endsWith('\n')).toBe(true)
    const doc = yaml.load(source) as {
      jobs: Record<string, { steps: { uses?: string; with?: Record<string, unknown> }[] }>
    }
    const node = doc.jobs['framework-baseline']!.steps.find((s) => s.uses?.startsWith('actions/setup-node'))
    expect(node?.with?.['node-version']).toBe(20)
    expect(node?.with?.['package-manager-cache']).toBe(false)
  })

  it('the MinIO build is pinned by commit, verified after the clone, and keyed on it', () => {
    const action = repo('.github/actions/start-minio/action.yml')
    const pin = '07c3a429bfed433e49018cb0f78a52145d4bedeb'
    expect(action).toContain(`pin=${pin}`)
    expect(action).toContain('git rev-parse HEAD')
    expect(action).toContain('refusing to build it')
    expect(action).toContain(`key: minio-${pin}-`)
    expect(action).not.toMatch(/key: minio-RELEASE/)
  })

  it('the promotion gate installs pinned, checksum-verified CLIs and pipes nothing to a shell', () => {
    const gate = text(on, '.github/workflows/promotion-gate.yml')
    expect(gate).not.toMatch(/\|\s*(sudo\s+)?(ba)?sh\b/)
    expect(gate).not.toMatch(/install\.sh/)
    expect(gate).toMatch(/DOPPLER_VERSION: \d+\.\d+\.\d+/)
    expect(gate).toMatch(/FLYCTL_VERSION: \d+\.\d+\.\d+/)
    expect(gate).toMatch(/DOPPLER_SHA256: [0-9a-f]{64}/)
    expect(gate).toMatch(/FLYCTL_SHA256: [0-9a-f]{64}/)
    expect(gate.match(/sha256sum -c -/g)).toHaveLength(2)
    expect(gate).toMatch(/environment\s+#?\s*protection/)
    const doc = yaml.load(gate) as { on: Record<string, unknown> }
    expect(Object.keys(doc.on).sort()).toEqual(['workflow_call', 'workflow_dispatch'])
  })
})
