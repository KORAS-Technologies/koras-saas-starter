import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { createHash } from 'node:crypto'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { mkdirSync, rmSync, existsSync, readFileSync } from 'node:fs'
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
 * `secure_files` (ADR 0013), layer 5: restore and replacement, in both modes and with and
 * without the capability that owns restore.
 *
 * Restore is `storage_governance`'s; what `secure_files` changes is how the worker writes. The
 * shape is one implementation, rendered by the capability: without `secure_files` the restore is
 * the Starter's existing one **byte for byte**; with it the replacement is a new final-shaped
 * object that begins `pending`. The files that only exist when both capabilities are on are
 * listed under both in the manifest, so a product with one and not the other gets none of them.
 * The behaviour is the generated product's own suites
 * (`tests/unit/test_storage_restore_replacement.py`, `tests/integration/test_restore_*_real.py`),
 * which the generator-integration workflow runs.
 */

const ROOT = join(tmpdir(), `koras-sf-restore-${process.pid}-${Date.now()}`)

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

const SECURE = ['secure_files', 'clamd', 'worker']
// The default product, with the worker restore runs in.
const off = render('sfrstoff', { with: ['worker'] })
const on = render('sfrston', { with: SECURE })
const onAi = render('sfrstai', { with: [...SECURE, 'ai', 'ai_gateway'] })
const onNoGovernance = render('sfrstnogov', { with: SECURE, without: ['storage_governance'] })
const offNoGovernance = render('sfrstoffnogov', { with: ['worker'], without: ['storage_governance'] })

const CR = String.fromCharCode(13)
const text = (files: Map<string, string>, path: string): string => {
  const found = files.get(path)
  expect(found, `${path} was not generated`).toBeDefined()
  return found!.split(CR).join('')
}
const read = (path: string): string =>
  readFileSync(templatePath('product' as ProfileName, path), 'utf8').split(CR).join('')
const sha256 = (value: string): string => createHash('sha256').update(value).digest('hex')

const WORKER = 'services/worker/koras_worker/tasks'
const RESTORE = `${WORKER}/storage_restore.py`
const RESTORE_UNIT = 'tests/unit/test_storage_restore.py'
const BOTH = [
  `${WORKER}/restore_scan.py`,
  'tests/unit/restore_support.py',
  'tests/unit/test_storage_restore_replacement.py',
  'tests/unit/test_restore_scan.py',
  'tests/integration/test_restore_replacement_real.py',
  'tests/integration/test_restore_orchestration_real.py',
]
const BOTH_WITH_AI = 'tests/integration/test_restore_derived_content_real.py'
/** What `storage_governance` generates whatever `secure_files` is. */
const RESTORE_FILES = [
  'services/api/koras_api/core/restore.py',
  'services/api/koras_api/routers/restore.py',
  RESTORE,
  RESTORE_UNIT,
  'supabase/migrations/00026_restore_requests.sql',
  'supabase/tests/250_restore_isolation.sql',
  'apps/web/src/app/dashboard/restore/RestorePanel.tsx',
]

/**
 * The text of the Starter's restore worker task and its unit test as they were before the
 * capability touched them (`13deb7d`), LF-normalized. A product generated without `secure_files`
 * must render exactly this: the rendering is checked against the hash so that a change to the
 * legacy half has to be made here, on purpose, and not as a side effect of the secure half.
 */
const LEGACY = {
  [RESTORE]: 'bf3a958b9f794a2ef7c73d017310fff4750f212c9b28cd2fb75b2538002af98c',
  [RESTORE_UNIT]: '0099faeed8640bc53b24360b050f2ff10b819eae8e0eefca5d6d9ac35971f017',
}

describe('without secure_files restore is exactly what it was', () => {
  it('renders the restore worker task and its unit test byte for byte as before', () => {
    for (const [path, digest] of Object.entries(LEGACY)) {
      expect(sha256(text(off, path)), path).toBe(digest)
    }
  })

  it('generates none of the layer-5 files and no template token survives', () => {
    for (const path of [...BOTH, BOTH_WITH_AI]) expect(off.has(path), path).toBe(false)
    for (const path of RESTORE_FILES) expect(text(off, path)).not.toContain('{{')
  })

  it('still overwrites the original key, which is the legacy behaviour the capability replaces', () => {
    const task = text(off, RESTORE)
    expect(task).toContain('target.put(original.storage_key')
    expect(task).toContain('_TOUCH_FILE')
    for (const secure of [
      'replacement_key',
      '_write_verified',
      '_REPLACE_FILE',
      'restore_scan',
      'final_key',
    ]) {
      expect(task, secure).not.toContain(secure)
    }
  })

  it('has no scan-status writer in the restore for the guard registry to find', () => {
    const guards = text(off, 'tests/unit/test_release_bypass_guards.py')
    expect(guards).toContain(
      '"services/worker/koras_worker/tasks/storage_restore.py": frozenset({"\'pending\'"})',
    )
    expect(text(off, RESTORE)).not.toMatch(/scan_status\s*=/)
  })
})

describe('with secure_files and storage_governance the replacement is a new final-shaped object', () => {
  it('generates the restore follow-up, the shared stand-ins and the suites', () => {
    for (const path of BOTH) expect(on.has(path), path).toBe(true)
    expect(on.has(BOTH_WITH_AI), 'the derived-content suite needs the assistant').toBe(false)
    for (const path of RESTORE_FILES) expect(on.has(path), path).toBe(true)
  })

  it('renders no template token anywhere in the restore files', () => {
    for (const path of [...BOTH, ...RESTORE_FILES]) expect(text(on, path), path).not.toContain('{{')
  })

  it('never writes the original key and names the key through the one window module', () => {
    const task = text(on, RESTORE)
    expect(task).not.toContain('put(original.storage_key')
    expect(task).not.toContain('_TOUCH_FILE')
    expect(task.match(/\.put\(/g)).toHaveLength(1)
    expect(task).toContain('target.put(key, content, content_type, checksum_sha256=digest)')
    expect(task).toContain('importlib.import_module("koras_api.core.upload_window")')
    expect(task).toContain('_window().final_key(')
    expect(task).not.toMatch(/from koras_api|import koras_api/)
  })

  it('resets the verdict and every piece of evidence about the old bytes in one statement', () => {
    const task = text(on, RESTORE)
    const statement = task.slice(
      task.indexOf('_REPLACE_FILE = text('),
      task.indexOf('"returning created_at"', task.indexOf('_REPLACE_FILE = text(')),
    )
    for (const needed of [
      'storage_key = :new_key',
      "scan_status = 'pending'",
      'scan_note = null',
      'scan_attempts = 0',
      'scan_attempted_at = null',
      'scan_failure = null',
      'scan_object_etag = null',
      'indexed_at = null',
      'index_note = null',
      "backup_status = 'none'",
      'storage_key = :old_key',
      'status = :seen_status',
      'scan_status = :seen_scan',
    ]) {
      expect(statement, needed).toContain(needed)
    }
    expect(statement).not.toContain("scan_status = 'clean'")
    expect(statement).not.toContain('scan_object_etag = :')
  })

  it('reads what it wrote back before a row may name it, and refuses a mismatch', () => {
    const task = text(on, RESTORE)
    expect(task).toContain('def _write_verified(')
    expect(task).toContain('hashlib.sha256(written).hexdigest() == digest')
    expect(task).toContain('checksum_verified_at = now()')
  })

  it('asks the scanner after the commit and follows up, through the one enqueue function', () => {
    const task = text(on, RESTORE)
    expect(task).toContain('await request_scans_for_restored(ctx, restored)')
    expect(task).toContain('await reconcile_restored_scans(ctx, session)')
    const follow = text(on, `${WORKER}/restore_scan.py`)
    expect(follow.match(/enqueue_scan\(/g)).toHaveLength(1)
    expect(follow).not.toContain('.enqueue(')
    expect(follow).not.toContain('scanner_active')
    expect(follow).not.toContain('ScanActivation')
    expect(follow).not.toMatch(/from \.\.scanning|koras_worker\.scanning/)
    expect(follow).toContain("final/[^/]+/[^/]+$'")
  })

  it("selects the backup on the request's own tenant and file", () => {
    const task = text(on, RESTORE)
    expect(task).toContain('b.tenant_id = r.tenant_id and b.file_id = r.file_id')
  })

  it('registers the restore writer for the scan-status guard and the scan-task guard', () => {
    const guards = text(on, 'tests/unit/test_release_bypass_guards.py')
    expect(guards).toContain(
      '"services/worker/koras_worker/tasks/storage_restore.py": frozenset({"\'pending\'"})',
    )
    expect(text(on, 'tests/unit/test_scan_task.py')).toContain(
      'services/worker/koras_worker/tasks/restore_scan.py',
    )
  })

  it("adds the key and the deferral to the capability's own modules, not the legacy ones", () => {
    const window = text(on, 'services/api/koras_api/core/upload_window.py')
    expect(window).toContain('def final_key(')
    expect(window).toContain('{FINAL}/{generation}/{name}')
    expect(text(on, 'services/api/koras_api/core/scan_enqueue.py')).toContain(
      'delay_seconds: float | None = None',
    )
    expect(off.has('services/api/koras_api/core/upload_window.py')).toBe(false)
    expect(off.has('services/api/koras_api/core/scan_enqueue.py')).toBe(false)
  })

  it('renders the unit test for the secure result type', () => {
    const unit = text(on, RESTORE_UNIT)
    expect(unit).toContain('ran = await run_one(')
    expect(unit).toContain('assert ran.outcome == "completed"')
    expect(unit).toContain('def scalar_one(self)')
    expect(unit).not.toContain('outcome, _, _ = await run_one(')
  })

  it("withdraws the file's chunks with the replacement only when the assistant is generated", () => {
    expect(text(on, RESTORE)).not.toContain('ai_knowledge_chunks')
    expect(text(on, RESTORE)).not.toContain('_WITHDRAW_CHUNKS')
    const withAi = text(onAi, RESTORE)
    expect(withAi).toContain('_WITHDRAW_CHUNKS = text(')
    expect(withAi).toContain('delete from public.ai_knowledge_chunks')
    expect(withAi.match(/_WITHDRAW_CHUNKS,/g)).toHaveLength(1)
    expect(onAi.has(BOTH_WITH_AI)).toBe(true)
  })

  it('documents restore for the operator, with the capability', () => {
    expect(text(on, 'docs/SECURE_FILES.md')).toContain('## Restoring a file')
    expect(off.has('docs/SECURE_FILES.md')).toBe(false)
  })
})

describe('secure_files without storage_governance has no restore, so there is nothing to bring under the rule', () => {
  it('generates no restore at all and none of the layer-5 files', () => {
    for (const path of [...RESTORE_FILES, ...BOTH, BOTH_WITH_AI]) {
      expect(onNoGovernance.has(path), path).toBe(false)
    }
    expect(onNoGovernance.has('docs/SECURE_FILES.md')).toBe(true)
  })

  it('does not tell the operator how to restore a file that cannot be restored', () => {
    expect(text(onNoGovernance, 'docs/SECURE_FILES.md')).not.toContain('## Restoring a file')
  })

  it('keeps the rest of the chain: the scanner, the finalizer and the release rule', () => {
    for (const path of [
      `${WORKER}/scan.py`,
      `${WORKER}/finalize.py`,
      'services/api/koras_api/core/file_release.py',
      'tests/unit/test_release_bypass_guards.py',
    ]) {
      expect(onNoGovernance.has(path), path).toBe(true)
    }
    // The guards that name the restore writer do so by path and only where it exists.
    expect(text(onNoGovernance, 'tests/unit/test_scan_task.py')).toContain('(REPO / name).exists()')
  })

  it('binds no restore task in a product that has none', () => {
    expect(text(onNoGovernance, 'services/worker/koras_worker/worker.py')).not.toContain(
      'storage_restore',
    )
    expect(text(offNoGovernance, 'services/worker/koras_worker/worker.py')).not.toContain(
      'storage_restore',
    )
  })
})

describe('the templates themselves', () => {
  it('keeps both halves of the restore worker task in the one template', () => {
    const template = read(RESTORE)
    expect(template).toContain('{{#if capability.secure_files}}')
    expect(template).toContain('{{else}}')
    expect(template).toContain('{{#if capability.ai}}')
  })

  it('lists the layer-5 files under both capabilities, so a product needs both to get them', () => {
    const manifest = readFileSync(
      join(__dirname, '..', '..', '..', 'profiles', 'product', 'manifest.yaml'),
      'utf8',
    )
    for (const path of BOTH) {
      expect(manifest.split(`- ${path}`).length - 1, path).toBe(2)
    }
    expect(manifest.split(`- ${BOTH_WITH_AI}`).length - 1).toBe(3)
  })
})
