import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import yaml from 'js-yaml'
import { templatePath } from './template-path'

/**
 * Data import, checked from the template text.
 *
 * CAT-02 Phase 1, shipped 2026-09-19: upload a file, say which column is
 * which, and see what would happen — with nothing written. The commit is Phase
 * 2 and is deliberately absent rather than disabled.
 *
 * The properties worth a structural test here are the ones that fail quietly,
 * and the first is the reason the feature exists at all.
 *
 * **Nothing in Phase 1 writes a row of a target table.** The state machine has
 * no edge out of `validating` that writes, no route commits, and the panel
 * carries no control that could. A commit route added later without its own
 * confirmation would sail past every other test in this repository.
 *
 * **The capability gates a real set of files, and every gated path exists.** A
 * path in the map that the template does not have is a capability that
 * silently excludes nothing — which is the state `notifications` was in for
 * its whole life before 2026-09-19.
 *
 * **It is off by default.** Unlike reporting and the governance pair, an
 * import target is something a product declares; a product that declares none
 * gets a page listing nothing, so the default is off and a product opts in.
 *
 * **The shared layers stay out of the gate.** `packages/i18n`, `packages/ui`
 * and `packages/api-client` are generated always, and a product without the
 * capability carries unused strings and unused client functions rather than a
 * build that does not resolve.
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
  capabilities: Record<string, boolean>
  requires?: Record<string, string[]>
  template_map: { capabilities: Record<string, string | string[]> }
}

function manifest(): Manifest {
  return yaml.load(readFileSync(join(PROFILE, 'manifest.yaml'), 'utf8')) as Manifest
}

function gatedPaths(capability: string): string[] {
  const entry = manifest().template_map.capabilities[capability]
  if (entry === undefined) return []
  return typeof entry === 'string' ? [entry] : entry
}

describe('data import', () => {
  it('gates a real set of files rather than nothing at all', () => {
    const paths = gatedPaths('data_import')
    expect(paths.length).toBeGreaterThan(0)

    // What a product loses without it: the engine, the registry, the store,
    // the routes, the job, the tables, their isolation suite, the unit tests,
    // the page and the browser test.
    for (const expected of [
      'python-packages/koras-import',
      'services/api/koras_api/imports',
      'services/api/koras_api/core/imports.py',
      'services/api/koras_api/routers/imports.py',
      'services/worker/koras_worker/tasks/imports.py',
      'supabase/migrations/00036_imports.sql',
      'supabase/tests/320_imports_isolation.sql',
      'tests/unit/test_imports.py',
      'apps/web/src/app/dashboard/imports',
      'e2e/imports.spec.ts',
    ]) {
      expect(paths).toContain(expected)
    }
  })

  it('gates nothing that is not there', () => {
    for (const path of gatedPaths('data_import')) {
      const direct = has(path)
      const templated = has(`${path}.hbs`)
      expect(direct || templated, `${path} is gated but not in the template`).toBe(true)
    }
  })

  it('is declared, and off by default', () => {
    const defaults = yaml.load(readFileSync(join(PROFILE, 'defaults.yaml'), 'utf8')) as {
      capabilities: Record<string, boolean>
    }

    expect(manifest().capabilities.data_import).toBe(true)
    // Off: a product with no declared targets would get a page listing
    // nothing, and a table nothing writes to.
    expect(defaults.capabilities.data_import).toBe(false)
  })

  it('keeps the shared layers out of the gate', () => {
    for (const path of gatedPaths('data_import')) {
      expect(path).not.toContain('packages/ui')
      expect(path).not.toContain('packages/i18n')
      expect(path).not.toContain('packages/api-client')
      expect(path).not.toContain('settings_catalogue')
    }
  })

  /* ---------------------------------------------------------------------- */
  /* Nothing in Phase 1 writes a row                                        */
  /* ---------------------------------------------------------------------- */

  it('has no route that commits, anywhere in the router', () => {
    const router = read('services/api/koras_api/routers/imports.py')
    expect(router).not.toContain('/commit')
    expect(router).not.toMatch(/def\s+commit/)
    // `COMMIT_RUN` is declared in the engine so the enqueue name is settled;
    // the router must not be enqueueing it yet.
    expect(router).not.toContain('COMMIT_RUN')
  })

  it('has no worker task that commits', () => {
    const task = read('services/worker/koras_worker/tasks/imports.py')
    expect(task).toContain('validate_run')
    expect(task).not.toMatch(/async def commit_run/)
  })

  it('offers no control that could write, on the page', () => {
    const panel = read('apps/web/src/app/dashboard/imports/ImportPanel.tsx.hbs')
    expect(panel).not.toMatch(/labels\.commit\b/)
    expect(panel).not.toContain('commitRun')
    // Discarding and checking are the only two verbs it has.
    expect(panel).toContain('void check()')
    expect(panel).toContain('void stop()')
  })

  it('records the dry run and moves the run, touching no other table', () => {
    const store = read('services/api/koras_api/core/imports.py')
    const statements = [...store.matchAll(/(insert into|update|delete from)\s+public\.(\w+)/g)].map(
      (match) => match[2]!,
    )
    expect(statements.length).toBeGreaterThan(0)
    for (const table of statements) {
      expect(['import_runs', 'import_row_errors'], `${table} is written by the store`).toContain(
        table,
      )
    }
  })

  /* ---------------------------------------------------------------------- */
  /* The queue, the source file, the permission                             */
  /* ---------------------------------------------------------------------- */

  it('refuses a dry run rather than promising one nothing will do', () => {
    const router = read('services/api/koras_api/routers/imports.py')
    // `Enqueued.simulated` is what an unconfigured queue answers. A 202 in that
    // case would leave a person watching a spinner for work nobody scheduled.
    expect(router).toContain('queued.simulated')
    expect(router).toContain('IMPORT_QUEUE_UNAVAILABLE')
    // And the check happens before the run is moved.
    expect(router.indexOf('queued.simulated')).toBeLessThan(
      router.indexOf('store.begin_validation'),
    )
  })

  it('will not parse a file nobody has scanned', () => {
    const store = read('services/api/koras_api/core/imports.py')
    // Stricter than a download on purpose: `core/file_scan.py` withholds
    // `infected` alone, because a person opening their own file is making
    // their own judgement. An import is the product parsing it unattended.
    expect(store).toContain('UNPARSEABLE_SCANS')
    for (const state of ['"pending"', '"skipped"', '"infected"']) {
      expect(store).toContain(state)
    }
    const scan = read('services/api/koras_api/core/file_scan.py')
    expect(scan, 'a download still allows a pending file').not.toContain('UNPARSEABLE_SCANS')
  })

  it('checks the permission every route, reads included, and the target as well', () => {
    const router = read('services/api/koras_api/routers/imports.py')
    const routes = [...router.matchAll(/@router\.(get|post|put|delete)\(/g)]
    expect(routes.length).toBeGreaterThanOrEqual(8)
    // One `_require` call per route. A read route without one would expose a
    // customer's own column headings to any member.
    const checks = [...router.matchAll(/^\s+_require\(claims, /gm)]
    expect(checks.length).toBe(routes.length)

    // And a target's own declared permission is enforced rather than decorative.
    expect(router).toContain('_require_target(claims, target)')
    expect(router).toContain('target.permission not in permissions_for(claims.roles)')
  })

  it('names the permission in both catalogues', () => {
    expect(read('packages/permissions/src/index.ts')).toContain("'imports.manage'")
    expect(read('python-packages/koras-auth/src/koras_auth/permissions.py')).toContain(
      '"imports.manage"',
    )
  })

  /* ---------------------------------------------------------------------- */
  /* The source file is an ordinary upload                                  */
  /* ---------------------------------------------------------------------- */

  it('uploads through the files route, on its own shelf', () => {
    // The source inherits retention, legal hold, reconciliation, scanning and
    // the quota because it is an ordinary file. What the category buys is that
    // the two are separable later — by a sweep, a rule or a report.
    const files = read('services/api/koras_api/routers/files.py')
    expect(files).toContain("category: Literal[\"documents\", \"imports\"] = \"documents\"")

    // The category is decided by the server action, never accepted from the
    // browser: a caller cannot ask for a document ticket and then feed it to a
    // run, nor the other way about.
    const actions = read('apps/web/src/app/dashboard/imports/actions.ts.hbs')
    expect(actions).toContain("category: 'imports'")
    expect(actions).not.toMatch(/category:\s*input\./)
  })

  it('checks the organisation-s own upload limits at the ticket', () => {
    const storage = read('services/api/koras_api/core/storage.py')
    expect(storage).toContain('files.maxUploadSizeMb')
    expect(storage).toContain('files.allowedExtensions')
    const files = read('services/api/koras_api/routers/files.py')
    expect(files).toContain('upload_limits')
    expect(files).toContain('UPLOAD_REFUSED_BY_POLICY')
  })

  /* ---------------------------------------------------------------------- */
  /* The registry, the navigation and the strings                           */
  /* ---------------------------------------------------------------------- */

  it('ships a registry with an empty extension point beside it', () => {
    // The sixth instance of the pattern: a starter-owned registry and a
    // product-owned list that starts empty, exactly as reports, audit actions,
    // settings, file hooks and the assistant's tools do.
    expect(has('services/api/koras_api/imports/__init__.py')).toBe(true)
    const targets = read('services/api/koras_api/imports/targets.py')
    expect(targets).toContain('TARGETS: list[ImportTarget] = []')
  })

  it('registers one module, gated on the permission and the capability', () => {
    const branding = read('packages/branding/src/index.ts.hbs')
    expect(branding).toContain("id: 'imports'")
    expect(branding).toContain("href: '/dashboard/imports'")
    expect(branding).toContain("requiredPermissions: ['imports.manage']")
    expect(branding).toContain("requiredCapabilities: ['data_import']")
    // No plan gate: a customer who cannot get their data in has not bought a
    // product. The same position Restore takes, from a different direction.
    const entry = branding.slice(branding.indexOf("id: 'imports'"))
    expect(entry.slice(0, entry.indexOf('},'))).not.toContain('requiredEntitlements')

    // The href resolves to a real route, and the module is inside the gate.
    expect(has('apps/web/src/app/dashboard/imports/page.tsx.hbs')).toBe(true)
    expect(branding).toContain('{{#if capability.data_import}}')
  })

  it('says the same thing in every language it offers', () => {
    const catalogues = readdirSync(join(PRODUCT, 'packages', 'i18n', 'src', 'messages'))
    const keys = (locale: string) =>
      new Set(
        [...read('packages', 'i18n', 'src', 'messages', locale).matchAll(/^\s+'([\w.]+)':/gm)]
          .map((match) => match[1]!)
          .filter((key) => key.startsWith('imports.') || key.startsWith('errors.import')),
      )
    const english = keys('en.ts')
    expect(english.size).toBeGreaterThan(50)
    for (const locale of catalogues) {
      expect([...keys(locale)].sort(), `${locale} is not level with English`).toEqual(
        [...english].sort(),
      )
    }
  })

  it('gives every import error code a sentence and a mapping', () => {
    const errors = read('services/api/koras_api/core/errors.py')
    const codes = [...errors.matchAll(/^\s+IMPORT_\w+ = "([a-z_]+)"$/gm)].map((match) => match[1]!)
    // Nine since the review: `import_file_too_large` is IMP-02's answer.
    expect(codes.length).toBe(9)

    const mapping = read('apps/web/src/lib/api-errors.ts.hbs')
    const english = read('packages/i18n/src/messages/en.ts')
    for (const code of codes) {
      expect(mapping, `api-errors.ts does not map "${code}"`).toContain(`case '${code}':`)
      const key = 'errors.' + code.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase())
      expect(english, `no sentence for "${code}"`).toContain(`'${key}':`)
    }
  })

  /* ---------------------------------------------------------------------- */
  /* The tables                                                             */
  /* ---------------------------------------------------------------------- */

  /* ---------------------------------------------------------------------- */
  /* What the review found                                                  */
  /* ---------------------------------------------------------------------- */

  it('lets retention reach an import source rather than making it immortal', () => {
    // IMP-01, and the worst defect this feature shipped with. `on delete
    // restrict` was the only foreign key onto `public.files` in the schema, and
    // the retention sweep -- which had never met a refusal -- marked the row
    // purged, deleted the bytes, then raised on the row delete and aborted. It
    // aborted again every night after, so no customer file was ever purged.
    const migration = read('supabase/migrations/00036_imports.sql')
    expect(migration).toContain('references public.files(id) on delete set null')
    expect(migration).not.toContain('on delete restrict')
    // Nullable, because that is what `set null` needs and what the store reads.
    expect(migration).not.toMatch(/source_file_id\s+uuid\s+not null/)
  })

  it('keeps the sweep running when a row will not delete', () => {
    // The other half, and the one that fixes the *class*: the next foreign key
    // onto `files` must not be able to stop retention either.
    const sweep = read('services/worker/koras_worker/tasks/storage_lifecycle.py')
    expect(sweep).toContain('async def _forget(')
    expect(sweep).toContain('await session.rollback()')
    // No unguarded delete left: every caller goes through the helper.
    const direct = [...sweep.matchAll(/await session\.execute\(_DELETE_ROW/g)]
    expect(direct.length, '_DELETE_ROW is executed outside _forget').toBe(1)
  })

  it('bounds the source it reads into memory with a number, not a hope', () => {
    // IMP-02. `source_bytes` selected `size_bytes` and never read it, while its
    // docstring claimed the read was bounded by an upload ceiling whose default
    // is five thousand megabytes.
    const store = read('services/api/koras_api/core/imports.py')
    expect(store).toContain('MAX_SOURCE_BYTES')
    expect(store).toContain('import.source.too_large')
    // Checked before the object is fetched, not after.
    expect(store.indexOf('import.source.too_large')).toBeLessThan(store.indexOf('store.get('))
    // And at the start of a run, so nobody maps forty columns first.
    const router = read('services/api/koras_api/routers/imports.py')
    expect(router).toContain('store.check_source(session, body.file_id)')
  })

  it('never decides an ambiguous number for the customer', () => {
    // IMP-04. `float(value.replace(",", "."))` read `1,234` as 1.234 -- wrong
    // by a factor of a thousand, silently. The same rule this module already
    // applies to `%m/%d/%Y`.
    //
    // Asserted on the branch rather than on the file's text: the replacement
    // quotes the old expression in its own docstring to explain what it fixed,
    // and a substring search cannot tell a fix from the account of one.
    const mapping = read('python-packages/koras-import/src/koras_import/mapping.py')
    expect(mapping).toContain('import.error.ambiguous_decimal')
    const branch = mapping.slice(mapping.indexOf('spec.kind is FieldKind.DECIMAL'))
    expect(branch.slice(0, 120)).toContain('_check_decimal(value)')
  })

  it('can actually report that no strict encoding fitted', () => {
    // IMP-03. `latin-1` maps all 256 byte values, so with it in `ENCODINGS` the
    // loop always returned before its own fallback: `replaced` was structurally
    // always False and the page's banner could never appear.
    const reading = read('python-packages/koras-import/src/koras_import/reading.py')
    expect(reading).toContain('ENCODINGS: tuple[str, ...] = ("utf-8-sig", "cp1252")')
    expect(reading).toContain('FALLBACK_ENCODING = "latin-1"')
  })

  it('checks a target-s own permission on every route that resolves one', () => {
    // IMP-06. It was on `start` alone, and `analysis` answers a preview of the
    // customer's rows.
    const router = read('services/api/koras_api/routers/imports.py')
    const resolves = [...router.matchAll(/_target\(/g)].length
    const checks = [...router.matchAll(/_require_target\(claims, target\)/g)].length
    expect(checks, 'a route resolves a target without checking its permission').toBe(3)
    expect(resolves).toBeGreaterThanOrEqual(checks)
  })

  it('answers a state conflict on validate with 409, before enqueueing', () => {
    // IMP-05. It enqueued, then advanced, then let TransitionRefused escape as
    // a 500 -- having already queued a job against a run the machine refused.
    const router = read('services/api/koras_api/routers/imports.py')
    const check = router.indexOf('may_move(run.state, RunState.VALIDATING)')
    const enqueue = router.indexOf('await jobs.enqueue(')
    expect(check).toBeGreaterThan(-1)
    expect(check, 'the transition is checked after the enqueue').toBeLessThan(enqueue)
    expect(router).toContain('HTTP_409_CONFLICT')
  })

  it('forces row-level security on both tables and gives updates a check', () => {
    const migration = read('supabase/migrations/00036_imports.sql')
    for (const table of ['import_runs', 'import_row_errors']) {
      expect(migration).toContain(`alter table public.${table} enable row level security`)
      expect(migration).toContain(`alter table public.${table} force row level security`)
    }
    // An UPDATE policy without WITH CHECK lets a row be moved to another
    // tenant by the update itself.
    const updates = [...migration.matchAll(/for update[\s\S]*?;/g)].map((match) => match[0])
    expect(updates.length).toBeGreaterThan(0)
    for (const policy of updates) {
      expect(policy, 'an update policy with no with check').toContain('with check')
    }
  })

  it('will not let a committed run forget who committed it', () => {
    const migration = read('supabase/migrations/00036_imports.sql')
    expect(migration).toContain('import_runs_committed_has_an_actor')
  })

  it('is exercised by an isolation suite', () => {
    const suite = read('supabase/tests/320_imports_isolation.sql')
    expect(suite).toContain('import_runs')
    expect(suite).toContain('import_row_errors')
    // The case that a SELECT-only suite misses: moving a row to another tenant.
    expect(suite.toLowerCase()).toContain('update')
  })
})
