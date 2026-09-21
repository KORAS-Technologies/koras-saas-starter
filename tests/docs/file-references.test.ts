import { describe, it, expect } from 'vitest'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { documents } from './documents.js'

/**
 * A path named in a document has to exist, or be exempt for a stated reason
 * that is itself checked.
 *
 * The documents here carry an unusual share of the repository's reasoning: why
 * a thing is absent, which file holds a guard, where a credential is read. That
 * is deliberate, and it has a failure mode nothing else here has — prose is the
 * only part of this repository that can be wrong without anything going red.
 *
 * Three defects in one session came from that. A comment said ZITADEL teardown
 * "needs a service-account JWT exchange"; it had never been true, and no test
 * could have said so, because an absence has no behaviour to assert. The
 * runbook said DATABASE_ADMIN_URL was deliberately kept out of
 * `secrets.manifest` — a decision, wrong, and invisible. An audit called
 * ZITADEL_SERVICE_TOKEN an orphan because no template declared it, when the
 * missing thing was the declaration.
 *
 * A false claim about *why* still cannot be checked mechanically. A false claim
 * about *where* can, and it is the commonest kind: files move, and the document
 * that named them does not move with them.
 *
 * Deliberately narrow, so it stays worth having: only backticked tokens shaped
 * like a path with an extension — up to seven characters, because a five-limit
 * silently exempted `environments/dev.tfvars`, a file this repository has never
 * had and a document described for months; globs and `<placeholders>` skipped, since they
 * name a shape rather than a file; other repositories skipped, since this one
 * cannot see them; matched by suffix, because a document reasonably writes
 * `src/terraform/inputs.ts` for a file two package directories down.
 */

const ROOT = join(__dirname, '..', '..')

/**
 * Paths this repository does not have, named on purpose.
 *
 * Every one is asserted *absent* below. An exemption is a claim too, and a
 * document that says a file was never created is wrong the moment somebody
 * creates it — which is precisely the kind of quiet staleness this file exists
 * to catch, so it would be poor to introduce a blind spot in the escape hatch.
 */
const ABSENT_ON_PURPOSE: Record<string, string> = {
  '.koras/project.yaml': 'written by create-koras-app; the factory is not a generated project',
  'local/.env': 'written by local/scripts/ports.sh, per machine',
  'docs/AGENT_CONTEXT.md':
    'a generated project writes its own; the generator never creates or touches it',
  'local/mail/mailpit.yml': 'IMPLEMENTATION_ROADMAP records it as a deviation: never created',
  'local/storage/minio.yml': 'IMPLEMENTATION_ROADMAP records it as a deviation: never created',
  'local/certs/README.md': 'IMPLEMENTATION_ROADMAP records it as absent; generate.sh explains itself',
  'environments/dev.tfvars': 'named in ENVIRONMENT_STRATEGY and R-042 to say it has never existed',
  'terraform.tfvars.json': 'named in INFRASTRUCTURE_PLAN and R-042 to say it has never existed',
  // Not absent on purpose in the design; named on purpose in the document. The
  // control-plane profile ships a Playwright helper that reads this file and
  // the template does not contain it, which is the whole of SYNC_BACKLOG B6.
  // The exemption goes when B6 does, and this test will say so.
  'e2e/support/key.json': 'SYNC_BACKLOG B6 names it to record that the template lacks it',

  // ── Written by a generated product, never by the factory ─────────────────
  //
  // Same class as `.koras/project.yaml` above: the adoption guide says "if the
  // product created one", and the factory ships the example it is created from.
  '.claude/orchestration/product-profile.yaml':
    'a product creates it from product-profile.example.yaml; the factory has only the example',

  // ── Deliberately not built, and named to say so ──────────────────────────
  'templates/feature/execution-plan.md':
    'v2-to-v2-1 lists it under "What was deliberately not built": the execution plan is an output contract, not a per-feature document',

  // ── Another repository's paths ───────────────────────────────────────────
  //
  // `docs/features/PROFILE_SYNC_MATRIX.md` and the settings-framework audit and
  // sync matrix are cross-repository documents by design -- the first says so in
  // its own opening line -- so they name paths in `koras-control-plane` and in
  // `docoris`. Those must stay absent *here*: this repository holding one would
  // mean a boundary had moved, which is the same reason CLAUDE.md gives for not
  // naming another repository's schema.
  'apps/admin/src/lib/navigation.ts': 'koras-control-plane: its console navigation',
  'apps/admin/src/components/ui/DataTable.tsx': 'koras-control-plane: its console table',
  'packages/ui/src/sidebar-frame.tsx': 'koras-control-plane: its console shell',
  'billing/prices.py': 'koras-control-plane: its commercial catalogue',
  'koras_platform/ai.py': 'koras-control-plane: its platform package',
  'koras_platform/plans.py': 'koras-control-plane: its platform package',
  'python-packages/koras-platform/src/koras_platform/plans.py': 'koras-control-plane: the same file, fully qualified',
  'services/worker/koras_worker/product_settings.py': 'koras-control-plane: its worker',
  'supabase/migrations/00006_commercial.sql': 'koras-control-plane: its migration series, which is not this one',
  'supabase/migrations/00045_product_settings.sql': 'koras-control-plane: its migration series, which is not this one',
  'tests/contract/reference_product.py': 'koras-control-plane: its contract suite',
  'tests/contract/test_product_platform_contract.py': 'koras-control-plane: its contract suite',
  'tests/unit/test_migration_numbering.py': 'koras-control-plane: its unit suite',
  'docoris/docs/architecture/IMPORT.md': 'docoris: quoted by the platform plan as the product-side record',
  'docoris/docs/requirements/GAP-REGISTER.md': 'docoris: the register this one adopts three rows from',

  // ── Named by a plan as work not done ─────────────────────────────────────
  //
  // The settings framework's implementation plan lists the suites it would add.
  // Absent is the correct state while the plan is unexecuted, and the moment
  // somebody creates one this test says the plan needs a past tense.
  'koras-settings/tests/test_scopes.py': 'settings-framework implementation plan: a suite it proposed',
  'tests/rls/test_rls_coverage.py': 'settings-framework implementation plan: a suite it proposed',
  'tests/unit/test_settings_audit.py': 'settings-framework implementation plan: a suite it proposed',
  'tests/unit/test_settings_rbac.py': 'settings-framework implementation plan: a suite it proposed',
}

/**
 * Paths that were right when written and have since moved.
 *
 * Kept rather than rewritten. These appear in dated accounts of what was true
 * at the time — an R-036 entry describing a teardown that could not delete —
 * and editing the path would quietly falsify the record. Both halves are
 * checked: the old path must really be gone, and the replacement must really
 * exist, so this map cannot rot into a list of names nobody has looked at.
 */
const MOVED: Record<string, string> = {
  // Named by G7 R2's telemetry events 14 and 16, which are append-only and may
  // not be edited. One file was written for the first failed `pnpm test` of that
  // run and then reused as the name for the second, so a single path stood for
  // two different runs and the first run's output had not been retained at all.
  // `qa-reviewer` found it (F1); the fix retained both runs under names that say
  // which is which, and an amendment records the correction. The events keep the
  // name they were written with, which is what this map is for.
  'docs/features/G7R2-F01-honour-high-contrast/testing/runs/2026-09-21-04/pnpm-test-attempt-1-summary.txt':
    'docs/features/G7R2-F01-honour-high-contrast/testing/runs/2026-09-21-04/pnpm-test-attempt-2-crlf.txt',
  'testing/runs/2026-09-21-04/pnpm-test-attempt-1-summary.txt':
    'docs/features/G7R2-F01-honour-high-contrast/testing/runs/2026-09-21-04/pnpm-test-attempt-2-crlf.txt',
  'helpers/teardown.ts': 'tooling/koras-cli/src/teardown/guards.ts',
  'tests/e2e/helpers/teardown.ts': 'tooling/koras-cli/src/teardown/guards.ts',
  // Named by FOLLOW_UPS F3a, which records that `koras-control-plane`'s
  // reference product claimed to mirror the router at this path after it had
  // moved. Quoting the wrong path is the finding; rewriting it here would erase
  // what the entry is about.
  'services/api/src/routers/platform.py':
    'profiles/product/template/services/api/koras_api/routers/platform.py',
  // Named by FOLLOW_UPS F20, in the dated account of what phase 1 cost: the
  // marketing homepage stopped being a cached static document because the
  // language came from a cookie, and the comment saying so lived at this
  // path. Phase 2 moved the page under a `[locale]` segment on 2026-09-15 --
  // which is the repair that entry named -- so the comment is at the new
  // path and the sentence about 2026-09-05 keeps the old one.
  'apps/marketing/src/app/page.tsx':
    'profiles/product/template/apps/marketing/src/app/[locale]/page.tsx.hbs',
  // Named by PRODUCT_FRONTEND and by FOLLOW_UPS F20, both in dated accounts of
  // the language work: `member_preferences` held one row per person per tenant
  // and that suite asserted a colleague could not read it. The settings
  // framework took the table's job on 2026-09-17 -- migration `00031` moves
  // the rows into `member_setting_values` and drops it -- and the suite moved
  // with it, keyed the same way and failing closed in the same place.
  //
  // Recorded rather than rewritten: both passages describe what was true when
  // they were written, and editing the path would falsify that.
  'supabase/tests/160_member_preferences_isolation.sql':
    'profiles/product/template/supabase/tests/280_member_setting_values_isolation.sql',
}

function tracked(): string[] {
  return execFileSync('git', ['ls-files'], { cwd: ROOT, encoding: 'utf8' })
    .split('\n')
    .filter(Boolean)
}

/** Every suffix of every tracked path, with `.hbs` also stripped. */
/** Every file extension some tracked file actually uses. */
let EXTENSIONS: Set<string> | undefined
function extensions(): Set<string> {
  if (!EXTENSIONS) {
    EXTENSIONS = new Set<string>()
    for (const file of tracked()) {
      const found = /\.([a-zA-Z0-9]{1,7})$/.exec(file)?.[1]
      if (found) EXTENSIONS.add(found.toLowerCase())
    }
  }
  return EXTENSIONS
}

function suffixes(): Set<string> {
  const all = new Set<string>()
  for (const file of tracked()) {
    for (const path of [file, file.endsWith('.hbs') ? file.slice(0, -4) : file]) {
      const parts = path.split('/')
      for (let i = 0; i < parts.length; i++) all.add(parts.slice(i).join('/'))
    }
  }
  return all
}


function referencedPaths(doc: string): string[] {
  const text = readFileSync(join(ROOT, doc), 'utf8')
  const found = new Set<string>()
  for (const match of text.matchAll(/`([^`\n]+)`/g)) {
    const token = (match[1] as string).trim()
    if (token.includes(' ') || !token.includes('/')) continue
    if (!/\.[a-z]{1,7}$/.test(token)) continue
    if (token.includes('*') || token.includes('<')) continue
    // `packages/i18n/src/messages/{en,de,es}.ts` names three files at once.
    // A brace expansion is a way of writing several paths, not one path.
    if (token.includes('{') || token.includes('}')) continue
    // `core/imports.prepare` is the `prepare` function in `core/imports.py`,
    // and reads as a path because `.prepare` looks like an extension. An
    // extension no tracked file uses is not one: this keeps the filter honest
    // without a list of suffixes somebody has to maintain, and a genuine new
    // file type is known the moment one is committed.
    const suffix = /\.([a-z]{1,7})$/.exec(token)?.[1]
    if (!suffix || !extensions().has(suffix)) continue
    if (/^(https?:|--|\$|#|\.\.\/)/.test(token)) continue
    // Another repository, named on purpose. SYNC_BACKLOG is mostly this;
    // PRODUCT_SIGN_IN cites ZITADEL's own source for the behaviour of a
    // feature flag, which is worth naming by file precisely because the
    // behaviour is not in ZITADEL's documentation.
    if (/^(koras-(control-plane|saas-starter)|zitadel\/zitadel)\//.test(token)) continue
    // An absolute path on the reader's machine -- C:/Program Files/Git/bin/bash.exe,
    // C:/WINDOWS/system32/bash.exe. Named because the reader has to type them,
    // and not this repository's to have.
    if (/^[A-Za-z]:\//.test(token)) continue
    found.add(token)
  }
  return [...found].sort()
}

describe('paths named in the documentation', () => {
  const known = suffixes()

  it('has documents to read and paths to check', () => {
    // A filter that quietly matched nothing would make every case below pass
    // for the wrong reason — the failure mode of a test that reads text.
    expect(documents().length).toBeGreaterThan(5)
    expect(documents().flatMap(referencedPaths).length).toBeGreaterThan(30)
  })

  it.each(documents())('all exist, in %s', (doc) => {
    const missing = referencedPaths(doc).filter(
      (path) => !known.has(path) && !(path in ABSENT_ON_PURPOSE) && !(path in MOVED),
    )

    expect(
      missing,
      `${doc} names these and nothing in the repository matches them. ` +
        'If a file moved, add it to MOVED rather than editing a dated passage: ' +
        'rewriting the path falsifies the record of what was true then.',
    ).toEqual([])
  })

  it('exempts only paths this repository really does not have', () => {
    for (const [path, reason] of Object.entries(ABSENT_ON_PURPOSE)) {
      expect(known.has(path), `${path} exists now, so "${reason}" is stale`).toBe(false)
    }
  })

  it('records a move only where the old path is gone and the new one is there', () => {
    for (const [was, now] of Object.entries(MOVED)) {
      expect(known.has(was), `${was} exists again; it is not a moved path`).toBe(false)
      expect(known.has(now), `${was} is recorded as moved to ${now}, which does not exist`).toBe(
        true,
      )
    }
  })
})
