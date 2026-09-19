import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import yaml from 'js-yaml'
import { templatePath } from './template-path'
import {
  sameShape,
  settingValue,
} from '../../../profiles/product/template/packages/ui/src/settings/value'
import type {
  ResolvedSetting,
  SettingValue,
} from '../../../profiles/product/template/packages/ui/src/settings/types'
import {
  DEFAULT_PAGE_SIZE,
  DEFAULT_PAGE_SIZE_OPTIONS,
  MAX_PAGE_SIZE,
  MIN_PAGE_SIZE,
  clampSize,
  paginate,
  sizeOptions,
} from '../../../profiles/product/template/packages/ui/src/data-table/paging'
import { parseEffectiveSettings } from '../../../profiles/product/template/packages/ui/src/settings/parse'

/**
 * The settings framework, checked from the template text.
 *
 * The one property this file exists for: **settings are foundation, and
 * nothing about them may be capability-gated.** The shell resolves a
 * customer's settings before it paints, and `tenant_store.create` seeds them
 * inside the transaction that creates a tenant — both of which are foundation
 * code, so by the rule at `profiles/product/manifest.yaml` a gated table here
 * would be a table foundation code reaches and the product does not have.
 *
 * That rule is written down because breaking it has happened. `audit_events`
 * sat inside the `reporting` gate until 2026-09-16, and a product generated
 * without analytics recorded nothing at all — invisible, because an empty
 * audit table and an absent one look the same from every screen.
 *
 * The rest of the assertions are the seams a rename would break silently: the
 * definitions live in one place, the extension point ships empty, every new
 * table has an isolation suite, and the package the API depends on is actually
 * declared as a dependency.
 */

const PRODUCT = join(templatePath('product', 'package.json.hbs'), '..')
const PROFILE = join(PRODUCT, '..')
const SHARED = join(PROFILE, '..', '_shared', 'template')

function read(...segments: string[]): string {
  return readFileSync(join(PRODUCT, ...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

function has(...segments: string[]): boolean {
  return existsSync(join(PRODUCT, ...segments))
}

type Manifest = {
  template_map: { capabilities: Record<string, string | string[]> }
}

function manifest(): Manifest {
  return yaml.load(readFileSync(join(PROFILE, 'manifest.yaml'), 'utf8')) as Manifest
}

function gatedPaths(): string[] {
  const map = manifest().template_map.capabilities
  return Object.values(map).flatMap((entry) => (Array.isArray(entry) ? entry : [entry]))
}

describe('the settings framework is foundation', () => {
  it('gates none of its files behind a capability', () => {
    // Every path the framework owns. A capability listing any of them would
    // produce a product whose shell reads settings that were never generated.
    const owned = [
      'supabase/migrations/00029_settings.sql',
      'supabase/migrations/00030_settings_snapshot.sql',
      'supabase/tests/260_global_settings_isolation.sql',
      'supabase/tests/270_tenant_setting_values_isolation.sql',
      'supabase/tests/280_member_setting_values_isolation.sql',
      'services/api/koras_api/core/settings_store.py',
      'services/api/koras_api/settings_catalogue',
      'tests/unit/test_settings_catalogue.py',
      'tests/unit/test_settings_snapshot.py',
    ]

    const gated = gatedPaths()
    for (const path of owned) {
      const caught = gated.filter((entry) => path === entry || path.startsWith(`${entry}/`))
      expect(caught, `${path} is gated by ${caught.join(', ')} and must not be`).toEqual([])
    }
  })

  it('ships every file it claims to own', () => {
    // The sibling of the assertion above, and the reason it is not vacuous: a
    // path listed there that does not exist would pass the gating check by
    // being absent from everything.
    for (const path of [
      'supabase/migrations/00029_settings.sql',
      'supabase/migrations/00030_settings_snapshot.sql',
      'supabase/tests/260_global_settings_isolation.sql',
      'supabase/tests/270_tenant_setting_values_isolation.sql',
      'supabase/tests/280_member_setting_values_isolation.sql',
      'services/api/koras_api/core/settings_store.py',
      'services/api/koras_api/settings_catalogue/standard.py',
      'services/api/koras_api/settings_catalogue/product.py',
      'tests/unit/test_settings_catalogue.py',
      'tests/unit/test_settings_snapshot.py',
    ]) {
      expect(existsSync(join(PRODUCT, path)), `${path} is missing`).toBe(true)
    }
  })

  it('keeps the framework itself in the shared layer, so both profiles receive it', () => {
    const pkg = join(SHARED, 'python-packages', 'koras-settings')
    expect(existsSync(join(pkg, 'pyproject.toml'))).toBe(true)
    for (const module of ['definitions', 'registry', 'coercion', 'resolver']) {
      expect(existsSync(join(pkg, 'src', 'koras_settings', `${module}.py`))).toBe(true)
    }
    // No dependencies, deliberately: the package answers with dataclasses and
    // writes nothing, and a database driver in here would be inherited by both
    // profiles and by the Control Plane's own copy of the catalogue.
    const project = readFileSync(join(pkg, 'pyproject.toml'), 'utf8')
    expect(project).toContain('dependencies = []')
  })

  it('declares the package everywhere it is imported from', () => {
    // A workspace member that nothing depends on is buildable and not
    // installed — the trap `koras-email` and `koras-ai` each fell into, and
    // the reason the root manifest names them.
    expect(read('services', 'api', 'pyproject.toml.hbs')).toContain('"koras-settings"')
    const root = read('pyproject.toml.hbs')
    expect(root).toContain('"koras-settings"')
    expect(root).toContain('koras-settings = { workspace = true }')
  })
})

describe('the settings catalogue', () => {
  it('ships its extension point empty', () => {
    // A worked example left in the list is a setting every product carries by
    // accident, and every tenant is then seeded with it forever.
    const product = read('services', 'api', 'koras_api', 'settings_catalogue', 'product.py')
    expect(product).toContain('SETTINGS: list[SettingDefinition] = []')
  })

  it('declares the page size the design fixes at fifty', () => {
    const standard = read('services', 'api', 'koras_api', 'settings_catalogue', 'standard.py')
    expect(standard).toContain('"grid.pageSize"')
    expect(standard).toMatch(/"grid\.pageSize",\s*\n\s*Category\.GRID,\s*\n\s*DataType\.INTEGER,\s*\n\s*50,/)
  })

  it('derives both i18n keys from the setting key rather than accepting prose', () => {
    const standard = read('services', 'api', 'koras_api', 'settings_catalogue', 'standard.py')
    expect(standard).toContain('label_key=f"settings.def.{key}.label"')
    expect(standard).toContain('description_key=f"settings.def.{key}.description"')
  })
})

describe('the settings tables', () => {
  const migration = read('supabase', 'migrations', '00029_settings.sql')

  it('enables and forces row-level security on all three', () => {
    // `enable` alone exempts the table owner, and both the migrations and the
    // API arrive as the owner — so the policies would be present, correct and
    // never consulted.
    for (const table of ['global_settings', 'tenant_setting_values', 'member_setting_values']) {
      expect(migration).toContain(`alter table public.${table} enable row level security`)
      expect(migration).toContain(`alter table public.${table} force row level security`)
    }
  })

  it('gives every new table a numbered isolation suite', () => {
    const suites = readdirSync(join(PRODUCT, 'supabase', 'tests')).join('\n')
    expect(suites).toContain('260_global_settings_isolation.sql')
    expect(suites).toContain('270_tenant_setting_values_isolation.sql')
    expect(suites).toContain('280_member_setting_values_isolation.sql')
  })

  it('keys a person’s values on the caller as well as the tenant', () => {
    // Both, on every verb. On the person alone somebody in two tenants reads
    // the wrong one; on the tenant alone a colleague reads theirs.
    const personal = migration.split('create table public.member_setting_values')[1] ?? ''
    for (const verb of ['select', 'insert', 'update', 'delete']) {
      const policy = `member_setting_values_${verb}_own`
      expect(personal, `${policy} is missing`).toContain(policy)
    }
    const clauses = personal.match(/user_id = public\.current_user_id\(\)/g) ?? []
    // select, insert, update (using + with check) and delete.
    expect(clauses.length).toBeGreaterThanOrEqual(5)
  })

  it('gives a tenant no way to delete its own setting', () => {
    // Deliberate, and the assertion most likely to be "fixed" by somebody
    // reading the absence as an oversight: a tenant resets by taking the
    // platform's current value, and deleting the row instead would restore the
    // dynamic inheritance the snapshot exists to prevent.
    expect(migration).not.toContain('tenant_setting_values_delete')
  })

  it('refuses a credential by constraint and not only by convention', () => {
    expect(migration).toContain('setting_holds_no_secret')
    for (const table of ['global_settings', 'tenant_setting_values', 'member_setting_values']) {
      expect(migration).toContain(`${table}_holds_no_secret`)
    }
    // The camelCase half. Setting keys are camelCase after the first segment,
    // so a pattern written only in snake_case waves `accessKey` through — which
    // it did, until the isolation suite asked it to refuse one.
    expect(migration).toContain('(private|access|api|secret)_?key')
  })
})

describe('the snapshot at provisioning', () => {
  const store = read('services', 'api', 'koras_api', 'core', 'tenant_store.py')

  it('is taken inside the transaction that creates the tenant', () => {
    // One commit. A tenant that existed without its settings would resolve
    // some keys from its own rows and the rest from whatever the platform
    // holds later — the dynamic inheritance the snapshot prevents, applied to
    // an arbitrary subset of the catalogue.
    const created = store.split('created = TenantRow(*row)')[1] ?? ''
    const seed = created.indexOf('settings_store.seed_tenant')
    const commit = created.indexOf('await session.commit()')
    expect(seed, 'the snapshot is not taken on the create path').toBeGreaterThan(-1)
    expect(seed).toBeLessThan(commit)
  })

  it('is taken on the retry path too, so an older tenant is repaired', () => {
    const retry = store.split('if row is None:')[1]?.split('created = TenantRow')[0] ?? ''
    expect(retry).toContain('settings_store.seed_tenant')
  })

  it('never overwrites a value somebody has since edited', () => {
    const seeding = read('services', 'api', 'koras_api', 'core', 'settings_store.py')
    expect(seeding).toContain('on conflict (tenant_id, key) do nothing')
    // And the provenance is written once, so a retry a week later does not
    // rewrite which version the tenant was actually seeded from.
    expect(seeding).toContain('settings_copied_at is null')
  })

  it('copies every applicable definition rather than only the platform’s rows', () => {
    // The subtle one. A key the platform has never set still gets a row;
    // copying only what exists would leave a gap the platform could fill
    // later, and filling it would move a tenant provisioned before.
    const seeding = read('services', 'api', 'koras_api', 'core', 'settings_store.py')
    expect(seeding).toContain('for definition in catalogue')
    expect(seeding).toContain('if definition.scope.admits_organization')
  })
})

describe('the settings API', () => {
  const main = read('services', 'api', 'koras_api', 'main.py.hbs')

  it('registers the router outside every capability gate', () => {
    // Between the import and the registration there is no `{{#if capability`
    // wrapping either one. A product generated with nothing optional still
    // serves these, because the shell reads them before it paints.
    expect(main).toContain('settings as settings_router')
    expect(main).toContain('settings_router.router')

    const registration = main.split('settings_router.router')[0] ?? ''
    const openGates = (registration.match(/\{\{#if capability\./g) ?? []).length
    const closedGates = (registration.match(/\{\{\/if\}\}/g) ?? []).length
    expect(openGates, 'the settings router sits inside an unclosed capability gate').toBe(
      closedGates,
    )
  })

  it('imports the router under another name than the process settings', () => {
    // `from .core.settings import settings` binds the configuration; a plain
    // `from .routers import settings` rebinds it to a module with no
    // `environment` attribute, and the app fails at import in every generated
    // product. Found on 2026-09-17 by running a generated product's tests.
    expect(main).toContain('from .core.settings import settings')
    expect(main).not.toMatch(/from \.routers import \([^)]*\n\s*settings,/)
  })

  it('answers each refusal with a code the web tier can translate', () => {
    const errors = read('services', 'api', 'koras_api', 'core', 'errors.py')
    for (const code of ['setting_not_found', 'setting_value_invalid', 'setting_scope_refused']) {
      expect(errors, `${code} is not declared`).toContain(code)
    }
    // The sentence exists in every language, which `product-i18n` enforces
    // generally; this asserts the branch that reaches it exists at all.
    const mapping = read('apps', 'web', 'src', 'lib', 'api-errors.ts.hbs')
    expect(mapping).toContain("t('errors.settingNotFound')")
    expect(mapping).toContain("t('errors.settingValueInvalid')")
    expect(mapping).toContain("t('errors.settingScopeRefused')")
  })

  it('needs no permission to resolve a caller’s own settings', () => {
    // The shell reads this on every signed-in request. A permission here means
    // a member without `settings.read` gets an unstyled page, not a refusal.
    const router = read('services', 'api', 'koras_api', 'routers', 'settings.py')
    const effective = router.split('async def effective(')[1]?.split('async def ')[0] ?? ''
    expect(effective).not.toContain('_require(')
    // And it takes no parameter naming a tenant or a person, which is what
    // makes the absence of a permission safe rather than an oversight.
    expect(effective).not.toContain('tenant_id:')
    expect(effective).not.toContain('user_id:')
  })

  it('refuses a personal write that carries no verified subject', () => {
    // Fail closed rather than silently: without the guard the statement is
    // built, the policy matches nothing, 200 is answered, and the value the
    // caller set is gone on the next read.
    const core = read('services', 'api', 'koras_api', 'core', 'tenant.py')
    expect(core).toContain('def require_subject(')
    const router = read('services', 'api', 'koras_api', 'routers', 'settings.py')
    expect(router).not.toContain('tenant.user_id')
    expect(router).toContain('require_subject(tenant)')
  })
})

describe('the language preference moves into the framework', () => {
  const migration = read('supabase', 'migrations', '00031_settings_locale_migration.sql')

  it('carries both stored halves across before dropping either', () => {
    const tenantCopy = migration.indexOf('insert into public.tenant_setting_values')
    const memberCopy = migration.indexOf('insert into public.member_setting_values')
    const dropColumn = migration.indexOf('drop column if exists locale')
    const dropTable = migration.indexOf('drop table if exists public.member_preferences')

    for (const step of [tenantCopy, memberCopy, dropColumn, dropTable]) {
      expect(step).toBeGreaterThan(-1)
    }
    expect(tenantCopy).toBeLessThan(dropColumn)
    expect(memberCopy).toBeLessThan(dropTable)
  })

  it('leaves nothing reading the columns it drops', () => {
    // The whole reason this migration is not in the same phase as the tables.
    const router = read('services', 'api', 'koras_api', 'routers', 'tenant.py')
    expect(router).not.toContain('public.member_preferences')
    expect(router).not.toContain('s.locale')
    expect(router).toContain('public.member_setting_values')
  })

  it('reads a seeded value as no choice at all', () => {
    // Every tenant holds a `general.language` row from provisioning. If `auto`
    // reported as a language, `Accept-Language` would never be consulted again
    // and a German browser would be answered in English.
    const standard = read('services', 'api', 'koras_api', 'settings_catalogue', 'standard.py')
    expect(standard).toContain('LANGUAGE_OPTIONS: tuple[str, ...] = ("auto", *LOCALES)')

    const router = read('services', 'api', 'koras_api', 'routers', 'tenant.py')
    expect(router).toContain('AUTOMATIC = "auto"')
    expect(router).toContain('def _chosen(')
  })

  it('keeps the suite that guarded the old table, under the new one', () => {
    // `160_member_preferences_isolation.sql` guarded two sentences: a person
    // may write their own row, and a colleague may not read it. The table is
    // gone and the sentences are not.
    expect(has('supabase', 'tests', '160_member_preferences_isolation.sql')).toBe(false)
    const suite = read('supabase', 'tests', '280_member_setting_values_isolation.sql')
    // The apostrophe is doubled in the SQL literal, so the assertion matches
    // either side of it rather than the escaping.
    expect(suite).toContain('row in the same tenant was visible')
    expect(suite).toContain('no subject declared')
  })
})

/**
 * Not about settings, and here because settings is where it bit.
 *
 * Every `python-packages/*\/tests/` directory is on the path as a top-level
 * module with no `__init__.py`, so two packages each carrying one filename are
 * two modules with one name. `mypy` refuses the pair rather than choosing, and
 * it refuses it only when it checks the whole workspace — a single package's
 * suite runs perfectly well on its own, which is why this reached CI on
 * 2026-09-17 with every local check green.
 *
 * **It then reached CI a second time, on 2026-09-19, past the first version of
 * this test.** That version skipped `test_*.py` on the reasoning that such a
 * name "is already unique by habit, and pytest would complain long before
 * mypy". Both halves were wrong: `test_definitions_and_registry.py` is the
 * obvious name for a registry's suite and two packages had reached for it, and
 * pytest was perfectly happy. A guard with a carve-out is a guard for the cases
 * somebody already thought of.
 *
 * So: every `.py` file in those directories, whatever it is called.
 */
describe('test helpers do not collide across packages', () => {
  it('gives every module in a tests directory a name of its own', () => {
    // Every directory whose `.py` files mypy sees as top-level modules.
    const directories: string[] = [join(PRODUCT, 'tests', 'unit')]
    for (const root of [join(SHARED, 'python-packages'), join(PRODUCT, 'python-packages')]) {
      if (!existsSync(root)) continue
      for (const entry of readdirSync(root, { withFileTypes: true })) {
        if (!entry.isDirectory()) continue
        directories.push(join(root, entry.name, 'tests'))
      }
    }

    const seen = new Map<string, string>()
    for (const tests of directories) {
      if (existsSync(tests)) {
        for (const file of readdirSync(tests)) {
          if (!file.endsWith('.py')) continue
          // The two names that are *supposed* to repeat: `__init__.py` makes a
          // package rather than a top-level module, and pytest resolves a
          // `conftest.py` by directory rather than by module name.
          if (file === '__init__.py' || file === 'conftest.py') continue
          const where = join(tests, file)
          const first = seen.get(file)
          expect(
            first,
            `${file} exists at ${where} and at ${first} — mypy refuses two ` +
              'top-level modules with one name; name a helper for its package',
          ).toBeUndefined()
          seen.set(file, where)
        }
      }
    }

    // Not vacuous: the files behind both failures really are in the scan, and
    // enough of the tree is being walked to have found them.
    expect(seen.has('settings_support.py')).toBe(true)
    expect(seen.has('support.py')).toBe(true)
    expect(seen.has('test_settings_definitions.py')).toBe(true)
    expect(seen.has('test_definitions_and_registry.py')).toBe(true)
    expect(seen.size).toBeGreaterThan(30)
  })
})

/**
 * The provider's one decision, tested rather than asserted about.
 *
 * `packages/ui` has no test runner in this template — it is typechecked and
 * exercised in a browser by Playwright, and nothing in it is unit-tested. The
 * rest of this file reads template text; this imports the module, because the
 * fallback rule is small, easy to get subtly wrong, and needs no DOM.
 */
describe('which value a component uses', () => {
  const resolved = (value: SettingValue): ResolvedSetting => ({
    key: 'grid.pageSize',
    value,
    source: 'organization',
    can_override: true,
    organization_value: value,
    global_value: value,
  })

  it('uses the resolved value when the server sent one', () => {
    expect(settingValue(resolved(100), 50)).toBe(100)
  })

  it('uses the fallback outside a provider', () => {
    // A component in a test, in a story, or on a page above the signed-in
    // area. It renders with its own default rather than crashing.
    expect(settingValue(undefined, 50)).toBe(50)
  })

  it('uses the fallback when the stored value is the wrong shape', () => {
    // A definition changed under a value that was valid when written. Trusting
    // it means a table asked to draw "comfortable" rows per page.
    expect(settingValue(resolved('comfortable'), 50)).toBe(50)
    expect(settingValue(resolved(true), 50)).toBe(50)
  })

  it('does not confuse a list with an object, in either direction', () => {
    // Both are `object` to `typeof`, and a component expecting page-size
    // options given `{}` would map over nothing and draw an empty control.
    expect(settingValue(resolved({ a: 1 }), ['10', '25'])).toEqual(['10', '25'])
    expect(settingValue(resolved(['10']), { a: 1 })).toEqual({ a: 1 })
    expect(settingValue(resolved(['10', '25']), ['50'])).toEqual(['10', '25'])
  })

  it('keeps a falsy value that is genuinely the answer', () => {
    // The mistake a `||` would make. `false` and `0` are values somebody chose.
    expect(settingValue(resolved(false), true)).toBe(false)
    expect(settingValue(resolved(0), 50)).toBe(0)
    expect(settingValue(resolved(''), 'UTC')).toBe('')
  })

  it('decides shape without deciding validity', () => {
    // Bounds and options are the definition's job, checked in the API before
    // the value was stored. This guards a type that changed, nothing else.
    expect(sameShape(9999, 50)).toBe(true)
    expect(sameShape('mauve', 'system')).toBe(true)
  })
})

describe('the settings provider', () => {
  it('loads once in the layout and wraps everything below it', () => {
    const layout = read('apps', 'web', 'src', 'app', 'dashboard', 'layout.tsx.hbs')

    // In the same concurrent read as the context and the locale — one call per
    // navigation, not one per page that happens to need a setting.
    expect(layout).toContain('effectiveSettings()')
    expect(layout).toMatch(/Promise\.all\(\[\s*\n\s*signedInContext\(\),/)

    // Outside the shell, so the header and the sidebar can read a setting too.
    const opens = layout.indexOf('<SettingsProvider')
    const shell = layout.indexOf('<AuthenticatedProductShell')
    const closes = layout.indexOf('</SettingsProvider>')
    expect(opens).toBeGreaterThan(-1)
    expect(opens).toBeLessThan(shell)
    expect(closes).toBeGreaterThan(layout.indexOf('</AuthenticatedProductShell>'))
  })

  it('never lets a settings read take the signed-in area down', () => {
    // Settings are the one thing every page reads. Failing closed here would
    // mean an unreachable API is an unreachable product.
    const loader = read('apps', 'web', 'src', 'lib', 'settings.ts.hbs')
    expect(loader).toContain('cache(')
    expect(loader).toContain('return null')
    expect(loader).toContain('catch')
  })

  it('is a client component, and the loader never reaches a browser', () => {
    const provider = read('packages', 'ui', 'src', 'settings', 'provider.tsx')
    expect(provider.startsWith("'use client'")).toBe(true)
    // The loader reads a cookie and talks to an origin the browser is not told
    // about, so it must not be imported from anything the client bundles.
    const loader = read('apps', 'web', 'src', 'lib', 'settings.ts.hbs')
    expect(loader).not.toContain("'use client'")
    expect(loader).toContain('providerToken')
  })

  it('offers the keys the catalogue declares, and does not cap what a product may add', () => {
    // A union for autocompletion, not a second catalogue: no labels, no
    // defaults, no rules. The string intersection is what lets a product
    // declare `shop.basketHoldMinutes` without editing this package.
    const types = read('packages', 'ui', 'src', 'settings', 'types.ts')
    const listed = [...types.matchAll(/^ {2}'([a-z][\w.]+)',$/gm)].map((match) => match[1]!)

    const standard = read('services', 'api', 'koras_api', 'settings_catalogue', 'standard.py')
    // The first argument of each `_setting(` call, and only that. Matching
    // every quoted string at that indent also catches defaults — `"auto"`,
    // `"comfortable"` — which are values, not keys.
    const declared = [...standard.matchAll(/_setting\(\s*\n\s*"([\w.]+)"/g)].map(
      (match) => match[1]!,
    )

    expect(listed.length).toBeGreaterThan(30)
    expect([...listed].sort()).toEqual([...declared].sort())
    expect(types).toContain('(string & Record<never, never>)')
  })
})

/**
 * The table's arithmetic, executed rather than asserted about.
 *
 * Every input here reaches the component from a customer's stored settings or
 * from a URL, so "produces a table rather than a stack trace" is a property and
 * not a nicety.
 */
describe('paging', () => {
  it('shows the first fifty rows by default', () => {
    const page = paginate(312, 1, 50)
    expect([page.start, page.end]).toEqual([0, 50])
    expect([page.from, page.to, page.total]).toEqual([1, 50, 312])
    expect(page.pages).toBe(7)
  })

  it('counts a part-full last page', () => {
    const page = paginate(312, 7, 50)
    expect([page.start, page.end]).toEqual([300, 312])
    expect([page.from, page.to]).toEqual([301, 312])
  })

  it('says page 1 of 1, showing 0 to 0, when there is nothing', () => {
    // Not "page 1 of 0", which reads as a fault, and not "showing 1 to 0 of 0",
    // which is what `start + 1` produces and what people report as a bug.
    const page = paginate(0, 1, 50)
    expect([page.pages, page.from, page.to, page.total]).toEqual([1, 0, 0, 0])
  })

  it('lands on the last page when asked for one past the end', () => {
    // Somebody on page 9 when a colleague deleted rows should see the end of
    // the list, not an empty grid that looks like the data is gone.
    expect(paginate(120, 9, 50).page).toBe(3)
    expect(paginate(120, -4, 50).page).toBe(1)
    expect(paginate(120, Number.NaN, 50).page).toBe(1)
  })

  it('treats no size as one page of everything', () => {
    // How `grid.paginationEnabled = false` is expressed, so the component has
    // one code path rather than a branch that skips the pager and another that
    // skips the slice.
    const page = paginate(312, 1, 0)
    expect([page.start, page.end, page.pages]).toEqual([0, 312, 1])
    expect(paginate(0, 1, 0).pages).toBe(1)
  })

  it('holds a page size inside the bounds the catalogue declares', () => {
    expect(clampSize(5)).toBe(MIN_PAGE_SIZE)
    expect(clampSize(5000)).toBe(MAX_PAGE_SIZE)
    expect(clampSize(Number.NaN)).toBe(DEFAULT_PAGE_SIZE)
    expect(clampSize(25)).toBe(25)
  })

  it('always offers the size actually in effect', () => {
    // A select whose current value is not among its options renders as though
    // nothing is selected, and a person then cannot get back to it.
    expect(sizeOptions(['10', '25'], 50)).toEqual([10, 25, 50])
    expect(sizeOptions(['10', '25', '50'], 50)).toEqual([10, 25, 50])
  })

  it('drops one bad option rather than the whole control', () => {
    expect(sizeOptions(['10', 'fifty', '25', '-3', ''], 25)).toEqual([10, 25])
  })

  it('falls back to the defaults when the list is unusable', () => {
    expect(sizeOptions([], 50)).toEqual([...DEFAULT_PAGE_SIZE_OPTIONS])
    expect(sizeOptions(['nonsense'], 50)).toEqual([...DEFAULT_PAGE_SIZE_OPTIONS])
  })

  it('collapses duplicates and sorts, so two orders give one control', () => {
    expect(sizeOptions(['100', '10', '10', '25'], 25)).toEqual([10, 25, 100])
  })
})

describe('the shared table', () => {
  const table = read('packages', 'ui', 'src', 'data-table', 'data-table.tsx')

  it('defaults to the page size the catalogue declares', () => {
    // One number in two languages. This is what keeps them the same number.
    const standard = read('services', 'api', 'koras_api', 'settings_catalogue', 'standard.py')
    const declared =
      /"grid\.pageSize",\s*\n\s*Category\.GRID,\s*\n\s*DataType\.INTEGER,\s*\n\s*(\d+),/.exec(
        standard,
      )?.[1]
    expect(Number(declared)).toBe(DEFAULT_PAGE_SIZE)

    const bounds = /minimum=(\d+),\s*\n\s*maximum=(\d+),/.exec(
      standard.split('"grid.pageSize"')[1] ?? '',
    )
    expect(Number(bounds?.[1])).toBe(MIN_PAGE_SIZE)
    expect(Number(bounds?.[2])).toBe(MAX_PAGE_SIZE)
  })

  it('reads its settings from context rather than from props it demands', () => {
    // `<KorasDataTable data={records} />` has to be the ordinary usage, or
    // every page ends up passing settings down and the framework buys nothing.
    for (const key of [
      'grid.pageSize',
      'grid.paginationEnabled',
      'grid.stickyHeader',
      'grid.rowDensity',
      'grid.pageSizeOptions',
    ]) {
      expect(table, `${key} is not read`).toContain(key)
    }
    // Every setting-bearing prop is optional: the `?:` is what makes the
    // one-prop usage compile.
    for (const prop of ['pageSize', 'paginationEnabled', 'stickyHeader', 'rowDensity']) {
      expect(table).toContain(`${prop}?:`)
    }
  })

  it('lets an explicit prop win over the resolved setting', () => {
    // `??` and not `||`: a page that asked for `paginationEnabled={false}` must
    // get it, and `||` would hand back the setting instead.
    expect(table).toContain('paginationEnabled ?? settingPaging')
    expect(table).toContain('stickyHeader ?? settingSticky')
    expect(table).toContain('pageSize ?? settingSize')
    expect(table).not.toMatch(/pageSize \|\|/)
  })

  it('is a real table a screen reader can use', () => {
    expect(table).toContain('<caption className="sr-only">')
    expect(table).toContain('scope="col"')
    // The pager is a landmark with a name, and the range is announced —
    // pressing Next changes content far from the button.
    expect(table).toContain('aria-label={labels.pagination}')
    expect(table).toContain('aria-live="polite"')
    // Focus is visible on both controls a keyboard reaches.
    expect(table.match(/focus-visible:outline/g)?.length).toBeGreaterThanOrEqual(2)
  })

  it('renders an empty result as a sentence rather than an empty grid', () => {
    expect(table).toContain('-empty`}')
    const empty = table.split('if (data.length === 0)')[1]?.split('cellPadding')[0] ?? ''
    expect(empty).not.toContain('<table')
  })

  it('holds no English, like every component in this package', () => {
    // Enforced generally by `product-frontend.test.ts`; asserted here because
    // a pager is where somebody reaches for a literal "Next".
    for (const word of ['Next', 'Previous', 'Rows per page', 'Showing']) {
      expect(table).not.toContain(`>${word}<`)
    }
    expect(table).toContain('labels.next')
    expect(table).toContain('labels.previous')
  })

  it('gives the pager a sentence in every language', () => {
    for (const locale of ['en', 'de', 'es']) {
      const catalogue = read('packages', 'i18n', 'src', 'messages', `${locale}.ts`)
      for (const key of [
        'grid.pagination',
        'grid.rowsPerPage',
        'grid.previous',
        'grid.next',
        'grid.showing',
        'grid.page',
      ]) {
        expect(catalogue, `${key} is missing from ${locale}`).toContain(key)
      }
      // The numbers are placeholders, so a language can put them where it
      // wants rather than in English order.
      expect(catalogue).toMatch(/grid\.showing.*\{from\}.*\{to\}.*\{total\}/)
    }
  })
})

/**
 * What the API said, checked into something a component may render.
 *
 * This exists because the two shapes were the same name for one commit. Every
 * package typechecked; the application that imported both did not, and it
 * failed in the generated-project build rather than anywhere local. The type
 * names are distinct now, and this is the seam that joins them.
 */
describe('parsing the effective settings', () => {
  const wire = (value: unknown, extra: Record<string, unknown> = {}) => ({
    settings: {
      'grid.pageSize': {
        key: 'grid.pageSize',
        value,
        source: 'organization',
        can_override: true,
        organization_value: value,
        global_value: value,
        ...extra,
      },
    },
    skipped: [],
  })

  it('keeps every type a setting can hold', () => {
    for (const value of [50, true, 'dark', ['10', '25'], { a: 1 }]) {
      const parsed = parseEffectiveSettings(wire(value))
      expect(parsed?.settings['grid.pageSize']?.value, JSON.stringify(value)).toEqual(value)
    }
  })

  it('drops one malformed setting rather than refusing the answer', () => {
    // One unrecognised setting must not unstyle the product.
    const raw = {
      settings: {
        'grid.pageSize': wire(50).settings['grid.pageSize'],
        'ui.theme': { key: 'ui.theme', value: null, source: 'default' },
      },
      skipped: [],
    }
    const parsed = parseEffectiveSettings(raw)
    expect(Object.keys(parsed?.settings ?? {})).toEqual(['grid.pageSize'])
  })

  it('refuses a value of a type no definition could produce', () => {
    // A mixed list is not a `STRING_LIST`, and null is not a setting value —
    // clearing one removes the row rather than storing a null.
    expect(parseEffectiveSettings(wire(['10', 25]))?.settings['grid.pageSize']).toBeUndefined()
    expect(parseEffectiveSettings(wire(null))?.settings['grid.pageSize']).toBeUndefined()
  })

  it('refuses a source it does not recognise', () => {
    const parsed = parseEffectiveSettings(wire(50, { source: 'somewhere-else' }))
    expect(parsed?.settings['grid.pageSize']).toBeUndefined()
  })

  it('treats a missing override flag as no override', () => {
    // Fail closed: a preferences page must not offer a control for a setting
    // the API never said this person may change.
    const parsed = parseEffectiveSettings(wire(50, { can_override: 'yes' }))
    expect(parsed?.settings['grid.pageSize']?.can_override).toBe(false)
  })

  it('falls back to the value itself when the two fallbacks are absent', () => {
    // An older answer is still usable; only the reset controls need them.
    const raw = {
      settings: {
        'grid.pageSize': { key: 'grid.pageSize', value: 100, source: 'user', can_override: true },
      },
      skipped: [],
    }
    const resolved = parseEffectiveSettings(raw)?.settings['grid.pageSize']
    expect([resolved?.organization_value, resolved?.global_value]).toEqual([100, 100])
  })

  it('answers null for something that is not an answer at all', () => {
    for (const raw of [null, undefined, 'nonsense', [], { skipped: [] }]) {
      expect(parseEffectiveSettings(raw)).toBeNull()
    }
  })

  it('keeps only the skipped keys that are strings', () => {
    const raw = { settings: {}, skipped: ['grid.pageSize', 7, null] }
    expect(parseEffectiveSettings(raw)?.skipped).toEqual(['grid.pageSize'])
  })

  it('trusts the map key over the entry key', () => {
    // If they disagree, the map is what a caller looked the setting up by.
    const raw = {
      settings: {
        'grid.pageSize': { key: 'something.else', value: 50, source: 'default', can_override: true },
      },
      skipped: [],
    }
    expect(parseEffectiveSettings(raw)?.settings['grid.pageSize']?.key).toBe('grid.pageSize')
  })
})

describe('the wire shape and the rendered shape are told apart', () => {
  it('names the API client’s types for what they describe', () => {
    // Two structurally different types with one name is a compile error in
    // whichever application imports both, and in no package on its own.
    const client = read('packages', 'api-client', 'src', 'index.ts')
    expect(client).toContain('EffectiveSettingsResponse')
    expect(client).toContain('ResolvedSettingResponse')
    expect(client).not.toMatch(/export interface EffectiveSettings\b/)
    expect(client).not.toMatch(/export interface ResolvedSetting\b/)
  })

  it('makes the application depend on the checked shape, not the wire one', () => {
    const loader = read('apps', 'web', 'src', 'lib', 'settings.ts.hbs')
    expect(loader).toContain('parseEffectiveSettings')
    // The type it promises is the one the provider takes.
    expect(loader).toMatch(/import type \{ EffectiveSettings \} from '@\{\{projectSlug\}\}\/ui'/)
  })
})

