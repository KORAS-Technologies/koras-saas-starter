import { describe, it, expect } from 'vitest'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'

/**
 * Row-level security is enforced against the role that actually connects.
 *
 * `enable row level security` exempts the table's owner. The migrations run as
 * the owner and the API connects with the same credentials, so a schema with
 * RLS enabled and not forced has policies that are present, correct, and never
 * consulted -- the isolation reads as complete in the migration and does
 * nothing at runtime.
 *
 * Nothing catches this by accident. A hand-written test connects as whatever
 * the developer has, which is the owner, and every policy appears to work
 * because the owner sees everything either way. It fails open, and it fails
 * open in the direction of cross-tenant reads.
 *
 * Asserted on rendered output because that is what a generated project runs.
 */

const PROFILES: ProfileName[] = ['product', 'control-plane']

function render(profile: ProfileName) {
  const { manifest, defaults } = loadProfile(profile)
  const ctx = buildContext({
    projectName: `rls-${profile}`,
    projectSlug: `rls-${profile}`,
    profile,
    manifest,
    defaults,
    selections: resolveSelections(manifest, defaults),
    outputDir: '.',
    dryRun: true,
    provision: false,
  })
  return new Map(renderTemplate(ctx).map((f) => [f.outputPath, f.content.toString()]))
}

function migrations(files: Map<string, string>): string {
  return [...files.entries()]
    .filter(([path]) => path.startsWith('supabase/migrations/') && path.endsWith('.sql'))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, sql]) => sql)
    .join('\n')
}

/**
 * The two profiles mean different things by "RLS is enabled", and applying one
 * profile's rule to the other is a lock-out rather than a hardening.
 *
 *   product        policies scope rows by tenant. force RLS, and connect as a
 *                  role that cannot bypass it.
 *   control-plane  no tenant model, no policies. RLS is a deny-by-default
 *                  backstop and the service role is meant to bypass it.
 *                  Forcing it binds the owner to policies that do not exist,
 *                  so every query returns nothing.
 *
 * Both were briefly given the product's treatment, which left the Control Plane
 * unable to read its own tables. That is what these assert apart.
 */
const SCOPES_BY_POLICY: Record<ProfileName, boolean> = {
  product: true,
  'control-plane': false,
}

describe.each(PROFILES)('%s: RLS applies to the connecting role', (profile) => {
  const files = render(profile)
  const sql = migrations(files)

  it('ships migrations to assert about', () => {
    expect(sql, 'no migrations rendered').not.toBe('')
  })

  it('enables RLS on its tables either way', () => {
    const enabled = [...sql.matchAll(/alter table (public\.\w+) enable row level security/g)]
    expect(enabled.length, 'no table enables RLS').toBeGreaterThan(0)
  })

  it(
    SCOPES_BY_POLICY[profile]
      ? 'forces RLS, so the owner cannot skip its policies'
      : 'does not force RLS, because there are no policies for the owner to be bound to',
    () => {
      const enabled = [...sql.matchAll(/alter table (public\.\w+) enable row level security/g)].map(
        (m) => m[1],
      )
      const forced = [...sql.matchAll(/alter table (public\.\w+) force row level security/g)].map(
        (m) => m[1],
      )

      if (SCOPES_BY_POLICY[profile]) {
        expect(
          enabled.filter((t) => !forced.includes(t)),
          'these tables enable RLS without forcing it; the owner bypasses their policies',
        ).toEqual([])
      } else {
        expect(
          forced,
          'forcing RLS on a schema with no policies denies the owner and returns nothing',
        ).toEqual([])
      }
    },
  )

  it('has policies exactly where it scopes rows by them', () => {
    const policies = [...sql.matchAll(/create policy/g)].length
    if (SCOPES_BY_POLICY[profile]) {
      expect(policies, 'a tenant-scoped schema with no policies denies everything').toBeGreaterThan(0)
    } else {
      expect(policies, 'a deny-all backstop that grew policies is no longer deny-all').toBe(0)
    }
  })

  it('ships the suite that proves the policies deny a cross-tenant read', () => {
    expect(files.has('supabase/tests/010_rls_structure.sql')).toBe(true)
  })

  it('ships a runner that uses a role RLS applies to', () => {
    const runner = files.get('local/scripts/test-rls.sh')
    expect(runner, 'local/scripts/test-rls.sh is not rendered').toBeDefined()
    // A suite run as the owner passes every assertion while proving nothing.
    expect(runner).toMatch(/nobypassrls/)
    expect(runner).toMatch(/set role|SET ROLE|TEST_ROLE/)
  })

  it('refuses to serve on a connection RLS cannot restrain', () => {
    // Executing the suite against a real Postgres showed `force` is necessary
    // and not sufficient: it binds the table owner and does nothing to a
    // superuser or a BYPASSRLS role, both of which bypass unconditionally. A
    // managed Postgres commonly hands out a superuser as the default connection
    // role, so a DATABASE_URL from a dashboard yields correct policies, force
    // everywhere, a passing suite, and no isolation. See R-032.
    const db = files.get('python-packages/koras-database/src/koras_database/__init__.py') ?? ''
    expect(db).toMatch(/async def assert_rls_enforced/)
    expect(db).toMatch(/rolsuper/)
    expect(db).toMatch(/rolbypassrls/)

    const wiring = files.get('services/api/koras_api/core/database.py') ?? ''
    expect(wiring).toMatch(/async def verify_rls_enforcement/)

    // Asserted only where policies do the scoping. The Control Plane's service
    // role bypasses RLS by design, so demanding it not bypass would refuse to
    // start a service working exactly as intended.
    const settings = files.get('services/api/koras_api/core/settings.py') ?? ''
    expect(settings).toMatch(
      SCOPES_BY_POLICY[profile]
        ? /require_rls_enforcement:\s*bool\s*=\s*True/
        : /require_rls_enforcement:\s*bool\s*=\s*False/,
    )

    // At startup, before anything is served -- the failure it prevents has no
    // symptom until a tenant sees another tenant's rows.
    const main = files.get('services/api/koras_api/main.py') ?? ''
    expect(main).toMatch(/await verify_rls_enforcement\(\)/)
  })

  it('checks the connection before deploying, not only at startup', () => {
    // The API refuses to serve on a bypassing connection, which is correct and
    // late: the release is already out and it presents as a service that will
    // not boot. This answers it while it is still a configuration question.
    const script = files.get('local/scripts/check-rls-connection.sh')
    expect(script, 'local/scripts/check-rls-connection.sh is not rendered').toBeDefined()
    expect(script).toMatch(/rolsuper/)
    expect(script).toMatch(/rolbypassrls/)

    // Reads the profile from the manifest rather than the directory name or a
    // guess, because the two profiles want opposite answers.
    expect(script).toMatch(/\.koras\/project\.yaml/)
    expect(script).toMatch(/control-plane\)/)
  })

  it('gates the deployment on it, so failing stops the release', () => {
    const deploy = files.get('.github/workflows/deploy.yml') ?? ''
    expect(deploy).toMatch(/check-rls-connection\.sh/)
    // In `migrate`, which `services` depends on -- so the check runs after the
    // schema exists and before anything is deployed against it.
    const migrateOnwards = deploy.slice(deploy.indexOf('  migrate:'))
    expect(migrateOnwards.slice(0, migrateOnwards.indexOf('  services:'))).toMatch(
      /check-rls-connection\.sh/,
    )
  })

  it('ships a way to create the role it demands', () => {
    // The connection check refuses a privileged credential. Refusing without
    // providing the alternative is a deploy that fails with no fix to hand.
    const script = files.get('local/scripts/create-app-role.sh')
    expect(script, 'local/scripts/create-app-role.sh is not rendered').toBeDefined()
    expect(script).toMatch(/nosuperuser/)
    expect(script).toMatch(/nobypassrls/)
    // Reads the property back rather than assuming the CREATE did what it said.
    expect(script).toMatch(/rolsuper/)
  })

  it('gives migrations their own privileged credential', () => {
    // DATABASE_URL is the restricted role, so migrations cannot use it. The
    // privileged one is named so that it is visibly privileged -- a plain
    // DATABASE_URL that happens to be a superuser is the trap.
    const deploy = files.get('.github/workflows/deploy.yml') ?? ''
    expect(deploy).toMatch(/DATABASE_URL_MIGRATE/)

    const migrate = deploy.slice(deploy.indexOf('  migrate:'))
    const migrateJob = migrate.slice(0, migrate.indexOf('  services:'))
    // The migration reads the privileged secret...
    expect(migrateJob).toMatch(/secrets get DATABASE_URL_MIGRATE/)
    // ...and the connection check reads the one the services use.
    expect(migrateJob).toMatch(/secrets get DATABASE_URL --plain/)
  })

  it('checks the connecting role from the suite too, when it is named', () => {
    const suite = files.get('supabase/tests/010_rls_structure.sql') ?? ''
    expect(suite).toMatch(/app_role/)
    expect(suite).toMatch(/rolbypassrls/)
    const runner = files.get('local/scripts/test-rls.sh') ?? ''
    expect(runner).toMatch(/RLS_APP_ROLE/)
  })

  it('sets the tenant context transaction-locally, not per session', () => {
    // A session-scoped context outlives the request on a pooled connection and
    // is inherited by whoever gets that connection next.
    const helper = files.get('python-packages/koras-database/src/koras_database/__init__.py')
    expect(helper, 'the RLS context helper is not rendered').toBeDefined()
    expect(helper).toMatch(/set_config\(\s*'app\.tenant_id'/)
    expect(helper, 'the third argument to set_config must be true (transaction-local)').toMatch(
      /set_config\([^)]*:tenant_id[^)]*,\s*true\s*\)/,
    )
  })
})
