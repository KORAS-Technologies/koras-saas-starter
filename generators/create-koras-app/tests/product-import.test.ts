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

/**
 * A bare `raise` statement at the start of an indented line.
 *
 * `\b` so that the word "raised" in a sentence is not one, and no `g` flag so
 * that `.test()` is stateless and two calls agree.
 */
const BARE_RAISE = /^\s+raise\b/m

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
  /* The commit writes everything or nothing                                */
  /* ---------------------------------------------------------------------- */

  /*
   * Phase 2, 2026-09-20. Three tests here used to assert the *absence* of a
   * commit -- no route, no task, no control -- which was the honest description
   * of Phase 1 and is now the opposite of the requirement. They are replaced
   * rather than deleted: what they were protecting, that nothing writes a row
   * of a target table by accident, is still protected, by the target's own
   * writer being the only thing that can.
   *
   * The acceptance criterion is one sentence -- a commit that raises on row 900
   * of 1000 leaves zero rows -- and it is a property of a transaction, which no
   * test that reads template text can see. What these assert is the shape that
   * makes it true, and each of them is a thing somebody could undo in a single
   * plausible edit.
   */

  it('does the writing in one transaction, and records the run inside it', () => {
    const task = read('services/worker/koras_worker/tasks/imports.py')
    const body = task.slice(task.indexOf('async def commit_run'), task.indexOf('async def _write'))
    // Three commits, and which is which matters more than the number: the
    // claim, the write, and the failure. The claim was missing until
    // 2026-09-22 and this assertion said 2 -- green over a commit path that
    // could not succeed once, for any product, because `record_commit` asks
    // for `committing -> committed` and nothing had moved the run into
    // `committing`. IMP2-01 in `docs/features/data-import/phase-2-review.md`.
    expect(body.match(/await session\.commit\(\)/g)?.length).toBe(3)
    expect(body).toContain('await store.record_commit(')
    // **The claim happens before anything is written, and the write and the
    // run's own committed row are still one transaction.** Ordering, because
    // the count above cannot tell a claim from a second write commit.
    expect(body.indexOf('await store.begin_commit(')).toBeGreaterThan(-1)
    expect(body.indexOf('await store.begin_commit(')).toBeLessThan(body.indexOf('_write('))
    expect(body.indexOf('_write(')).toBeLessThan(body.indexOf('await store.record_commit('))
    // The second is the failure path, and it must be a *separate* session --
    // a failure written inside the transaction that failed rolls back with it,
    // and the run sits in `committing` forever.
    expect(body.indexOf('await store.fail(')).toBeGreaterThan(
      body.indexOf('await store.record_commit('),
    )
    expect(body.match(/async_sessionmaker\(engine/g)?.length).toBe(2)
  })

  it('rolls back before it records a failure', () => {
    const task = read('services/worker/koras_worker/tasks/imports.py')
    const body = task.slice(task.indexOf('async def commit_run'), task.indexOf('async def _write'))
    // Every exception path rolls the writing transaction back. One that did
    // not would leave a poisoned session and, worse, a half-written unit of
    // work in doubt.
    const handlers = body.match(/except [^\n]*\n(\s+)await session\.rollback\(\)/g) ?? []
    expect(handlers.length).toBeGreaterThanOrEqual(4)
  })

  it('writes through the product-s own writer and knows no table itself', () => {
    // The rule CAT-02 states first: no product table name reaches the engine.
    const engine = read('python-packages/koras-import/src/koras_import/writing.py')
    expect(engine).not.toMatch(/insert into|update\s+public\.|delete from/i)
    const task = read('services/worker/koras_worker/tasks/imports.py')
    expect(task).toContain('await target.writer(session, request)')
    // And the worker writes nothing of its own.
    expect(task).not.toMatch(/insert into public\./)
  })

  it('accounts for every row a writer was given', () => {
    // A filter or an early `continue` that skips rows without counting them
    // would otherwise report a clean import of fewer records than the file
    // held, and nobody could say which were missing.
    const task = read('services/worker/koras_worker/tasks/imports.py')
    expect(task).toContain('check_total(request, written)')
    const engine = read('python-packages/koras-import/src/koras_import/writing.py')
    expect(engine).toContain('def check_total(')
    expect(engine).toContain('raise WriteRefused')
  })

  it('checks the file again rather than trusting the verdict it stored', () => {
    // Between the dry run and the commit a deploy may have changed the
    // target's own field specifications, and the run's stored counts would
    // still say it was clean.
    const task = read('services/worker/koras_worker/tasks/imports.py')
    expect(task).toContain('partial(store.prepare, raw, target, run, watch=budget.check)')
    expect(task).toContain('if not verdict.ok:')
    // Refused rather than written around. Writing only the good rows is the
    // partial commit the requirements forbid.
    const write = task.slice(task.indexOf('async def _write'))
    expect(write).toContain('raise WriteRefused')
  })

  it('reads the file and the mapping through one reader for both passes', () => {
    // A commit that parsed differently from the validation that approved it
    // would write rows nobody checked, and both would look like they had run.
    const store = read('services/api/koras_api/core/imports.py')
    expect(store).toContain('def _parse(')
    const examine = store.slice(store.indexOf('def examine('), store.indexOf('async def predict_outcome('))
    const check = store.slice(store.indexOf('def check('), store.indexOf('def prepare('))
    const prepare = store.slice(store.indexOf('def prepare('))
    // With or without the budget it is asked as it reads -- GR-352C gave the
    // dry run and the commit one, and `check` has none to give.
    for (const body of [examine, check, prepare]) {
      expect(body).toMatch(/_parse\(raw, target, run[,)]/)
    }
  })

  it('refuses a target that declares no writer, at every layer', () => {
    // Absent rather than disabled, all the way down. A disabled control
    // promises a thing this product cannot do, and a person cannot tell
    // "not yet" from "not for you".
    const targets = read('python-packages/koras-import/src/koras_import/targets.py')
    expect(targets).toContain('def committable(')
    const router = read('services/api/koras_api/routers/imports.py')
    expect(router).toContain('if not target.committable:')
    expect(router).toContain('IMPORT_NOT_COMMITTABLE')
    const task = read('services/worker/koras_worker/tasks/imports.py')
    expect(task).toContain('if not target.committable:')
    const panel = read('apps/web/src/app/dashboard/imports/ImportPanel.tsx.hbs')
    // The **run's** target, not the picker's: they diverge the moment somebody
    // changes the picker with a run in progress, and the control would then be
    // answering a question about a different import.
    expect(panel).toContain('runTarget?.committable === true')
    expect(panel).not.toContain('target?.committable === true')
  })

  it('never retries a commit on its own', () => {
    // A retry after a write that committed and then failed somewhere later
    // would write a customer's records twice, and nothing outside the
    // transaction can tell that case from a clean failure.
    const jobs = read('python-packages/koras-import/src/koras_import/jobs.py')
    const commit = jobs.slice(jobs.indexOf('COMMIT_RUN = TaskDefinition('))
    expect(commit).toContain('RetryPolicy(attempts=1)')
  })

  it('records who confirmed before it queues the work', () => {
    const router = read('services/api/koras_api/routers/imports.py')
    const body = router.slice(
      router.indexOf('async def commit('),
      router.indexOf('@router.get("/imports/{run_id}/errors"'),
    )
    // The other order has a window in which a worker reads a run still
    // `validated` and refuses its own job.
    expect(body.indexOf('store.request_commit(')).toBeLessThan(body.indexOf('jobs.enqueue('))
    expect(body).toContain('committed_by')
    expect(body).toContain('idempotency_key=f"commit:{run.id}"')
    // And an unconfigured queue fails the run rather than leaving somebody
    // watching a state that will never change.
    expect(body).toContain('queued.simulated')
    expect(body).toContain('IMPORT_QUEUE_UNAVAILABLE')
  })

  it('still writes nothing of its own to any product table', () => {
    // What the Phase 1 test protected, kept. The run store touches the two
    // import tables and nothing else; the product's writer is the only thing
    // in the path that may write a record.
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

  it('tells whoever confirmed it, through the one dispatch point', () => {
    // IMPORT-US-018, and the outbox's second producer. A second emitter is how
    // two notifications drift, and the drift is invisible until somebody
    // compares them side by side.
    const task = read('services/worker/koras_worker/tasks/imports.py')
    expect(task).toContain('koras_api.core.dispatch')
    expect(task).toContain('koras_api.core.import_notify')
    const body = task.slice(task.indexOf('async def _tell'), task.indexOf('#: Bound here'))
    // Swallows everything: a notification that cannot be raised must not turn
    // a finished import into a failed job, and a retried job writes the rows
    // again.
    expect(body).toContain('except Exception:')
    // The pattern is checked against a known-prohibited body and a known-good
    // one before it is trusted against the template. It carried a literal
    // backspace byte where `\b` was meant from 2026-09-20 until 2026-09-20 --
    // `/^\s+raise\x08/m` cannot match anything a Python file contains, so the
    // assertion below passed without ever reading the template. A pattern that
    // is only ever asked for a negative answer cannot tell "nothing prohibited
    // here" apart from "this regex matches nothing at all", which is why both
    // directions are asserted rather than the one the template needs.
    expect(BARE_RAISE.test('    try:\n        pass\n    except Exception:\n        raise\n')).toBe(
      true,
    )
    expect(BARE_RAISE.test('    # a notification that cannot be raised must not fail\n')).toBe(
      false,
    )
    expect(body, 'the notice can fail an import that already happened').not.toMatch(BARE_RAISE)
    // In-app only, and it is a property of the template rather than a flag.
    const notice = read('services/api/koras_api/core/import_notify.py')
    expect(notice).toContain('html=None')
    expect(notice).toContain('kinds.add(IMPORT_FINISHED)')
  })

  it('needs notifications, and says so rather than degrading', () => {
    const requires = manifest().requires as Record<string, string[]> | undefined
    expect(requires?.data_import).toContain('notifications')
  })

  it('carries the dispatch point into the worker image', () => {
    // Reached by `importlib`, so a missing file is a silent skip rather than a
    // crash -- which makes forgetting a COPY invisible without this.
    const dockerfile = readFileSync(
      join(PROFILE, '..', '_shared', 'template', 'services', 'worker', 'Dockerfile.hbs'),
      'utf8',
    )
    for (const file of [
      'core/import_notify.py',
      'core/dispatch.py',
      'core/notifications.py',
      'core/recipients.py',
      'core/settings_store.py',
      // The audit sink, since 2026-09-29: the worker witnesses a dry run and
      // a commit (ADR 0012 D5). Reached by `importlib` like the rest, so a
      // missing COPY would be evidence that silently never lands.
      'core/audit.py',
      // And what the sink calls after it commits. IMPORT-DEF-020: this was
      // inside `core/database.py`, which the image never carried.
      'core/rebind.py',
    ]) {
      expect(dockerfile).toContain(`koras_api/${file}`)
    }
    // And none of them may reach the API's own settings at import: a worker
    // that had to satisfy the API's whole environment to announce a finished
    // import is a worker with the API's configuration surface.
    const recipients = read('services/api/koras_api/core/recipients.py')
    expect(recipients).not.toMatch(/^from \. import platform$/m)
    expect(recipients).toContain('def _platform()')
    // The audit sink must not reach `.database` at all -- at the top of the
    // file or inside a function.
    //
    // **This asserted the opposite until 2026-10-02, and the assertion was the
    // defect.** `.database` builds `Settings()` at import, so the sink
    // imported it inside the function that rebinds, and this test held it to
    // exactly that line. In the worker's image there is no `.database`: the
    // import failed on the first flush, after the flush had committed, and
    // every dry run in a deployed worker was a failed job over a run already
    // `validated`. IMPORT-DEF-020. A shape was asserted and nothing asked
    // what the shape did -- found by running the image, and held now by
    // `tests/unit/test_worker_image_contents.py`, which walks the imports,
    // and `tests/integration/test_worker_image.py`, which runs it.
    const audit = read('services/api/koras_api/core/audit.py')
    expect(audit).not.toMatch(/^\s*from \.database import/m)
    expect(audit).toMatch(/^from \.rebind import rebind_tenant as rebind_tenant$/m)
    // And the module it does reach imports nothing of the API, which is what
    // lets the image carry it whole.
    const rebind = read('services/api/koras_api/core/rebind.py')
    expect(rebind).not.toMatch(/^\s*(from \.|from koras_api|import koras_api)/m)
    // Every caller in the API still finds it where it always was.
    expect(read('services/api/koras_api/core/database.py')).toContain(
      'from .rebind import rebind_tenant as rebind_tenant',
    )
    for (const path of ['tests/integration/test_worker_image.py', 'tests/integration/worker_image_probe.py']) {
      expect(gatedPaths('data_import')).toContain(path)
    }
    expect(has('tests/unit/test_worker_image_contents.py')).toBe(true)
  })

  /* ---------------------------------------------------------------------- */
  /* Templates and formats, 2026-09-29                                      */
  /* ---------------------------------------------------------------------- */

  it('renders a template from the declaration the validator reads, and nothing else', () => {
    // No second description of the schema: the renderer takes an
    // `ImportTarget` and reads `fields`. A module holding column lists of its
    // own would be the thing the brief forbids.
    const templates = read('python-packages/koras-import/src/koras_import/templates.py')
    expect(templates).toContain('def render(target: ImportTarget, fmt: Format) -> Rendered:')
    expect(templates).toContain('for spec in target.fields')
    expect(templates).not.toMatch(/AsyncSession|tenant_id|session:/)
    // JSON is in the vocabulary and refused by name (ADR 0012 D4).
    expect(templates).toContain('TEMPLATE_FORMATS: tuple[Format, ...] = (Format.CSV, Format.XLSX)')
  })

  it('serves the template behind the permission and records the download', () => {
    const router = read('services/api/koras_api/routers/imports.py')
    const route = router.slice(
      router.indexOf('@router.get("/imports/targets/{key}/template")'),
      router.indexOf('@router.get("/imports", response_model=list[RunView])'),
    )
    expect(route).toContain('_require(claims, "downloading an import template")')
    expect(route).toContain('_require_target(claims, target)')
    // Permission before the render, the audit row before the bytes.
    expect(route.indexOf('_require_target(')).toBeLessThan(route.indexOf('render(target, fmt)'))
    expect(route.indexOf('action="import.template.downloaded"')).toBeLessThan(
      route.indexOf('return Response('),
    )
    // And the web half is a route handler, the export handler's twin, gated
    // with the rest of the capability.
    expect(has('apps/web/src/app/api/imports/[key]/template/route.ts.hbs')).toBe(true)
    expect(gatedPaths('data_import')).toContain('apps/web/src/app/api/imports')
    const handler = read('apps/web/src/app/api/imports/[key]/template/route.ts.hbs')
    expect(handler).toContain("request.headers.get('sec-fetch-site')")
    expect(handler).toContain("can(signedIn.access, 'imports.manage')")
  })

  it('offers one template control, as a disclosure over plain anchors', () => {
    const panel = read('apps/web/src/app/dashboard/imports/ImportPanel.tsx.hbs')
    expect(panel).toContain('<DownloadMenu')
    expect(panel).toContain("href: `/api/imports/${encodeURIComponent(target?.key ?? '')}/template?format=${format}`")
    // Not a row of one button per format: the export menu's shape is not this
    // control's.
    expect(panel).not.toContain('ExportMenu')
    const menu = read('packages/ui/src/primitives/download-menu.tsx')
    expect(menu).toContain('aria-expanded={open}')
    expect(menu).toContain("event.key !== 'Escape'")
    expect(menu).not.toContain('role="menu"')
    expect(menu).toContain('<ButtonLink')
    expect(read('packages/ui/src/index.ts')).toContain(
      "export { DownloadMenu } from './primitives/download-menu'",
    )
  })

  it('registers the four audit moments and writes two of them from the worker', () => {
    const store = read('services/api/koras_api/core/imports.py')
    for (const key of [
      'import.template.downloaded',
      'import.run.validated',
      'import.run.finished',
    ]) {
      expect(store).toContain(`key="${key}"`)
    }
    const worker = read('services/worker/koras_worker/tasks/imports.py')
    expect(worker).toContain('action="import.run.validated"')
    expect(worker).toContain('action="import.run.finished"')
    // The commit's evidence is its own transaction, after the write and
    // before the notice, and swallows everything: a record that could roll
    // an import back is not a record.
    const commit = worker.slice(worker.indexOf('async def commit_run('), worker.indexOf('async def _record('))
    expect(commit.indexOf('await _witness(')).toBeLessThan(commit.indexOf('await _tell('))
    const witness = worker.slice(worker.indexOf('async def _witness('), worker.indexOf('async def _tell('))
    expect(witness).toContain('except Exception:')
    expect(BARE_RAISE.test(witness)).toBe(false)
    // Never a cell: counts, identifiers and the safe sentence.
    expect(witness).not.toMatch(/cells|rows\[/)
  })

  it('gates the migration that carries the figures, and the figures are nullable', () => {
    expect(gatedPaths('data_import')).toContain('supabase/migrations/00038_import_counts.sql')
    const migration = read('supabase/migrations/00038_import_counts.sql')
    for (const column of ['rows_created', 'rows_updated', 'rows_skipped', 'predicted_create']) {
      expect(migration).toMatch(new RegExp(`add column ${column}\\s+integer check`))
      expect(migration).not.toMatch(new RegExp(`add column ${column}\\s+integer not null`))
    }
    expect(migration).toContain('import_runs_written_counts_together')
  })

  it('reads a workbook by the CSV reader-s own header and row rules', () => {
    const xlsx = read('python-packages/koras-import/src/koras_import/reading_xlsx.py')
    expect(xlsx).toContain('header_from(cells)')
    expect(xlsx).toContain('row_from(number, cells, header)')
    expect(xlsx).toContain('read_only=True, data_only=True')
    // Bounded from the zip directory before any sheet is opened, and a
    // macro-bearing workbook refused there too.
    expect(xlsx.indexOf('DECOMPRESSED_CEILING')).toBeLessThan(xlsx.indexOf('load_workbook('))
    expect(xlsx).toContain('xl/vbaProject.bin')
  })

  it('runs the safety pass before either reader, on every path that parses', () => {
    // GR-352A. `openpyxl` builds a workbook's whole shared-string table on
    // load and the CSV path decodes the whole file into one string, so a
    // limit checked after either has already paid for what it refuses.
    //
    // This is the shape only: that the call is there and comes first. Whether
    // it *works* is asked of the code itself, by replacing both readers with
    // something that fails when reached -- `tests/unit/test_import_preflight.py`
    // in the product and `test_preflight.py` in the engine. A test that read
    // only this text would pass over a safety pass that refused nothing.
    const xlsx = read('python-packages/koras-import/src/koras_import/reading_xlsx.py')
    const pass = xlsx.indexOf('preflight(raw, Format.XLSX, limits)')
    expect(pass).toBeGreaterThan(-1)
    expect(pass).toBeLessThan(xlsx.indexOf('load_workbook('))

    // The store has no whole-file decode and no workbook read left to guard.
    //
    // Two of each until GR-352B, when the analysis stopped calling either
    // reader; one of each until GR-352C, when the dry run and the commit's
    // shared `_parse` stopped as well. What `_parse` opens instead is a stream,
    // once, and it is handed the envelope rather than taking a default.
    const store = read('services/api/koras_api/core/imports.py')
    const code = store.slice(store.indexOf('from __future__'))
    expect(code).not.toMatch(/[^a-z_.`]decode\(raw|[^`a-z_]read_workbook\(|load_workbook|splitlines/)
    const parse = store.slice(store.indexOf('def _parse('), store.indexOf('class Examined'))
    expect([...store.matchAll(/[^`]open_rows\(/g)]).toHaveLength(1)
    expect(parse).toMatch(/open_rows\(\s*raw,[\s\S]*?limits,[\s\S]*?limit=target\.max_rows/)
    expect(parse).toContain('limits = limits_for(target, rows=True)')

    // And the stream runs the safety pass itself, ahead of both of its
    // readers, so there is no way to it that goes around the pass.
    const streaming = read('python-packages/koras-import/src/koras_import/streaming.py')
    const entry = streaming.slice(streaming.indexOf('def open_rows('))
    const guard = entry.indexOf('checked = preflight(')
    expect(guard).toBeGreaterThan(-1)
    expect(guard).toBeLessThan(entry.indexOf('_workbook_rows(raw, checked'))
    expect(guard).toBeLessThan(entry.indexOf('_csv_rows(raw, checked'))
    const body = streaming.slice(streaming.indexOf('from __future__'))
    expect(body).not.toMatch(/load_workbook\(|read_workbook\(|[^a-z_.]decode\(raw/)

    // One envelope for the routes and the worker, and it says what it is.
    expect(store).toContain('SAFETY_LIMITS = SafetyLimits(max_source_bytes=MAX_SOURCE_BYTES)')
    const safety = read('python-packages/koras-import/src/koras_import/safety.py')
    for (const limit of ['MAX_DECODED_STRING_BYTES', 'MAX_CELLS', 'MAX_COLUMNS']) {
      // The comment block directly above the constant, and no other.
      const comment = safety.slice(0, safety.indexOf(`\n${limit} = `)).split('\n\n').pop() ?? ''
      expect(comment, `${limit} is not marked provisional`).toContain('#: PROVISIONAL (GR-352')
    }

    // The worker reaches a source only through the store, so it has no reader
    // of its own to guard.
    const worker = read('services/worker/koras_worker/tasks/imports.py')
    expect(worker).not.toMatch(/read_workbook|load_workbook|[^a-z_.]decode[(]/)

    expect(gatedPaths('data_import')).toContain('tests/unit/test_import_preflight.py')
    expect(has('python-packages/koras-import/tests/test_preflight_memory.py')).toBe(true)
  })

  it('scans the parts the reader reads, and reads only the sheet that was scanned', () => {
    // IMPORT-DEF-017. The safety pass found a workbook's parts by its own
    // rules and `openpyxl` finds them by others, so nine different packages
    // were called safe with their text and cells uncounted and then read in
    // full. Two halves, and each is worthless alone.
    //
    // The shape only. That every such package is refused *before* `openpyxl`
    // is reached, and that the parts the pass names are the ones `openpyxl`
    // goes on to use, is asked of the code and of the library --
    // `test_preflight_package.py` in the engine, which a generated product
    // runs.
    const safety = read('python-packages/koras-import/src/koras_import/safety.py')
    const survey = safety.slice(safety.indexOf('def _survey_xlsx('), safety.indexOf('def survey('))
    // The pass resolves the package, and scans what that names as what it is.
    expect(survey).toContain('package = _package(archive, names, limits.max_archive_entries)')
    expect(survey).toContain('force="worksheet"')
    expect(survey).toContain('force="sst" if named else None')
    // Not by a fixed name, and not by the prefix an attribute happens to use.
    const resolve = safety.slice(safety.indexOf('def _package('), safety.indexOf('def _survey_xlsx('))
    expect(resolve).toContain('map(part, _WORKBOOK_TYPES)')
    expect(resolve).toContain('entry.get(f"{_RELATIONSHIPS} id", entry.get("id", ""))')
    // A cell is a child of a row, whatever it is called.
    expect(safety).toContain('if self.kind == "worksheet" and (parent == "row" or local == "c"):')

    // The reader's half: the sheet it is about to read is the one the pass
    // scanned, checked before a row is asked for.
    const xlsx = read('python-packages/koras-import/src/koras_import/reading_xlsx.py')
    const check = xlsx.indexOf('!= checked.sheet_part')
    expect(check).toBeGreaterThan(xlsx.indexOf('load_workbook('))
    expect(check).toBeLessThan(xlsx.indexOf('sheet.iter_rows('))
    // And whatever a malformed sheet raises is a refusal, not a traceback.
    expect(xlsx).toMatch(/except Exception as broken:[^\n]*\n(?:\s*#[^\n]*\n)+\s*raise ReadRefused\(_UNREADABLE\) from broken/)

    // The inspection has no resolution of its own: it reads what the pass named.
    const inspection = read('python-packages/koras-import/src/koras_import/inspection.py')
    expect(inspection).toContain('checked.sheet_part, checked.sheet_title, checked.strings_part')
    expect(inspection).not.toMatch(/_WORKBOOK_RELS|\[Content_Types\]/)

    expect(has('python-packages/koras-import/tests/test_preflight_package.py')).toBe(true)
  })

  it('inspects a file-s head for the mapping page instead of parsing the file', () => {
    // GR-352B. The analysis and mapping routes used to hand the whole file to
    // the readers the dry run uses, inline on the event loop, to keep two
    // hundred rows of it.
    //
    // The shape only, again. That the inspection *agrees* with the readers,
    // holds none of what it does not show and leaves the loop free is asked
    // of the code -- `test_inspection.py` in the engine, and
    // `tests/unit/test_import_inspection.py` and its Linux memory twin in the
    // product, each of which Generator Integration runs on a generated
    // product. A test that read only this text would pass over an inspection
    // that returned the wrong rows.
    const store = read('services/api/koras_api/core/imports.py')
    const analyse = store.slice(store.indexOf('def analyse('), store.indexOf('async def analysed('))
    expect(analyse).toContain('inspect_source(')
    // Neither reader, and no whole-file decode, anywhere in the analysis.
    expect(analyse).not.toMatch(/read_workbook\(|[^a-z_.`]decode\(|load_workbook|splitlines/)
    // The envelope the routes were always given, and no row refusal from it:
    // the analysis answers `over_ceiling` and the mapping route refuses.
    expect(analyse).toContain('limits_for(target, rows=False)')

    // The routes await the thread wrapper and never call the synchronous one.
    expect(store).toContain('return await asyncio.to_thread(analyse, raw, target, fmt, sample=sample)')
    const router = read('services/api/koras_api/routers/imports.py')
    expect(router).not.toMatch(/store\.analyse\(/)
    expect([...router.matchAll(/await store\.analysed\(/g)]).toHaveLength(2)
    // The mapping route shows nobody a preview and asks for no rows.
    const mapping = router.slice(router.indexOf('async def set_mapping('))
    expect(mapping.slice(0, mapping.indexOf('await store.set_mapping('))).toContain('sample=0')

    // The inspection is in the engine, runs the safety pass itself before
    // anything else, and never opens a workbook through `openpyxl`.
    const inspection = read('python-packages/koras-import/src/koras_import/inspection.py')
    const entry = inspection.slice(inspection.indexOf('def inspect_source('))
    const pass = entry.indexOf('checked = preflight(raw, fmt, limits)')
    expect(pass).toBeGreaterThan(-1)
    expect(pass).toBeLessThan(entry.indexOf('_inspect_xlsx('))
    expect(pass).toBeLessThan(entry.indexOf('_inspect_csv('))
    const code = inspection.slice(inspection.indexOf('from __future__'))
    expect(code).not.toMatch(/load_workbook|read_workbook|[^a-z_.]decode\(raw/)
    // The sample's own budget says what it is.
    const comment =
      inspection.slice(0, inspection.indexOf('\nMAX_SAMPLE_CHARACTERS = ')).split('\n\n').pop() ?? ''
    expect(comment).toContain('#: PROVISIONAL (GR-352')

    // The worker has no inspection of its own: it reads every row, through
    // the store's `_parse`, as a stream since GR-352C.
    const worker = read('services/worker/koras_worker/tasks/imports.py')
    expect(worker).not.toMatch(/inspect_source|analysed?\(/)

    for (const path of [
      'tests/unit/test_import_inspection.py',
      'tests/unit/test_import_inspection_memory.py',
    ]) {
      expect(gatedPaths('data_import')).toContain(path)
    }
    expect(has('python-packages/koras-import/tests/test_inspection.py')).toBe(true)
  })

  it('hands the writer canonical values whatever the source', () => {
    // IMP2-19, closed: `prepare` normalises rather than stripping.
    const store = read('services/api/koras_api/core/imports.py')
    const prepare = store.slice(store.indexOf('def prepare('))
    expect(prepare).toContain('normalise = normaliser(target, resolved)')
    expect(prepare).toContain('mapped.append(normalise(row))')
    expect(store).not.toContain('row.cells.get(column, "").strip() for field, column in resolved.fields.items()')
  })

  it('reads one import at a time, off the event loop, under a budget it can be stopped at', () => {
    // GR-352C. Four things, and this is their shape only -- each is a line
    // somebody could remove in one plausible edit and leave every other
    // assertion in this file green.
    //
    // Whether any of them *works* is asked of the product's own task by
    // `tests/unit/test_import_worker_envelope.py`, where each has a second
    // test showing the first can fail; of the kernel by
    // `tests/unit/test_import_worker_memory.py`; and of a real database by
    // `tests/integration/test_import_commit_atomic.py`, which counts rows.
    const worker = read('services/worker/koras_worker/tasks/imports.py')

    // One slot, held by both handlers from before the source is fetched.
    // Since GR-352E it is the worker's heavy gate, with the import's own
    // limit passed to the same acquisition -- one gate taken once, and no
    // second semaphore before or after it for an order to go wrong between.
    const held = 'async with heavy(IMPORT, limit=IMPORT_SLOTS):'
    expect(worker.split(held)).toHaveLength(3)
    for (const name of ['validate_run', 'commit_run']) {
      const handler = worker.slice(worker.indexOf(`async def ${name}(`))
      expect(handler.indexOf(held)).toBeGreaterThan(-1)
      expect(handler.indexOf(held)).toBeLessThan(handler.indexOf(`return await _${name}(`))
    }
    expect(worker).not.toContain('asyncio.Semaphore')
    for (const limit of ['IMPORT_SLOTS', 'WORK_BUDGET_SECONDS']) {
      const comment = worker.slice(0, worker.indexOf(`\n${limit} = `)).split('\n\n').pop() ?? ''
      expect(comment, `${limit} is not marked provisional`).toContain('#: PROVISIONAL (GR-352C')
    }
    expect(worker).toContain('IMPORT_SLOTS = 1\n')

    // The reading is on a thread, and neither store function is called inline.
    expect(worker).toMatch(/await _off_loop\(\s*budget,\s*partial\(store\.examine, raw, target, run, watch=budget\.check\)/)
    expect(worker).toMatch(/await _off_loop\(\s*budget,\s*partial\(store\.prepare, raw, target, run, watch=budget\.check\)/)
    expect(worker).not.toMatch(/=\s*store\.(examine|prepare)\(/)

    // A cancellation is passed on to the thread, and the run is told.
    const offLoop = worker.slice(worker.indexOf('async def _off_loop'), worker.indexOf('_AS_TENANT = '))
    expect(offLoop.indexOf('except asyncio.CancelledError:')).toBeLessThan(offLoop.indexOf('budget.cancel()'))
    expect([...worker.matchAll(/except asyncio\.CancelledError:[\s\S]{0,400}?await _abandon\(envelope\)\n\s+raise/g)]).toHaveLength(2)
    // And so is a job that raised: its run must not go on saying it is being
    // checked, or being written.
    expect([...worker.matchAll(/except Exception:[\s\S]{0,500}?await _abandon\(envelope, _BROKE\)\n\s+raise/g)]).toHaveLength(2)
    // And that telling can never overwrite a commit that landed.
    const store = read('services/api/koras_api/core/imports.py')
    const abandon = store.slice(store.indexOf('async def abandon('), store.indexOf('async def record_validation('))
    expect(abandon).toContain('and status = :was')

    // The writer's rows are not held twice.
    expect(worker).toContain('rows_from(mapped, ceiling=target.max_rows, owned=True)')

    // The API holds a bounded number of sources at once, on both routes.
    const slot = store.slice(0, store.indexOf('\nANALYSIS_SLOTS = ')).split('\n\n').pop() ?? ''
    expect(slot).toContain('#: PROVISIONAL (GR-352C')
    const router = read('services/api/koras_api/routers/imports.py')
    expect([...router.matchAll(/async with store\.analysis_slot\(\):/g)]).toHaveLength(2)
    for (const route of ['async def analysis(', 'async def set_mapping(']) {
      const body = router.slice(router.indexOf(route))
      expect(body.indexOf('async with store.analysis_slot():')).toBeLessThan(
        body.indexOf('await _bytes(session, storage, run)'),
      )
    }

    for (const path of [
      'tests/unit/test_import_worker_envelope.py',
      'tests/unit/test_import_worker_memory.py',
      'tests/integration/test_import_commit_atomic.py',
    ]) {
      expect(gatedPaths('data_import')).toContain(path)
    }
    for (const path of ['test_streaming.py', 'test_equivalence.py']) {
      expect(has(`python-packages/koras-import/tests/${path}`)).toBe(true)
    }
  })

  it('holds every job that carries a payload behind one gate', () => {
    // GR-352E. The shape only, as above -- each is a line somebody could
    // remove in one plausible edit. Whether two jobs are in fact kept apart
    // is asked of the jobs themselves by
    // `tests/unit/test_worker_heavy_sections.py`, where every pair has a
    // second test showing the first can fail, and of the gate by
    // `tests/unit/test_worker_heavy_gate.py`.
    const gate = read('services/worker/koras_worker/heavy.py')
    expect(gate).toContain('HEAVY_SLOTS = 1\n')
    const comment = gate.slice(0, gate.indexOf('\nHEAVY_SLOTS = ')).split('\n\n').pop() ?? ''
    expect(comment, 'HEAVY_SLOTS is not marked provisional').toContain('#: PROVISIONAL (GR-352E')
    // Not a job slot: the worker still has ten.
    expect(read('services/worker/koras_worker/worker.py.hbs')).toContain('max_jobs = 10\n')

    // A backup: every copy goes through the gated one, and the gate is taken
    // before `copy_one` reads anything.
    const backup = read('services/worker/koras_worker/tasks/storage_backup.py')
    const run = backup.slice(backup.indexOf('async def back_up_tenant_objects('))
    expect(run).toContain('outcome = await _copy_gated(')
    expect(run).not.toMatch(/=\s*copy_one\(/)
    const gated = backup.slice(backup.indexOf('async def _copy_gated('), backup.indexOf('def backup_key_for('))
    expect(gated).toMatch(/async with heavy\(BACKUP\):\n\s+return copy_one\(/)

    // A restore: the gate, then the claim, then the read.
    const restore = read('services/worker/koras_worker/tasks/storage_restore.py')
    const approved = restore.slice(restore.indexOf('async def restore_approved('))
    const inGate = approved.indexOf('async with heavy(RESTORE):')
    expect(inGate).toBeGreaterThan(-1)
    expect(inGate).toBeLessThan(approved.indexOf('session.execute(_CLAIM'))
    expect(approved.indexOf('session.execute(_CLAIM')).toBeLessThan(approved.indexOf('await run_one('))

    // A scheduled report: the gate before the query, the count before the
    // file, and the bound is the framework's own.
    const report = read('services/worker/koras_worker/tasks/reporting.py')
    const deliver = report.slice(report.indexOf('async def deliver_one('), report.indexOf('async def deliver_due('))
    const order = [
      'async with heavy(REPORT):',
      'await definition.resolver(context, filters)',
      'if rows > SCHEDULED_DELIVERY_ROW_LIMIT:',
      'raise ReportTooLarge(rows)',
      'render(result, fmt, title=definition.name)',
      'await sender.send(',
    ].map((line) => deliver.indexOf(line))
    expect(order.every((at) => at > -1), `${order}`).toBe(true)
    expect([...order].sort((a, b) => a - b)).toEqual(order)
    // Derived from the framework's number under a name of its own, and the
    // framework's number is not rebound here.
    expect(report).toContain('\nSCHEDULED_DELIVERY_ROW_LIMIT = EXPORT_ROW_LIMIT\n')
    expect(report).not.toMatch(/(^|\n)EXPORT_ROW_LIMIT\s*=/)
    expect(report).not.toContain('10_000')
    expect(gatedPaths('reporting')).toContain('tests/unit/test_reporting_delivery_bound.py')

    for (const path of ['test_worker_heavy_gate.py', 'test_worker_heavy_sections.py']) {
      expect(has(`tests/unit/${path}`)).toBe(true)
    }
  })

  it('is run by name on the row that has every heavy job, and in the image on the row with a database', () => {
    // A job a product was generated without is skipped inside
    // `test_worker_heavy_sections.py`, and the image test skips without an
    // image -- both right for a product, and both a silent pass in the step
    // that runs everything. So the workflow names them and fails on a skip.
    const workflow = readFileSync(
      join(PROFILE, '..', '..', '.github', 'workflows', 'generator-integration.yml'),
      'utf8',
    )
      .split(String.fromCharCode(13))
      .join('')
    const step = (name: string): string => {
      const at = workflow.indexOf(`- name: ${name}`)
      expect(at, `no step named ${name}`).toBeGreaterThan(-1)
      const rest = workflow.slice(at + 1)
      const next = rest.search(/\n {6}- name: /)
      return next === -1 ? rest : rest.slice(0, next)
    }

    const gate = step('The heavy-job gate and the report bound ran, and nothing skipped')
    for (const suite of [
      'tests/unit/test_worker_heavy_gate.py',
      'tests/unit/test_worker_heavy_sections.py',
      'tests/unit/test_reporting_delivery_bound.py',
      'tests/unit/test_worker_image_contents.py',
    ]) {
      expect(gate).toContain(suite)
    }
    expect(gate).toContain("if: contains(matrix.components, 'data_import')")
    expect(gate).toMatch(/skipped'[^\n]*; then\n\s+echo "::error::[^\n]*\n\s+exit 1/)

    const image = step('The worker image was built, ran an import, and did not skip')
    expect(image).toContain("if: matrix.roundtrip && contains(matrix.components, 'data_import')")
    // Built from the generated Dockerfile, at the generated project's root.
    expect(image).toContain('docker build -f services/worker/Dockerfile -t "$WORKER_IMAGE" .')
    expect(image).toContain('tests/integration/test_worker_image.py')
    expect(image).toMatch(/skipped'[^\n]*; then\n\s+echo "::error::[^\n]*\n\s+exit 1/)
    // Nothing of the tree is mounted into either container: the test passes
    // no volume, and neither does the step.
    expect(image).not.toMatch(/\s-v\s|--volume|--mount/)
    const test = read('tests/integration/test_worker_image.py')
    expect(test).not.toMatch(/"-v"|"--volume"|"--mount"/)
    // And the row that names `data_import` owns a round trip, or the image
    // step would never run.
    expect(workflow).toMatch(
      /components: "--with [^"]*data_import[^"]*"\n(\s+#[^\n]*\n)*\s+roundtrip: true/,
    )
  })

  it('translates the rejection a matcher can produce', () => {
    const labels = read('apps/web/src/app/dashboard/imports/labels.ts.hbs')
    expect(labels).toContain("'import.error.already_exists': t('imports.problem.alreadyExists')")
    for (const locale of readdirSync(join(PRODUCT, 'packages', 'i18n', 'src', 'messages'))) {
      expect(read('packages', 'i18n', 'src', 'messages', locale)).toContain("'imports.problem.alreadyExists':")
    }
  })

  it('lets a person take every bad row away in a file', () => {
    // A person fixing a file works in a spreadsheet, not in a table on a web
    // page, and `listErrors` answers a page rather than the report.
    const actions = read('apps/web/src/app/dashboard/imports/actions.ts.hbs')
    expect(actions).toContain('export async function allErrors(')
    const panel = read('apps/web/src/app/dashboard/imports/ImportPanel.tsx.hbs')
    expect(panel).toContain('labels.downloadReport')
    expect(panel).toContain('text/csv;charset=utf-8')
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

  it('polls exactly the states only a worker can move a run out of', () => {
    /*
     * IMP2-06. `commit_requested` was missing, and the commit route answers
     * with the run in precisely that state -- so confirming an import ended
     * the polling it was meant to start. The card froze on the request
     * sentence while the worker wrote the rows.
     *
     * Derived from the state machine rather than restated: the set the page
     * polls must be the set of states a *person* cannot move, which is the
     * only reason to ask again. A count would not have caught this; the old
     * set had two entries and two was not obviously wrong.
     */
    const panel = read('apps/web/src/app/dashboard/imports/ImportPanel.tsx.hbs')
    const declared = panel.match(/const IN_FLIGHT = new Set\(\[([^\]]*)\]\)/)
    expect(declared, 'IN_FLIGHT is not declared as a literal set').not.toBeNull()
    const polled = [...(declared?.[1] ?? '').matchAll(/'([a-z_]+)'/g)].map((m) => m[1])

    expect(new Set(polled)).toEqual(
      new Set(['validating', 'commit_requested', 'committing']),
    )

    const states = read('python-packages/koras-import/src/koras_import/states.py')
    // Every polled state exists, so a rename on one side fails here rather
    // than becoming a page that polls a state nothing ever reports.
    for (const state of polled) {
      expect(states, `${state} is not a state`).toContain(`= "${state}"`)
    }
    // And no terminal state is polled: that is a request every three seconds,
    // for a run that will never change again, until the tab is closed.
    for (const terminal of ['committed', 'failed', 'cancelled']) {
      expect(polled, `${terminal} is terminal and must not be polled`).not.toContain(
        terminal,
      )
    }
  })

  it('neutralises a cell a spreadsheet would execute, on the way out', () => {
    /*
     * IMP2-08. The error report is the one file this product hands back whose
     * every value was chosen by whoever made the upload -- and a cell that
     * failed its check is the one most likely to be hostile. It was quoted and
     * nothing else: quoting defends the *delimiter*, and Excel strips the
     * quotes before deciding whether the cell is a formula.
     *
     * The rule: a cell whose first character is `=`, `+`, `-`, `@`, a tab or a
     * carriage return is prefixed with an apostrophe, which is the documented
     * way to tell a spreadsheet "this is text". Tab and carriage return are in
     * the set because some importers carry them into the next cell along with
     * whatever follows.
     *
     * The one thing it changes that is not an attack is a negative number,
     * which gains an apostrophe. Excel does not display that apostrophe, and a
     * report is read rather than re-imported, so the cost is accepted.
     */
    const panel = read('apps/web/src/app/dashboard/imports/ImportPanel.tsx.hbs')
    expect(panel).toContain('function guardCell(')
    // Every trigger character, named. A guard that covered `=` alone would
    // read as present and let `+`, `-` and `@` through.
    const rule = panel.match(/function guardCell[\s\S]{0,200}?\/\^\[([^\]]+)\]/)
    expect(rule, 'guardCell does not test a leading-character class').not.toBeNull()
    const cls = rule?.[1] ?? ''
    for (const ch of ['=', '+', '-', '@', 't', 'r']) {
      expect(cls, `guardCell does not cover ${ch}`).toContain(ch)
    }
    // And it is actually applied where the file is built, not merely defined.
    expect(panel).toContain('guardCell(cell)')
  })

  it('pages the report on the key the route pages on, and bounds the loop', () => {
    // IMP2-05. The route pages on `import_row_errors.id`; the browser sent the
    // file's row number, a different scale entirely, so the "every problem"
    // file truncated on a young database and repeated pages on an old one.
    // The route did not return the key at all, so there was no correct value
    // to send.
    const actions = read('apps/web/src/app/dashboard/imports/actions.ts.hbs')
    expect(actions).toContain('after = last.cursor')
    expect(actions, 'the loop pages on the file row number again').not.toMatch(
      /after = last\.row/,
    )
    // The bound the docstring claimed and the code did not apply.
    expect(actions).toContain('collected.length >= ceiling')

    // And the key is actually answered, in the store, the view and the client.
    expect(read('services/api/koras_api/core/imports.py')).toContain('cursor=row.id')
    expect(read('services/api/koras_api/routers/imports.py')).toContain('cursor: int')
    expect(read('packages/api-client/src/index.ts')).toContain('cursor: number')
  })

  it('reads the duplicate answer from the queue rather than only the simulated one', () => {
    /*
     * IMP2-09. `Enqueued` has carried `duplicate` since it was written and no
     * caller in either template read it. The queue refuses a deterministic job
     * id while the previous result still lives -- an hour by default -- so
     * re-checking a re-mapped file, which is the ordinary flow after a failed
     * dry run, enqueued nothing while the route answered 202 and moved the run
     * to `validating`. It waited there for a job that was never created.
     */
    const router = read('services/api/koras_api/routers/imports.py')
    expect((router.match(/queued\.duplicate/g) ?? []).length).toBe(2)
    // `validate` carries no key at all now: re-checking is legitimate, and the
    // state machine is what refuses a second check of a run already running.
    const validate = router.slice(
      router.indexOf('async def validate('),
      router.indexOf('async def commit('),
    )
    expect(validate, 'validate must not re-key on the run').not.toContain(
      'idempotency_key=f"validate:',
    )
    // `commit` keeps its key: `committed` and `failed` are both terminal, so a
    // duplicate there is a race rather than a second attempt.
    expect(router).toContain('idempotency_key=f"commit:')
  })

  it('announces the commit through the shared outcome rather than a bare paragraph', () => {
    // IMP2-10, which is SET-24 in a second feature. The confirm button unmounts
    // on success, so focus falls to BODY, and the sentence that replaces it
    // mounts inside a new subtree -- which a live region does not announce.
    const panel = read('apps/web/src/app/dashboard/imports/ImportPanel.tsx.hbs')
    expect(panel).toContain('SaveOutcome')
    expect(panel).toContain('testId="imports-committed"')
    // Not reimplemented beside it: the component is the fix, and a second copy
    // is how the first one stops being maintained.
    expect(panel, 'the outcome is still a bare paragraph').not.toMatch(
      /<p[^>]*data-testid="imports-committed"/,
    )
  })

  it('lets a person open a past run, so the report survives a reload', () => {
    /*
     * IMP2-29. `run` starts `null` on every load and `refresh` keeps a null
     * null, so the result card -- which is where *Download every problem*
     * lives -- rendered only for a run the page was already working on. The
     * history listed every run and was four cells with no control. A customer
     * who reloaded could not reach their own report; the route answered and
     * the page had no way in.
     *
     * **This assertion is the only automated protection the control has.** The
     * panel cannot be exercised in a browser by this repository's own CI: a
     * generated product declares no import targets, so `ImportPanel` returns
     * the no-targets banner before it renders anything. Verified instead in a
     * browser against a product given a target by hand, recorded in
     * `docs/features/data-import/testing/manual/manual-test-results.md`.
     */
    const panel = read('apps/web/src/app/dashboard/imports/ImportPanel.tsx.hbs')
    const history = panel.slice(panel.indexOf('{runs.map((row) => ('))
    expect(history).toContain('data-testid="imports-open"')
    expect(history, 'the history row has no control that selects its run').toMatch(
      /onClick=\{\(\) => open\(row\)\}/,
    )
    // Opening clears what belonged to whichever run was open before. A report
    // from one run shown under another is worse than no report at all.
    const opener = panel.slice(panel.indexOf('const open = useCallback'))
    expect(opener.slice(0, 400)).toContain('setAnalysis(null)')
    expect(opener.slice(0, 400)).toContain('setProblems(null)')
    // Each button says which run it opens. Twenty rows of "Open" is twenty
    // identical accessible names.
    expect(history).toContain('aria-label={fill(labels.openRun,')
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
    const files = read('services/api/koras_api/routers/files.py.hbs')
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
    const files = read('services/api/koras_api/routers/files.py.hbs')
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
    const errors = read('services/api/koras_api/core/errors.py.hbs')
    const codes = [...errors.matchAll(/^\s+IMPORT_\w+ = "([a-z_]+)"$/gm)].map((match) => match[1]!)
    // Ten since the commit: `import_not_committable` is what a target with
    // no writer answers, and it is a sentence rather than a 500 because a
    // person confirming an import they cannot make should be told why.
    // Eleven since the templates: `import_format_refused` is a 406 for a
    // template in a format the target does not accept, and a 422 for a
    // source file in one.
    expect(codes.length).toBe(11)

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

  it('checks a target-s own permission on every route that could leak one', () => {
    /*
     * IMP-06 put this on the three routes that resolved a target. IMP2-03 found
     * the hole that left: three more routes did not *resolve* a target at all,
     * so they skipped the check by never arriving at it -- and one of them,
     * `GET /imports/{id}/errors`, answers `problem.value`, which is the cell
     * itself out of a file the target was meant to gate.
     *
     * **The assertion this replaces could not fail.** It pinned the count at
     * four and then compared `_target(` matches against `_require_target(`
     * matches -- a regex that matches the substring inside every occurrence of
     * the thing it was being compared to, so the second expectation was
     * `n >= n`. Asserted per route now, by name, because a count says nothing
     * about *which* routes are covered.
     */
    const router = read('services/api/koras_api/routers/imports.py')

    // Every route that names a single run, plus the one that starts one. Each
    // either returns something derived from that run's file or acts on it.
    const perRun = [
      { path: "/imports/{run_id}", fn: 'async def one(' },
      { path: "/imports/{run_id}/analysis", fn: 'async def analysis(' },
      { path: "/imports/{run_id}/mapping", fn: 'async def set_mapping(' },
      { path: "/imports/{run_id}/validate", fn: 'async def validate(' },
      { path: "/imports/{run_id}/commit", fn: 'async def commit(' },
      { path: "/imports/{run_id}/errors", fn: 'async def errors(' },
      { path: "/imports/{run_id}/cancel", fn: 'async def cancel(' },
      { path: '/imports', fn: 'async def start(' },
    ]
    for (const route of perRun) {
      const at = router.indexOf(route.fn)
      expect(at, `${route.fn} is missing`).toBeGreaterThan(-1)
      // The body, up to whatever is defined next.
      const nextDef = router.indexOf('\nasync def ', at + 1)
      const body = router.slice(at, nextDef === -1 ? undefined : nextDef)
      expect(
        body,
        `${route.path} does not check the target's own permission`,
      ).toContain('_require_target(claims,')
    }

    // The two list routes cannot 403 -- a caller entitled to import something
    // is entitled to the page -- so they filter instead. Asserted separately
    // because "no _require_target" is the correct shape for exactly these two.
    for (const fn of ['async def targets(', 'async def history(']) {
      const at = router.indexOf(fn)
      const nextDef = router.indexOf('\nasync def ', at + 1)
      const body = router.slice(at, nextDef === -1 ? undefined : nextDef)
      expect(body, `${fn} must filter by the caller's permissions`).toContain('held')
    }

    expect(router).toContain('target.permission not in permissions_for(claims.roles)')
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

describe('import start fields stay level', () => {
  /**
   * The shared field frame draws a hint between the label and the control, so
   * a hint on one of two side-by-side fields pushed its control down. The
   * Existing records hint is drawn below its control instead, which is opt-in
   * (`hintPlacement`, default `above`) so no other form moves.
   */
  it('the field primitive offers hintPlacement and defaults to the long-standing shape', () => {
    const field = read('packages/ui/src/primitives/field.tsx')
    expect(field).toContain("export type HintPlacement = 'above' | 'below'")
    expect(field).toContain("hintPlacement = 'above'")
    // Either placement keeps the control described by the hint.
    expect(field).toContain('aria-describedby={describedBy(id, error, hint)}')
  })

  it('the import panel draws the Existing records hint below its control, in a top-aligned grid', () => {
    const panel = read('apps/web/src/app/dashboard/imports/ImportPanel.tsx.hbs')
    expect(panel).toMatch(/hint=\{labels\.operationHint\}\s+hintPlacement="below"/)
    expect(panel).toContain('grid items-start gap-4 sm:grid-cols-2')
    expect(panel).toContain('data-testid="imports-start-fields"')
  })
})
