import { describe, it, expect, beforeAll, afterAll } from 'vitest'
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
 * `secure_files` (ADR 0013), layer 2: the upload foundation, in both modes.
 *
 * One router, one request model, one response shape; what differs is whether `checksum_sha256`
 * is required and what the ticket signs. This file renders the product both ways and asserts,
 * from the generated text, the half that is each mode's own. The behaviour is the generated
 * product's own tests (`tests/unit/test_upload_ticket_contract.py` in both modes,
 * `test_upload_finalization.py` and the integration suites in the secure one), which the
 * generator-integration workflow runs.
 */

const ROOT = join(tmpdir(), `koras-sf-up-${process.pid}-${Date.now()}`)

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

// `data_import` is on in both, because the import panel is the second upload surface.
const ON = ['secure_files', 'clamd', 'worker', 'data_import']
const off = render('sfupoff', { with: ['worker', 'data_import'] })
const on = render('sfupon', { with: ON })
const text = (files: Map<string, string>, path: string): string => {
  const found = files.get(path)
  expect(found, `${path} was not generated`).toBeDefined()
  return found!.split(String.fromCharCode(13)).join('')
}

const ROUTER = 'services/api/koras_api/routers/files.py'
const FILES_PANEL = 'apps/web/src/app/dashboard/files/FilesPanel.tsx'
const IMPORT_PANEL = 'apps/web/src/app/dashboard/imports/ImportPanel.tsx'

describe('without secure_files the upload contract is the one every product had', () => {
  const router = text(off, ROUTER)

  it('keeps the claim optional and signs nothing but what it always signed', () => {
    expect(router).toContain('checksum_sha256: str | None = Field(default=None, pattern=')
    expect(router).not.toContain('checksum_sha256: str = Field(')
    expect(router).toContain('headers = {"Content-Type": content_type}')
    expect(router).toContain('if body.checksum_sha256:')
    expect(router).toContain('key = object_key(tenant.id, file_id, body.name')
    expect(router).toContain('UPLOAD_URL_SECONDS = 15 * 60')
  })

  it('carries no trace of the secure path', () => {
    for (const marker of [
      'incoming_key',
      'upload_guard_headers',
      'provenance=',
      'enqueue_finalize',
      'finalize_enqueue',
      'upload_window',
      'JobsDep',
      'UPLOAD_CHECKSUM_CLAIM_INVALID',
      'is_incoming_key',
    ]) {
      expect(router, marker).not.toContain(marker)
    }
    expect(text(off, 'services/api/koras_api/core/errors.py')).not.toContain(
      'UPLOAD_CHECKSUM_CLAIM_INVALID',
    )
  })

  it('still hands a confirmed upload to the hooks, as it did', () => {
    expect(router).toContain('run_after_upload')
    expect(router).toContain('credentials: CredentialsDep')
    expect(router).toContain('checksum_sha256 = :checksum, checksum_verified_at = :verified')
  })

  it('generates none of the finalizer, its window, its job, its migration or its tests', () => {
    for (const path of [
      'services/api/koras_api/core/upload_window.py',
      'services/api/koras_api/core/finalize_jobs.py',
      'services/api/koras_api/core/finalize_enqueue.py',
      'services/api/koras_api/core/upload_audit.py',
      'services/worker/koras_worker/tasks/finalize.py',
      'supabase/migrations/00039_file_scan_attempts.sql',
      'packages/api-client/src/upload-claim.ts',
      'apps/web/src/lib/browser-upload.ts',
      'tests/unit/test_upload_finalization.py',
      'tests/integration/test_upload_finalization_real.py',
    ]) {
      expect(off.has(path), path).toBe(false)
    }
    expect([...off.keys()].filter((p) => p.startsWith('services/worker/koras_worker/uploads'))).toEqual([])
  })

  it('registers nothing in the worker and copies nothing extra into its image', () => {
    const worker = text(off, 'services/worker/koras_worker/worker.py')
    expect(worker).not.toMatch(/finalize/i)
    const image = text(off, 'services/worker/Dockerfile')
    expect(image).not.toMatch(/upload_window|finalize_jobs|upload_audit/)
    // (`data_import` brings `koras-audit` of its own, so it is the capability's own note that
    // must be absent here.)
    expect(text(off, 'services/worker/pyproject.toml')).not.toContain('The finalizer records')
  })

  it('leaves the web client unchanged: a digest that cannot be taken is not an error', () => {
    for (const path of [FILES_PANEL, IMPORT_PANEL]) {
      const panel = text(off, path)
      expect(panel, path).toContain('async function digestOf(file: File): Promise<string | null>')
      expect(panel, path).not.toContain('browser-upload')
    }
    expect(text(off, 'apps/web/src/app/dashboard/files/actions.ts')).toContain(
      'checksumSha256?: string | null',
    )
  })

  it('renders the contract test for this mode, and not the other', () => {
    const contract = text(off, 'tests/unit/test_upload_ticket_contract.py')
    expect(contract).toContain('assert SECURE is False')
    expect(contract).toContain('def test_the_claim_is_optional_and_a_ticket_without_one')
    expect(contract).not.toContain('def test_a_missing_claim_is_refused_when_the_ticket_is_issued')
  })

  it('backs up exactly what it always did', () => {
    const backup = text(off, 'services/worker/koras_worker/tasks/storage_backup.py')
    expect(backup).toContain('_DUE = _due_query(SECURE_FILES)')
    expect(backup).toContain('if secure_files else " "')
  })
})

describe('with secure_files the claim is required and the upload is confined', () => {
  const router = text(on, ROUTER)

  it('requires the claim, as one model, and binds it at issuance', () => {
    const ticket = router.slice(
      router.indexOf('class UploadRequest'),
      router.indexOf('class CompleteRequest'),
    )
    expect(ticket).toMatch(/checksum_sha256: str = Field\(\n\s+pattern=r"\^\[0-9a-f\]\{64\}\$"/)
    expect(ticket).not.toContain('checksum_sha256: str | None')
    // The completion's own digest stays optional: it is only ever compared with the bound one.
    expect(router).toContain('checksum_sha256: str | None = Field(default=None, pattern=')
    expect(router).toContain('status, uploaded_by, checksum_sha256)')
    expect(router).toContain('"checksum": body.checksum_sha256')
  })

  it('signs an incoming key and the copy-source guard, and always names the upload id', () => {
    expect(router).toContain('key = incoming_key(')
    expect(router).not.toContain('object_key(')
    expect(router).toContain('provenance=upload_id')
    expect(router).toContain('**upload_guard_headers(upload_id)')
    expect(router).toContain('"x-amz-checksum-sha256": _b64(body.checksum_sha256)')
  })

  it('refuses a completion that changes the claim and never invents one', () => {
    expect(router).toContain('UPLOAD_CHECKSUM_CLAIM_INVALID')
    expect(router).toContain('bound = (row.checksum_sha256 or "").lower()')
    expect(router).toContain('claimed = bound')
    expect(router).toContain('text("update public.files set status = \'ready\', ready_at = :now where id = :id")')
    // No digest is read back from the provider, and no hook is handed an unverified URL.
    expect(router).not.toContain('storage.store.checksum(')
    expect(router).not.toContain('run_after_upload')
    expect(router).not.toContain('credentials: CredentialsDep')
  })

  it('hands the confirmed upload to the finalizer after the response, and refuses an incoming key', () => {
    expect(router).toContain('enqueue_finalize,')
    expect(router).toContain('jobs: JobsDep')
    expect(router).toContain('if is_incoming_key(row.storage_key):')
    expect(router.indexOf('if is_incoming_key(row.storage_key):')).toBeLessThan(
      router.indexOf('presign_download('),
    )
  })

  it('declares the new refusal only here', () => {
    expect(text(on, 'services/api/koras_api/core/errors.py')).toContain(
      'UPLOAD_CHECKSUM_CLAIM_INVALID = "upload_checksum_claim_invalid"',
    )
  })

  it('generates the finalizer, its window, its job, its migration and its tests', () => {
    for (const path of [
      'services/api/koras_api/core/upload_window.py',
      'services/api/koras_api/core/finalize_jobs.py',
      'services/api/koras_api/core/finalize_enqueue.py',
      'services/api/koras_api/core/upload_audit.py',
      'services/worker/koras_worker/uploads/finalize.py',
      'services/worker/koras_worker/uploads/_audit.py',
      'services/worker/koras_worker/tasks/finalize.py',
      'supabase/migrations/00039_file_scan_attempts.sql',
      'packages/api-client/src/upload-claim.ts',
      'packages/api-client/src/upload-claim.test.ts',
      'apps/web/src/lib/browser-upload.ts',
      'tests/unit/upload_store_support.py',
      'tests/unit/test_upload_finalization.py',
      'tests/unit/test_upload_finalize_task.py',
      'tests/integration/test_upload_finalization_real.py',
      'tests/integration/test_upload_checksum_provenance_real.py',
      'tests/integration/test_upload_finalization_provider.py',
      'tests/integration/test_upload_checksum_provider.py',
    ]) {
      expect(on.has(path), path).toBe(true)
    }
  })

  it('binds the finalizer in the worker by name and schedules its sweep', () => {
    const worker = text(on, 'services/worker/koras_worker/worker.py')
    expect(worker).toContain('from .tasks.finalize import bound as finalize_tasks')
    expect(worker).toContain('*worker_functions(finalize_tasks()),')
    expect(worker).toContain('cron(sweep_finalize, minute={2, 7, 12, 17, 22, 27, 32, 37, 42, 47, 52, 57}, timeout=1800)')
  })

  it('carries the finalizer into the worker image and declares what it imports', () => {
    const image = text(on, 'services/worker/Dockerfile')
    for (const file of ['upload_window', 'finalize_jobs', 'upload_audit', 'audit', 'rebind']) {
      expect(image).toContain(`COPY services/api/koras_api/core/${file}.py`)
    }
    expect(text(on, 'services/worker/pyproject.toml')).toMatch(/"koras-audit",/)
  })

  it('makes the queue and the database mandatory settings, in both services, identically', () => {
    for (const path of [
      'services/api/koras_api/core/secure_files.py',
      'services/worker/koras_worker/secure_files.py',
    ]) {
      const module = text(on, path)
      expect(module, path).toContain('"redis_url",\n        "REDIS_URL",')
      expect(module, path).toContain('"database_url",\n        "DATABASE_URL",')
    }
    expect(text(on, 'services/worker/koras_worker/secure_files.py')).toContain('redis_url: str = ""')
  })

  it('computes the claim in the browser and refuses to upload without it', () => {
    for (const path of [FILES_PANEL, IMPORT_PANEL]) {
      const panel = text(on, path)
      expect(panel, path).toContain("from '../../../lib/browser-upload'")
      expect(panel, path).not.toContain('Promise<string | null>')
    }
    expect(text(on, 'apps/web/src/app/dashboard/files/actions.ts')).toMatch(
      /contentType: string\n\s+checksumSha256: string\n\}\)/,
    )
    expect(text(on, 'apps/web/src/lib/browser-upload.ts')).toContain(
      `@sfupon/api-client/src/upload-claim`,
    )
  })

  it('renders the contract test for this mode, and not the other', () => {
    const contract = text(on, 'tests/unit/test_upload_ticket_contract.py')
    expect(contract).toContain('assert SECURE is True')
    expect(contract).toContain('def test_a_missing_claim_is_refused_when_the_ticket_is_issued')
    expect(contract).not.toContain('def test_the_claim_is_optional_and_a_ticket_without_one')
  })

  it('names the settings the round-trip harness API refuses to start without', () => {
    const harness = text(on, 'playwright.config.ts')
    for (const name of [
      'FILE_SCAN_BACKEND',
      'FILE_SCAN_CLAMD_HOST',
      'STORAGE_ENDPOINT',
      'STORAGE_BUCKET',
      'STORAGE_ACCESS_KEY',
      'STORAGE_SECRET_KEY',
      'REDIS_URL',
    ]) {
      expect(harness, name).toContain(name + ':')
    }
    expect(text(off, 'playwright.config.ts')).not.toContain('FILE_SCAN_BACKEND')
  })

  it('refuses to back up a key a ticket could write', () => {
    const backup = text(on, 'services/worker/koras_worker/tasks/storage_backup.py')
    expect(backup).toContain("storage_key not like '%/incoming/%'")
  })
})

describe('the migration is the one Docoris proved', () => {
  const read = (p: string) =>
    readFileSync(templatePath('product', p), 'utf8').split(String.fromCharCode(13)).join('')
  const migration = read('supabase/migrations/00039_file_scan_attempts.sql')

  it('is numbered after the last one the starter had, and is idempotent', () => {
    const numbers = [...on.keys()]
      .map((p) => /^supabase\/migrations\/(\d{5})_/.exec(p)?.[1])
      .filter((n): n is string => n !== undefined)
      .map(Number)
    // The first the capability adds follows the last one the starter had (00038); the scanner's
    // two follow it (`product-secure-files-scanner.test.ts`).
    expect(Math.min(...numbers.filter((n) => n >= 39))).toBe(39)
    expect(numbers).toContain(38)
    expect(migration).toContain('add column if not exists scan_attempts smallint not null default 0')
    expect(migration).toContain('drop constraint if exists files_scan_failure_check')
    expect(migration).toContain('drop constraint if exists files_scan_attempts_check')
  })

  it('has the twelve words of the closed vocabulary, and no scanner-only thirteenth', () => {
    for (const word of [
      'scanner_unavailable',
      'scan_timeout',
      'malformed_response',
      'scanner_error',
      'object_unreachable',
      'object_changed',
      'integrity_mismatch',
      'over_ceiling',
      'misconfigured',
      'scan_limit_exceeded',
      'inspection_incomplete',
      'identity_insufficient',
    ]) {
      expect(migration, word).toContain(`'${word}'`)
    }
    expect(migration).not.toContain('scan_interrupted')
  })

  it('is absent from a product without the capability', () => {
    expect([...off.keys()].filter((p) => p.includes('00039'))).toEqual([])
  })
})

describe('the shared storage package keeps working for a product that never asks for the guard', () => {
  const read = (p: string) =>
    readFileSync(templatePath('product', p), 'utf8').split(String.fromCharCode(13)).join('')
  const storage = read('python-packages/koras-storage/src/koras_storage/__init__.py')

  it('leaves provenance optional, so the old call signs what it always signed', () => {
    expect(storage).toMatch(/provenance: str \| None = None,/)
    expect(storage).not.toMatch(/\n\s+provenance: str \| None,\n/)
  })

  it('is identical in a product with and without the capability', () => {
    expect(text(on, 'python-packages/koras-storage/src/koras_storage/__init__.py')).toBe(
      text(off, 'python-packages/koras-storage/src/koras_storage/__init__.py'),
    )
  })
})

describe('both profiles render', () => {
  it('the control plane does not carry any of it', () => {
    const { manifest, defaults } = loadProfile('control-plane' as ProfileName)
    const selections = resolveSelections(manifest, defaults)
    validateSelections(manifest, selections)
    const ctx = buildContext({
      projectName: 'sfcp',
      projectSlug: 'sfcp',
      profile: 'control-plane' as ProfileName,
      manifest,
      defaults,
      selections,
      outputDir: ROOT,
      dryRun: false,
      provision: false,
    })
    const paths = renderTemplate(ctx).map((f) => f.outputPath.replace(/\\/g, '/'))
    expect(paths.filter((p) => /upload_window|finalize|upload-claim|browser-upload/.test(p))).toEqual([])
  })
})
