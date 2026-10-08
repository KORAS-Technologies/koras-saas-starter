import { describe, expect, it } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  CHECK_DEADLINE_MS,
  CHECK_FIRST_MS,
  CHECK_MAX_MS,
  PENDING_KEY,
  PENDING_MAX_AGE_MS,
  checkDelay,
  isWaiting,
  parsePending,
  pendingKey,
  phaseOf,
} from '../../../profiles/product/template/apps/web/src/app/dashboard/imports/source-state'
import { templatePath } from './template-path'

/**
 * A freshly uploaded import source is a wait, not a refusal.
 *
 * The pure half (the wait's schedule, the remembered entry, the closed reading of the
 * server's word) is **executed**: `source-state.ts` is plain TypeScript with no generated
 * import for exactly that reason. The rest is read from the template text, because the
 * template has no browser test runner; the page's behaviour is exercised in the product
 * repository that proved it.
 */

const PRODUCT = join(templatePath('product', 'package.json.hbs'), '..')

function read(...segments: string[]): string {
  const plain = join(PRODUCT, ...segments)
  const file = existsSync(plain) || !existsSync(`${plain}.hbs`) ? plain : `${plain}.hbs`
  return readFileSync(file, 'utf8').split(String.fromCharCode(13)).join('')
}

describe('source-state — executed', () => {
  it('only the server word ready is ready; checking is the one wait; the rest end it', () => {
    expect(phaseOf('ready')).toBe('ready')
    expect(phaseOf('checking')).toBe('checking')
    expect(phaseOf('held')).toBe('held')
    expect(phaseOf('rejected')).toBe('rejected')
    expect(phaseOf('missing')).toBe('missing')
    for (const word of ['', 'READY', 'ready ', 'clean', 'pending']) {
      expect(phaseOf(word), `a word this build has never heard of: ${word}`).toBe('missing')
    }
    expect(isWaiting('checking')).toBe(true)
    for (const phase of ['idle', 'ready', 'held', 'rejected', 'missing', 'stalled'] as const) {
      expect(isWaiting(phase), phase).toBe(false)
    }
  })

  it('doubles from ten seconds to a minute, and outlasts the upload window', () => {
    expect([0, 1, 2, 3, 4, 9].map(checkDelay)).toEqual([10_000, 20_000, 40_000, 60_000, 60_000, 60_000])
    expect(checkDelay(-3)).toBe(CHECK_FIRST_MS)
    expect(checkDelay(99)).toBe(CHECK_MAX_MS)
    expect(CHECK_DEADLINE_MS).toBeGreaterThan(25 * 60_000)
  })

  const NOW = 1_800_000_000_000
  const entry = (over: Record<string, unknown> = {}): string =>
    JSON.stringify({
      fileId: 'f',
      name: 'a.csv',
      size: 5,
      target: 'shop.customers',
      operation: 'skip_duplicate',
      at: NOW - 1000,
      ...over,
    })

  it('reads a remembered upload back only when it is whole, recent and not from the future', () => {
    expect(parsePending(entry(), NOW)).toEqual({
      fileId: 'f',
      name: 'a.csv',
      size: 5,
      target: 'shop.customers',
      operation: 'skip_duplicate',
      at: NOW - 1000,
    })
    for (const raw of [null, '', '{nope', '[]', '"x"']) expect(parsePending(raw, NOW)).toBeNull()
    expect(parsePending(entry({ at: NOW - PENDING_MAX_AGE_MS - 1 }), NOW)).toBeNull()
    expect(parsePending(entry({ at: NOW + 10 * 60_000 }), NOW)).toBeNull()
    for (const field of ['fileId', 'name', 'size', 'target', 'operation', 'at']) {
      expect(parsePending(entry({ [field]: undefined }), NOW), field).toBeNull()
      expect(parsePending(entry({ [field]: { x: 1 } }), NOW), field).toBeNull()
    }
  })

  it('drops extra fields of a remembered entry rather than passing them on', () => {
    const read = parsePending(entry({ token: 'secret', url: 'https://x' }), NOW)
    expect(Object.keys(read ?? {}).sort()).toEqual(['at', 'fileId', 'name', 'operation', 'size', 'target'])
  })

  it('keys the remembered wait per organisation and person', () => {
    expect(pendingKey('')).toBe(PENDING_KEY)
    expect(pendingKey('org-1:user-1')).not.toBe(pendingKey('org-1:user-2'))
    expect(pendingKey('org-1:user-1')).not.toBe(pendingKey('org-2:user-1'))
  })
})

describe('the pending-source wait — read from the template', () => {
  const core = read('services/api/koras_api/core/imports.py')
  const router = read('services/api/koras_api/routers/imports.py')
  const panel = read('apps/web/src/app/dashboard/imports/ImportPanel.tsx')

  it('names a pending file as a wait and everything else as before', () => {
    expect(core).toContain('raise SourceRefused("import.source.pending")')
    expect(core).toContain('raise SourceRefused("import.source.unscanned")')
    expect(core).toContain('async def source_state(')
    // Only the upload-window rendering treats a pending scan or upload as a wait.
    expect(core).toContain('{{#if capability.secure_files}}\n    if row.status == "pending":')
    // Release rule untouched: the state function applies it, it does not restate it.
    expect(core).toContain('_row_clears(row)')
    expect(router).toContain('FILE_SCAN_PENDING')
    expect(read('services/worker/koras_worker/tasks/imports.py')).toContain('"import.source.pending"')
  })

  it('declares the read-only source route before the run route, behind the router-wide gate', () => {
    expect(router).toContain('@router.get("/imports/sources/{file_id}"')
    expect(router.indexOf('/imports/sources/{file_id}')).toBeLessThan(router.indexOf('@router.get("/imports/{run_id}"'))
    expect(router).toContain('_require(claims, "checking an import source")')
  })

  it('starts a run only on the server saying ready, and never from a restored wait', () => {
    expect(panel).toContain('await checkSource(source.fileId)')
    expect(panel).toContain("next === 'ready' && resumed.current === source.fileId")
    expect(panel).toContain('generation.current')
    // A stale ask must not release a slot a newer ask holds, and Continue waits for idle.
    expect(panel).toContain('if (mine === generation.current) asking.current = false')
    expect(panel).toContain('onClick={continueResumed} disabled={busy}')
    expect(panel).toContain('storageScope')
    // The upload handler no longer starts the run itself.
    const choose = panel.slice(panel.indexOf('const choose = useCallback('), panel.indexOf('const check = useCallback('))
    expect(choose).not.toContain('await startRun(')
  })

  it('ships the ten source sentences in every language', () => {
    for (const lang of ['en', 'es', 'de']) {
      const messages = read(`packages/i18n/src/messages/${lang}.ts`)
      for (const key of ['checking', 'ready', 'stalled', 'held', 'rejected', 'missing', 'unreachable', 'checkAgain', 'continue', 'stop']) {
        expect(messages, `${lang} ${key}`).toContain(`'imports.source.${key}'`)
      }
    }
  })
})
