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
 * `secure_files` (ADR 0013), layer 4: the release layer, in both modes.
 *
 * `core/file_release.py` is generated in every product and dispatches on the one generated
 * constant; everything else that releases or derives from a file's bytes is either the same code
 * in both modes (the primitive) or rendered by the capability. This file renders the product
 * both ways, with and without the assistant and data import, and asserts from the generated text
 * the half that is each mode's own. The behaviour is the generated product's own tests
 * (`tests/unit/test_file_release.py`, `test_files_release_api.py`, `test_release_bypass_guards.py`,
 * `test_ai_indexing_gate.py`, and the integration suites against a real PostgreSQL), which the
 * generator-integration workflow runs.
 */

const ROOT = join(tmpdir(), `koras-sf-release-${process.pid}-${Date.now()}`)

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

const OPTIONAL = ['worker', 'ai', 'ai_gateway', 'data_import']
const off = render('sfreloff', { with: OPTIONAL })
const on = render('sfrelon', { with: ['secure_files', 'clamd', ...OPTIONAL] })
const onBare = render('sfrelbare', { with: ['secure_files', 'clamd', 'worker'] })
const offBare = render('sfreloffbare')

const CR = String.fromCharCode(13)
const text = (files: Map<string, string>, path: string): string => {
  const found = files.get(path)
  expect(found, `${path} was not generated`).toBeDefined()
  return found!.split(CR).join('')
}
const read = (path: string): string =>
  readFileSync(templatePath('product' as ProfileName, path), 'utf8').split(CR).join('')

const API = 'services/api/koras_api'
const GATED = [
  `${API}/core/file_release_gate.py`,
  `${API}/core/release_audit.py`,
  'supabase/migrations/00042_file_derived_content_withdrawal.sql',
  'supabase/tests/360_file_derived_content_withdrawal.sql',
  'tests/unit/test_files_lazy_indexing_api.py',
  'tests/unit/test_ai_indexing_gate.py',
  'tests/unit/test_derived_content_withdrawal_static.py',
  'tests/integration/test_file_release_real.py',
  'tests/integration/test_file_derived_content_real.py',
  'packages/api-client/src/file-state.ts',
  'packages/api-client/src/file-state.test.ts',
  'e2e/roundtrip/files-release-state.spec.ts',
]
const ALWAYS = [
  `${API}/core/file_release.py`,
  'tests/unit/test_file_release.py',
  'tests/unit/test_files_release_api.py',
  'tests/unit/test_release_bypass_guards.py',
  'tests/unit/release_support.py',
]

describe('without secure_files the release layer is the rule and nothing else', () => {
  it('generates the always-on rule and its tests, and none of the capability-only files', () => {
    for (const path of ALWAYS) expect(off.has(path), path).toBe(true)
    for (const path of GATED) expect(off.has(path), path).toBe(false)
  })

  it('renders the rule dispatching on the generated constant, with the legacy answers in it', () => {
    const rule = text(off, `${API}/core/file_release.py`)
    expect(rule).toContain('from .secure_files import SECURE_FILES')
    expect(rule).toContain('if not SECURE_FILES:')
    expect(rule).toContain('LEGACY_WITHHELD: Final[frozenset[str]] = frozenset({"infected"})')
    expect(rule).toContain('LEGACY_IMPORT_REFUSED: Final[frozenset[str]] = frozenset({"pending", "skipped", "infected"})')
    // The rule's only imports: the worker image copies it beside `secure_files.py`.
    expect([...rule.matchAll(/^(?:from|import) (\S+)/gm)].map((m) => m[1])).toEqual([
      '__future__',
      'uuid',
      'typing',
      '.secure_files',
    ])
  })

  it('keeps the legacy download on the platform deny-list, reached through the one rule', () => {
    const router = text(off, `${API}/routers/files.py`)
    expect(router).toContain('from ..core.file_release import releasable')
    expect(router).toContain('if not releasable(status="ready", scan_status=row.scan_status):')
    expect(router).not.toMatch(/withheld\(|import withheld|require_releasable|file_release_gate/)
    // The legacy router still hands a hook a signed URL at upload, and the list is as it was.
    expect(router).toContain('run_after_upload')
    expect(router).toContain('hooks.for_upload(row.content_type)')
    expect(router).not.toContain('content_available')
    expect(router).not.toContain('LAZY_HOOKS_PER_LIST')
  })

  it('keeps the legacy hooks, the eager indexer and the unguarded retrieval', () => {
    const hooks = text(off, `${API}/core/file_hooks.py`)
    expect(hooks).toContain('after_upload: Callable[..., Awaitable[int]] | None = None')
    expect(hooks).toContain('async def run_after_upload')
    expect(hooks).not.toMatch(/after_clean|for_clean|run_after_clean/)
    const indexing = text(off, `${API}/core/file_indexing.py`)
    expect(indexing).toContain('after_upload=index_uploaded_file')
    const ai = text(off, `${API}/core/ai.py`)
    expect(ai).toContain('async def index_uploaded_file(')
    expect(ai).toContain('import httpx')
    expect(ai).not.toMatch(/read_releasable|RELEASABLE_SQL|index_clean_file|_withhold/)
    const knowledge = text(off, `${API}/core/knowledge.py`)
    expect(knowledge).not.toMatch(/RELEASABLE_SQL|_WRITE_GUARD|index_file_document|ReadIdentity/)
    expect(text(off, `${API}/ai/tools.py`)).not.toMatch(/content_available|row_releasable/)
  })

  it('keeps the legacy import gate, with its own narrower deny-list', () => {
    const imports = text(off, `${API}/core/imports.py`)
    expect(imports).toContain('UNPARSEABLE_SCANS: frozenset[str] = frozenset({"pending", "skipped", "infected"})')
    expect(imports).toContain('if (row.scan_status or "pending") in UNPARSEABLE_SCANS:')
    expect(imports).not.toMatch(/file_release|releasable|session_tenant_id/)
  })

  it('adds no schema, no audit action, no worker copy and no wiring', () => {
    const migrations = [...off.keys()].filter((p) => p.startsWith('supabase/migrations/'))
    expect(migrations.some((m) => /00042/.test(m))).toBe(false)
    expect(text(off, 'services/worker/Dockerfile')).not.toMatch(/file_release|secure_files/)
    expect(text(off, `${API}/core/errors.py`)).not.toContain('FILE_SCAN_PENDING')
    expect(text(off, `${API}/core/file_scan.py`)).toBe(read(`${API}/core/file_scan.py`))
  })

  it('shows the files list as it was: no availability column, no polling', () => {
    const panel = text(off, 'apps/web/src/app/dashboard/files/FilesPanel.tsx')
    expect(panel).not.toMatch(/availabilityOf|file-state|data-state|statusAvailable|files-notice/)
    expect(panel).toContain('INDEXING_GRACE_MS')
    const actions = text(off, 'apps/web/src/app/dashboard/files/actions.ts')
    expect(actions).not.toContain('code?: string')
  })

  it('ships the both-modes API test, with the legacy half rendered', () => {
    expect(text(off, 'tests/unit/test_files_release_api.py')).not.toContain('file_scan_pending')
    expect(text(off, 'tests/unit/test_files_release_api.py')).toContain(
      'test_a_rows_identity_is_not_consulted_without_the_capability',
    )
    expect(text(offBare, 'tests/unit/test_files_release_api.py')).toContain('DECISIONS')
  })
})

describe('with secure_files the release layer is generated and wired as one unit', () => {
  it('generates every capability-only file, and the always-on ones as well', () => {
    for (const path of [...ALWAYS, ...GATED]) expect(on.has(path), path).toBe(true)
  })

  it('without the assistant the assistant-only tests are present and empty, and nothing else is missing', () => {
    for (const path of ALWAYS) expect(onBare.has(path), path).toBe(true)
    for (const path of GATED) expect(onBare.has(path), path).toBe(true)
    expect(text(onBare, 'tests/unit/test_ai_indexing_gate.py')).not.toContain('index_clean_file')
    expect(text(onBare, 'tests/integration/test_file_derived_content_real.py')).not.toContain(
      'ai_knowledge_chunks',
    )
    expect(onBare.has(`${API}/core/ai.py`)).toBe(false)
    expect(onBare.has(`${API}/core/knowledge.py`)).toBe(false)
  })

  it('answers the download through the gate and nothing else: no deny-list, no incoming-key special case', () => {
    const router = text(on, `${API}/routers/files.py`)
    expect(router).toContain('require_releasable')
    expect(router).toContain('session, tenant.id, file_id, actor_id=claims.sub, consumer="download"')
    expect(router).not.toMatch(/withheld\(|import withheld|is_incoming_key|file_scan import|run_after_upload|for_upload/)
    // The list is the one place a hook is offered a file, and only a releasable one.
    expect(router).toContain('LAZY_HOOKS_PER_LIST = 3')
    expect(router).toContain('row_releasable(row, tenant.id, "listing")')
    expect(router).toContain('content_available: bool')
    expect(router).toContain('scan_status: str\n')
  })

  it('refuses a hook that wants the upload, and registers the assistant as an after-clean reader', () => {
    const hooks = text(on, `${API}/core/file_hooks.py`)
    expect(hooks).not.toMatch(/after_upload:|after_upload=|def for_upload|def run_after_upload/)
    expect(hooks).toContain('after_clean: Callable[..., Awaitable[int]] | None = None')
    expect(hooks).toContain('must say when it is due')
    const indexing = text(on, `${API}/core/file_indexing.py`)
    expect(indexing).toContain('after_clean=_index_once')
    expect(indexing).not.toContain('after_upload=')
  })

  it('reads a file for the assistant only through the gate, bound to the object that was read', () => {
    const ai = text(on, `${API}/core/ai.py`)
    expect(ai).toContain('from .file_release_gate import read_releasable')
    expect(ai).toContain('consumer="indexing"')
    expect(ai).toContain('knowledge_store.index_file_document')
    expect(ai).not.toMatch(/httpx|presign_download|async def index_uploaded_file|_index_uploaded_file/)
    expect(ai).toContain('_withhold_unreleasable_sources')
    const knowledge = text(on, `${API}/core/knowledge.py`)
    expect(knowledge).toContain('from .file_release import RELEASABLE_SQL')
    expect(knowledge).toContain('and {RELEASABLE_SQL}')
    expect(knowledge).toContain('for share of f')
    expect(knowledge).toContain('class ObjectChanged(FileNotReleasable)')
    expect(text(on, `${API}/ai/tools.py`)).toContain('row_releasable(row, ctx.context.tenant_id, "listing")')
  })

  it('parses an import source only through the rule, and carries the rule into the worker image', () => {
    const imports = text(on, `${API}/core/imports.py`)
    expect(imports).toContain('from .file_release import releasable')
    expect(imports).toContain('consumer="import"')
    expect(imports).not.toMatch(/UNPARSEABLE_SCANS/)
    expect(imports).toContain("nullif(current_setting('app.tenant_id', true), '') as session_tenant_id")
    const image = text(on, 'services/worker/Dockerfile')
    for (const file of ['file_release', 'secure_files']) {
      expect(image).toContain(`COPY services/api/koras_api/core/${file}.py`)
    }
    // Copied once: with data_import the import block already carries the audit sink and rebind.
    for (const file of ['audit', 'rebind']) {
      expect(image.match(new RegExp(`COPY services/api/koras_api/core/${file}\\.py`, 'g'))).toHaveLength(1)
    }
    // Without data_import nothing the worker reaches asks the rule, so the image does not carry it
    // (every COPY line has to be one something reaches), and the secure block carries the audit sink.
    expect(text(onBare, 'services/worker/Dockerfile')).not.toMatch(/file_release|core\/secure_files/)
    const bare = text(onBare, 'services/worker/Dockerfile')
    for (const file of ['audit', 'rebind']) {
      expect(bare.match(new RegExp(`COPY services/api/koras_api/core/${file}\\.py`, 'g'))).toHaveLength(1)
    }
  })

  it('the HTTP gate is API-only and the rule is not: the worker image never copies the gate', () => {
    expect(text(on, 'services/worker/Dockerfile')).not.toContain('file_release_gate')
    expect(text(on, 'services/worker/Dockerfile')).not.toContain('release_audit')
  })

  it('adds the withdrawal migration at the next number, with the semantics of Docoris 01019', () => {
    const migrations = [...on.keys()].filter((p) => p.startsWith('supabase/migrations/')).sort()
    expect(migrations.slice(-4)).toEqual([
      'supabase/migrations/00039_file_scan_attempts.sql',
      'supabase/migrations/00040_file_scan_interrupted.sql',
      'supabase/migrations/00041_file_scan_due_indexes.sql',
      'supabase/migrations/00042_file_derived_content_withdrawal.sql',
    ])
    const sql = text(on, 'supabase/migrations/00042_file_derived_content_withdrawal.sql')
    expect(sql).toContain('before update on public.files')
    expect(sql).toContain("old.status = 'ready' and old.scan_status = 'clean'")
    expect(sql).toContain('not (new.status = \'ready\' and new.scan_status = \'clean\')')
    expect(sql).toContain('before delete on public.files')
    expect(sql).toContain('security definer')
    expect(sql).toContain('set search_path = pg_catalog, public, pg_temp')
    // The table is the assistant's: skipped where there is none.
    expect(sql).toContain("if to_regclass('public.ai_knowledge_chunks') is not null then")
    expect(sql).not.toMatch(/alter table|create index|create policy/)
  })

  it('writes the one new audit action and the one new error code, and only here', () => {
    expect(text(on, `${API}/core/release_audit.py`)).toContain('storage.object.release_refused')
    expect(text(on, `${API}/core/errors.py`)).toContain('FILE_SCAN_PENDING = "file_scan_pending"')
  })

  it('shows the list as the server released it, and ends safe on a stale page', () => {
    const panel = text(on, 'apps/web/src/app/dashboard/files/FilesPanel.tsx')
    expect(panel).toContain("from '@sfrelon/api-client/src/file-state'")
    expect(panel).toContain('data-state={state}')
    expect(panel).toContain('disabled={state !== \'available\'}')
    expect(panel).toContain('RELEASE_REFUSALS.has(answer.code)')
    expect(panel).not.toContain('INDEXING_GRACE_MS')
    const actions = text(on, 'apps/web/src/app/dashboard/files/actions.ts')
    expect(actions).toContain("error.code === 'file_scan_pending' || error.code === 'file_quarantined'")
    expect(actions).toContain('code?: string')
  })
})

describe('the catalogue and the client', () => {
  it('declares the Files page sentences in every language, in every product', () => {
    for (const file of ['en', 'de', 'es']) {
      const catalogue = text(off, `packages/i18n/src/messages/${file}.ts`)
      for (const key of [
        'files.column.status',
        'files.status.available',
        'files.status.scanning',
        'files.status.unavailable',
        'files.notAvailable',
        'files.refresh',
      ]) {
        expect(catalogue, `${file}: ${key}`).toContain(`'${key}'`)
      }
    }
  })

  it('reads a listed file through a structural type, so the shared client is not touched', () => {
    const state = text(on, 'packages/api-client/src/file-state.ts')
    expect(state).toContain('export interface Releasable')
    expect(state).not.toContain("from '@")
    const client = text(off, 'packages/api-client/src/index.ts')
    expect(client).not.toContain('content_available')
  })
})

describe('the capability map names every file the layer adds', () => {
  const manifest = loadProfile('product').manifest
  const entry = manifest.template_map.capabilities.secure_files
  const gated = typeof entry === 'string' ? [entry] : (entry ?? [])

  it('lists the capability-only files and nothing the layer generates always', () => {
    for (const path of GATED) expect(gated, path).toContain(path)
    for (const path of ALWAYS) expect(gated, path).not.toContain(path)
  })
})
