import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { tmpdir } from 'node:os'
import { existsSync, readFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import yaml from 'js-yaml'
import { templatePath } from './template-path'
import { loadProfile } from '../src/profiles/index.js'
import {
  resolveSelections,
  applyComponentOverrides,
  validateSelections,
} from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'
import { writeFiles } from '../src/generation/writer.js'

/**
 * The two governance capabilities, checked from the template text.
 *
 * The property worth a suite of its own is not what they gate — it is what
 * they deliberately do **not**. `audit_events` sat inside the `reporting` gate
 * until 2026-09-16, which meant a product generated without analytics recorded
 * nothing at all and nobody noticed, because an empty audit table and an
 * absent one look identical from every screen a person opens.
 *
 * So the rule these two follow, asserted below: a table is gated only when no
 * foundation code and no foundation migration reaches it. Everything else —
 * the routes, the pages, the sweeps — may be gated freely, because their
 * absence is visible the moment somebody looks for the route.
 */

const PRODUCT = join(templatePath('product', 'package.json.hbs'), '..')
const PROFILE = join(PRODUCT, '..')

function read(...segments: string[]): string {
  return readFileSync(join(PRODUCT, ...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

function has(...segments: string[]): boolean {
  return existsSync(join(PRODUCT, ...segments))
}

type Manifest = {
  capabilities: Record<string, unknown>
  template_map: { capabilities: Record<string, string[]> }
}
type Defaults = { capabilities: Record<string, boolean> }

const manifest = yaml.load(
  readFileSync(join(PROFILE, 'manifest.yaml'), 'utf8'),
) as Manifest
const defaults = yaml.load(readFileSync(join(PROFILE, 'defaults.yaml'), 'utf8')) as Defaults

const GATED = {
  audit_governance: manifest.template_map.capabilities.audit_governance ?? [],
  storage_governance: manifest.template_map.capabilities.storage_governance ?? [],
}

const OUT = join(tmpdir(), `koras-governance-${process.pid}-${Date.now()}`)

afterAll(() => {
  if (existsSync(OUT)) rmSync(OUT, { recursive: true, force: true })
})

/** A real product on disk, which is the only thing that cannot be argued with. */
async function generate(slug: string, overrides: { with?: string[]; without?: string[] } = {}) {
  const profile = loadProfile('product')
  const selections = resolveSelections(profile.manifest, profile.defaults)
  applyComponentOverrides(profile.manifest, selections, overrides)
  validateSelections(profile.manifest, selections)
  const ctx = buildContext({
    projectName: slug,
    projectSlug: slug,
    profile: 'product',
    manifest: profile.manifest,
    defaults: profile.defaults,
    selections,
    outputDir: OUT,
    dryRun: false,
    provision: false,
  })
  const { fileList } = await writeFiles(ctx, renderTemplate(ctx))
  return {
    fileList,
    has: (path: string) => fileList.some((f) => f === path || f.startsWith(`${path}/`)),
    read: (path: string) => readFileSync(join(OUT, slug, path), 'utf8'),
  }
}

// ── declared at all ───────────────────────────────────────────────────────────

describe('both capabilities are declared where a capability has to be', () => {
  it.each(['audit_governance', 'storage_governance'])('%s is a known component', (name) => {
    // Three places, and a capability missing from any one of them fails
    // differently: absent from `capabilities` and `--without` is refused as an
    // unknown component; absent from `defaults` and it is off for everybody;
    // absent from `template_map` and it gates nothing at all while appearing
    // to work.
    expect(manifest.capabilities).toHaveProperty(name)
    expect(defaults.capabilities).toHaveProperty(name)
    expect(GATED[name as keyof typeof GATED].length).toBeGreaterThan(0)
  })

  it.each(['audit_governance', 'storage_governance'])('%s is on by default', (name) => {
    // Neither needs an external service, a second credential or a bill. The
    // sweeps that do cost something are each off behind their own setting, so
    // the capability decides whether the code is there and the setting decides
    // whether it runs.
    expect(defaults.capabilities[name]).toBe(true)
  })

  it('every gated path exists in the template tree', () => {
    const missing = [...GATED.audit_governance, ...GATED.storage_governance].filter(
      (path) => !has(...path.split('/')) && !has(...`${path}.hbs`.split('/')),
    )
    expect(missing, 'a gated path that does not exist gates nothing').toEqual([])
  })
})

// ── what is deliberately not gated ────────────────────────────────────────────

describe('the record is foundation, and only the surface is gated', () => {
  const everything = [...GATED.audit_governance, ...GATED.storage_governance]

  it.each([
    ['00019_audit_classification.sql', 'the audit sweep reads the class it adds'],
    ['00020_legal_holds.sql', 'three foundation callers ask under_legal_hold'],
    ['00021_files_retention.sql', 'the policies sit on files, which is foundation'],
    ['00022_audit_exports.sql', 'platform_governance counts it and 00024 reads it'],
    ['00023_retention_overrides.sql', 'the audit sweep resolves through it'],
    ['00024_governance_sweeps.sql', 'reconciliation calls claimed_storage_keys'],
  ])('%s stays in the foundation — %s', (migration) => {
    expect(everything).not.toContain(`supabase/migrations/${migration}`)
  })

  it('00025_file_backups.sql is the one governance migration that is gated', () => {
    // And it can be, because nothing outside `storage_backup.py` reads
    // `file_backups`. The columns the sweeps act on live on `files` from
    // 00018, which is foundation.
    expect(GATED.storage_governance).toContain('supabase/migrations/00025_file_backups.sql')
  })

  it.each([
    'services/api/koras_api/core/audit.py',
    'services/api/koras_api/routers/platform_governance.py',
    'services/api/koras_api/routers/files.py',
    'services/worker/koras_worker/tasks/audit_retention.py',
  ])('%s stays in the foundation', (path) => {
    expect(everything).not.toContain(path)
  })

  it('the file index still carries governance state without either capability', () => {
    // A column that records what is true, with no sweep pretending to
    // maintain it, is the honest shape. A column that disappears with a
    // capability would make the history of an object depend on how the
    // product was generated.
    const migration = read('supabase', 'migrations', '00018_files_governance.sql')
    for (const column of ['retain_until', 'legal_hold', 'backup_status', 'checksum_sha256']) {
      expect(migration).toContain(column)
    }
    expect(everything).not.toContain('supabase/migrations/00018_files_governance.sql')
  })
})

// ── the wiring, proved by generating rather than by reading Handlebars ────────
//
// The first version of this section read `main.py.hbs` and asserted that the
// gate was in the text. It passed with the gate deleted, because a template
// full of gates contains that string whatever the audit block does -- which is
// the same class of defect this repository has spent two days finding. So:
// generate the product and ask it what it has.

describe('a product generated without either capability', () => {
  let bare: Awaited<ReturnType<typeof generate>>
  let full: Awaited<ReturnType<typeof generate>>

  beforeAll(async () => {
    bare = await generate('governance-off', {
      without: ['audit_governance', 'storage_governance'],
    })
    full = await generate('governance-on')
  }, 120_000)

  it('registers no audit, export or hold route', () => {
    const main = bare.read('services/api/koras_api/main.py')
    for (const router of ['audit_exports.router', 'audit.router', 'holds.router']) {
      expect(main, `${router} survived --without audit_governance`).not.toContain(router)
    }
    // And the import list with it, or ruff fails the product rather than us.
    expect(main).not.toMatch(/^\s+audit,$/m)
    expect(main).not.toMatch(/^\s+holds,$/m)
  })

  it('still answers the platform governance contract', () => {
    // The collector asks every product what it holds. One that answered 404
    // because of how it was generated would read as a product storing nothing.
    expect(bare.read('services/api/koras_api/main.py')).toContain('platform_governance.router')
    expect(bare.has('services/api/koras_api/routers/platform_governance.py')).toBe(true)
  })

  it('schedules no sweep that either capability ships', () => {
    const worker = bare.read('services/worker/koras_worker/worker.py')
    for (const task of [
      'expire_audit_exports',
      'expire_legal_holds',
      'reconcile_storage',
      'sweep_storage_lifecycle',
      'back_up_storage',
    ]) {
      expect(worker, `${task} survived`).not.toContain(task)
    }
  })

  it('still forgets audit rows on a schedule', () => {
    // Foundation, like the table it sweeps. A product that records for ever
    // is a product whose retention policy is a document.
    expect(bare.read('services/worker/koras_worker/worker.py')).toContain('purge_audit_history')
  })

  it('keeps every governance migration but the backup catalogue', () => {
    for (const n of ['00019', '00020', '00021', '00022', '00023', '00024']) {
      const [path] = bare.fileList.filter((f) => f.startsWith(`supabase/migrations/${n}`))
      expect(path, `migration ${n} was gated away`).toBeDefined()
    }
    expect(bare.has('supabase/migrations/00025_file_backups.sql')).toBe(false)
    expect(full.has('supabase/migrations/00025_file_backups.sql')).toBe(true)
  })

  it('shows no Audit module in the navigation registry', () => {
    const branding = bare.read('packages/branding/src/index.ts')
    expect(branding).not.toContain("href: '/dashboard/audit'")
    expect(full.read('packages/branding/src/index.ts')).toContain("href: '/dashboard/audit'")
  })

  it('carries no test that would fail at import', () => {
    // Every capability added to this repository has leaked at least once, and
    // the leak has always been a test file nobody remembered to gate.
    for (const name of [
      'test_storage_backup.py',
      'test_storage_lifecycle.py',
      'test_storage_reconcile.py',
      'test_legal_holds.py',
      'test_governance_review.py',
      'test_governance_sweeps_review.py',
    ]) {
      expect(bare.has(`tests/unit/${name}`), `${name} leaked`).toBe(false)
    }
  })
})
