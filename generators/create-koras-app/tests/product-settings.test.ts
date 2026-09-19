import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import yaml from 'js-yaml'
import { templatePath } from './template-path'

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
 * module with no `__init__.py`, so two packages each carrying a `support.py`
 * are two modules with one name. `mypy` refuses the pair rather than choosing
 * one, and it refuses it only when it checks the whole workspace — a single
 * package's suite runs perfectly well on its own, which is why this reached
 * CI on 2026-09-17 with every local check green.
 *
 * The convention that avoids it is already in the tree twice
 * (`reporting_support.py`, and now `settings_support.py`): a shared test helper
 * is named for the package it serves.
 */
describe('test helpers do not collide across packages', () => {
  it('gives every shared helper a name of its own', () => {
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
          // Only the helpers. A `test_*.py` name is already unique by habit,
          // and pytest's own collection would complain long before mypy.
          if (!file.endsWith('.py') || file.startsWith('test_')) continue
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

    // Not vacuous: the helpers it is meant to be comparing really are there.
    expect(seen.has('settings_support.py')).toBe(true)
    expect(seen.has('support.py')).toBe(true)
  })
})
