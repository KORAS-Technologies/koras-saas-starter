import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { mkdirSync, rmSync, existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import {
  resolveSelections,
  applyComponentOverrides,
  validateSelections,
} from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'
import { templatePath } from './template-path.js'

/**
 * `secure_files` (ADR 0013), layer 3: the scanner, in both modes.
 *
 * The scanner's schema, runtime, job, sweep and tests exist only in a product generated with
 * the capability, and what the capability changes in the files both modes share is rendered, not
 * branched at run time. This file renders the product both ways and asserts, from the generated
 * text, the half that is each mode's own. The behaviour is the generated product's own tests
 * (`tests/unit/test_scan*.py`, `test_scanner*.py`, and the integration suites against a real
 * PostgreSQL, store and clamd), which the generator-integration workflow runs.
 */

const ROOT = join(tmpdir(), `koras-sf-scan-${process.pid}-${Date.now()}`)

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
  return {
    ctx,
    files: new Map(
      renderTemplate(ctx).map((f) => [
        f.outputPath.replace(/\\/g, '/'),
        typeof f.content === 'string' ? f.content : f.content.toString('utf8'),
      ]),
    ),
  }
}

const off = render('sfscanoff', { with: ['worker'] }).files
const on = render('sfscanon', { with: ['secure_files', 'clamd', 'worker'] }).files
const text = (files: Map<string, string>, path: string): string => {
  const found = files.get(path)
  expect(found, `${path} was not generated`).toBeDefined()
  return found!.split(String.fromCharCode(13)).join('')
}
const read = (path: string): string =>
  readFileSync(templatePath('product' as ProfileName, path), 'utf8')
    .split(String.fromCharCode(13))
    .join('')

const SCANNER_PATHS = [
  'services/worker/koras_worker/scanning/__init__.py',
  'services/worker/koras_worker/scanning/clamd.py',
  'services/worker/koras_worker/scanning/config.py',
  'services/worker/koras_worker/scanning/objects.py',
  'services/worker/koras_worker/scanning/protocol.py',
  'services/worker/koras_worker/scanning/release.py',
  'services/worker/koras_worker/scanning/result.py',
  'services/worker/koras_worker/scanning/runtime.py',
  'services/worker/koras_worker/scanning/s3.py',
  'services/worker/koras_worker/scanning/structure.py',
  'services/worker/koras_worker/scanning/transition.py',
  'services/worker/koras_worker/tasks/scan.py',
  'services/worker/koras_worker/tasks/scan_sweep.py',
  'services/api/koras_api/core/scan_jobs.py',
  'services/api/koras_api/core/scan_enqueue.py',
  'services/api/koras_api/core/scan_audit.py',
  'supabase/migrations/00040_file_scan_interrupted.sql',
  'supabase/migrations/00041_file_scan_due_indexes.sql',
  'supabase/tests/350_file_scan_columns_isolation.sql',
  'supabase/tests/351_file_scan_sweep_selection.sql',
  'tests/unit/eicar_support.py',
  'tests/unit/scanner_support.py',
  'tests/unit/zip_support.py',
  'tests/unit/test_scan_runtime.py',
  'tests/unit/test_scan_sweep.py',
  'tests/unit/test_scan_handoff.py',
  'tests/unit/test_scanner_transition.py',
  'tests/integration/test_scan_runtime_real.py',
  'tests/integration/test_scan_orchestration_real.py',
  'tests/integration/test_scanner_clamd_live.py',
]

describe('without secure_files there is no scanner and nothing about it', () => {
  it('generates none of the scanner, its schema or its tests', () => {
    for (const path of SCANNER_PATHS) expect(off.has(path), path).toBe(false)
    expect([...off.keys()].filter((p) => p.includes('/scanning/'))).toEqual([])
  })

  it('registers nothing in the worker and copies nothing extra into its image', () => {
    const worker = text(off, 'services/worker/koras_worker/worker.py')
    expect(worker).not.toMatch(/scan_tasks|sweep_pending_scans|tasks\.scan|file\.scan/)
    expect(text(off, 'services/worker/Dockerfile')).not.toMatch(/scan_jobs|scan_enqueue|scan_audit/)
  })

  it('leaves the shared checks and settings exactly as they were', () => {
    for (const path of [
      'services/api/koras_api/core/secure_files.py',
      'services/worker/koras_worker/secure_files.py',
    ]) {
      const module = text(off, path)
      expect(module, path).not.toMatch(/SCAN_CEILING_BYTES|_seconds_up_to|file_scan_timeout|file_scan_max/)
      expect(module, path).toMatch(/^SECURE_FILES = False$/m)
    }
    const settings = text(off, 'services/api/koras_api/core/settings.py')
    expect(settings).not.toMatch(/file_scan|FILE_SCAN/)
    expect(text(off, 'local/config/secrets.manifest')).not.toMatch(/FILE_SCAN|FILE_FINALIZE/)
  })

  it('keeps the legacy seam byte for byte', () => {
    expect(text(off, 'services/api/koras_api/core/file_scan.py')).toBe(
      read('services/api/koras_api/core/file_scan.py'),
    )
    expect(text(on, 'services/api/koras_api/core/file_scan.py')).toBe(
      text(off, 'services/api/koras_api/core/file_scan.py'),
    )
  })

  it('generates no scanner migration, so the schema stops where it did', () => {
    const migrations = [...off.keys()].filter((p) => p.startsWith('supabase/migrations/')).sort()
    expect(migrations.some((m) => /0003[9]|0004\d/.test(m))).toBe(false)
  })
})

describe('with secure_files the scanner is generated and wired as one unit', () => {
  it('generates every scanner artefact', () => {
    for (const path of SCANNER_PATHS) expect(on.has(path), path).toBe(true)
  })

  it('binds file.scan by name and schedules the sweep every five minutes', () => {
    const worker = text(on, 'services/worker/koras_worker/worker.py')
    expect(worker).toContain('from .tasks.scan import bound as scan_tasks')
    expect(worker).toContain('from .tasks.scan_sweep import SWEEP_INTERVAL_MINUTES, sweep_pending_scans')
    expect(worker).toContain('*worker_functions(scan_tasks()),')
    expect(worker).toContain(
      'cron(sweep_pending_scans, minute=set(range(0, 60, SWEEP_INTERVAL_MINUTES)), second=30),',
    )
    // The finalizer's own binding and sweep are still there.
    expect(worker).toContain('*worker_functions(finalize_tasks()),')
    expect(worker).toContain('cron(sweep_finalize,')
  })

  it('has no switch for the scanner or its sweep', () => {
    for (const path of [
      'services/worker/koras_worker/tasks/scan.py',
      'services/worker/koras_worker/tasks/scan_sweep.py',
      'services/worker/koras_worker/scanning/config.py',
      'local/config/secrets.manifest',
    ]) {
      const module = text(on, path)
      expect(module, path).not.toMatch(/FILE_SCAN_SWEEP_ENABLED|file_scan_sweep_enabled/)
      expect(module, path).not.toMatch(/FILE_SCAN_(ALLOW|SKIP|DISABLE|BYPASS)/)
    }
  })

  it('carries the three API files the scanner reaches by name into the worker image', () => {
    const image = text(on, 'services/worker/Dockerfile')
    for (const file of ['scan_jobs', 'scan_enqueue', 'scan_audit']) {
      expect(image).toContain(`COPY services/api/koras_api/core/${file}.py`)
    }
  })

  it('hands a finalized file to the scanner, after the swap, and never decides content there', () => {
    const finalize = text(on, 'services/worker/koras_worker/tasks/finalize.py')
    expect(finalize).toContain('on_final: Callable[[str, str], Awaitable[object]] | None = None')
    expect(finalize.indexOf('await _clear_hold(session, tenant_id, file_id)')).toBeLessThan(
      finalize.indexOf('await on_final(tenant_id, file_id)'),
    )
    expect(finalize).toContain('on_final=_hand_off(ctx)')
    expect(finalize).not.toMatch(/scan_status\s*=\s*'clean'/)
  })

  it('reads and scans only a final key, in the runtime and in the sweep', () => {
    const runtime = text(on, 'services/worker/koras_worker/scanning/runtime.py')
    expect(runtime).toContain('if not _is_final(str(row["storage_key"])):')
    expect(runtime).not.toMatch(/restore|legacy/i)
    const sweep = text(on, 'services/worker/koras_worker/tasks/scan_sweep.py')
    expect(sweep).toContain("^tenants/[^/]+/[^/]+/[^/]+/final/[^/]+/[^/]+$")
    expect(sweep).not.toContain('restore_requests')
    expect(text(on, 'services/api/koras_api/core/upload_window.py')).toContain('def is_final_key(')
  })

  it('writes the verdict only through the guarded transitions', () => {
    const transition = text(on, 'services/worker/koras_worker/scanning/transition.py')
    expect(transition).toContain("and status = 'ready' and scan_status = 'pending'")
    expect(transition).toContain('class CleanEvidence')
    for (const path of [
      'services/worker/koras_worker/scanning/runtime.py',
      'services/worker/koras_worker/tasks/scan.py',
      'services/worker/koras_worker/tasks/scan_sweep.py',
    ]) {
      expect(text(on, path), path).not.toMatch(/record_scan|update public\.files/)
    }
  })

  it('takes no environment, no derived host and no product name into the scanner', () => {
    const config = text(on, 'services/worker/koras_worker/scanning/config.py')
    expect(config).not.toMatch(/Environment|derived_host|_SCANNER_ENVIRONMENTS|docoris|Doppler/i)
    expect(config).toContain('def resolve_scanner(config: ScannerSettings) -> Scanner:')
    for (const path of SCANNER_PATHS.filter((p) => p.endsWith('.py'))) {
      expect(text(on, path), path).not.toMatch(/docoris|legacy_retrust|OD-1[0-9]|GR-\d{3}/i)
    }
  })
})

describe('the scanner settings are one declarative list, in both services, identically', () => {
  const api = text(on, 'services/api/koras_api/core/secure_files.py')
  const worker = text(on, 'services/worker/koras_worker/secure_files.py')

  it('adds the limits to SECURE_FILES_CHECKS with their ranges', () => {
    for (const module of [api, worker]) {
      expect(module).toContain('SCAN_CEILING_BYTES = 100 * 1024 * 1024')
      for (const env of [
        'FILE_SCAN_CONNECT_TIMEOUT_SECONDS',
        'FILE_SCAN_TIMEOUT_SECONDS',
        'FILE_SCAN_MAX_BYTES',
        'FILE_SCAN_MAX_ATTEMPTS',
      ]) {
        expect(module, env).toContain(`"${env}",`)
      }
      expect(module).toContain('_integer_within(1, SCAN_CEILING_BYTES)')
      expect(module).toContain('_seconds_up_to(60)')
      expect(module).toContain('_seconds_up_to(600)')
    }
  })

  it('shares one text between the API and the worker', () => {
    const shared = (t: string) => {
      const a = t.indexOf('# BEGIN SHARED')
      const b = t.indexOf('# END SHARED')
      expect(a).toBeGreaterThan(-1)
      expect(b).toBeGreaterThan(a)
      return t.slice(a, b)
    }
    expect(shared(worker)).toBe(shared(api))
    // and the template text, before rendering, which is what a refresh copies
    expect(shared(read('services/worker/koras_worker/secure_files.py.hbs'))).toBe(
      shared(read('services/api/koras_api/core/secure_files.py.hbs')),
    )
  })

  it('has the API state the same limits the worker enforces', () => {
    const settings = text(on, 'services/api/koras_api/core/settings.py')
    for (const field of [
      'file_scan_connect_timeout_seconds: float = 5.0',
      'file_scan_timeout_seconds: float = 120.0',
      'file_scan_max_bytes: int = 100 * 1024 * 1024',
      'file_scan_max_attempts: int = 12',
    ]) {
      expect(settings).toContain(field)
    }
    const config = text(on, 'services/worker/koras_worker/scanning/config.py')
    expect(config).toContain('MAX_SCAN_BYTES = 100 * MIB')
    expect(config).toContain('MAX_CONNECT_TIMEOUT_SECONDS = 60')
    expect(config).toContain('MAX_SCAN_TIMEOUT_SECONDS = 600')
  })

  it('refuses a worker whose limits are not numbers, naming the variable only', () => {
    expect(worker).toContain('except ValidationError as error:')
    expect(worker).toContain('SecureFilesConfigurationError([f"{name} is not valid" for name in names])')
  })

  it('declares the optional settings with their types and no switch', () => {
    const manifest = text(on, 'local/config/secrets.manifest')
    for (const line of [
      'FILE_SCAN_BACKEND supplied - enum:clamd',
      'FILE_SCAN_MAX_BYTES optional - int',
      'FILE_SCAN_MAX_ATTEMPTS optional - int',
      'FILE_SCAN_SWEEP_BATCH_SIZE optional - int',
      'FILE_SCAN_SWEEP_MAX_BATCHES optional - int',
      'FILE_SCAN_SWEEP_NOT_BEFORE optional',
    ]) {
      expect(manifest).toMatch(new RegExp(`^${line}$`, 'm'))
    }
  })
})

describe('the two scanner migrations are the Docoris ones, renumbered', () => {
  it('keeps the SQL bodies identical to the Docoris originals', () => {
    const body = (t: string) => t.slice(t.indexOf('\nbegin;'))
    expect(body(text(on, 'supabase/migrations/00040_file_scan_interrupted.sql'))).toContain(
      "'identity_insufficient', 'scan_interrupted'",
    )
    const indexes = body(text(on, 'supabase/migrations/00041_file_scan_due_indexes.sql'))
    expect(indexes).toContain('drop index if exists public.files_scan_pending_idx;')
    expect(indexes.match(/create index if not exists files_scan_due/g)).toHaveLength(2)
    expect(indexes.match(/size_bytes <= 104857600/g)).toHaveLength(2)
    expect(indexes.match(/make_interval\(secs => 1260\)/g)).toHaveLength(2)
  })

  it('numbers them after the finalizer migration and records the mapping', () => {
    const numbers = [...on.keys()]
      .map((p) => /^supabase\/migrations\/(\d{5})_/.exec(p)?.[1])
      .filter((n): n is string => n !== undefined)
      .map(Number)
    expect(Math.max(...numbers)).toBeGreaterThanOrEqual(41)
    expect(numbers).toEqual(expect.arrayContaining([39, 40, 41]))
    const docs = readFileSync(
      fileURLToPath(new URL('../../../docs/SECURE_FILES.md', import.meta.url)),
      'utf8',
    )
    expect(docs).toContain('`00040_file_scan_interrupted.sql` (layer 3) | `01017_file_scan_interrupted`')
    expect(docs).toContain('`00041_file_scan_due_indexes.sql` (layer 3) | `01018_file_scan_due_indexes`')
    expect(docs).toContain('`01019_file_derived_content_withdrawal`')
  })
})
