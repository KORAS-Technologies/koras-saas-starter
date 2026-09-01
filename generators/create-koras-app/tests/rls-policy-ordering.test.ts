import { describe, it, expect } from 'vitest'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'

/**
 * Row-level security policies ship as numbered migrations, and the migrate
 * script does not re-apply a policies directory on top of them.
 *
 * `local/scripts/migrate.sh` used to apply every migration and then every file
 * in `supabase/policies/`. A policy defined in both places was applied twice,
 * with the directory winning:
 *
 *     00001 .. 000NN   create the corrected policies
 *     policies/*.sql   recreate the older ones on top
 *
 * An existing database never showed it, because the directory had already been
 * applied before any corrective migration ran. Only a clean bootstrap inverts
 * the order — the case least likely to be noticed, and the one that becomes
 * production. It restored a cross-organization read in the Control Plane, which
 * found it downstream and fixed it there; both templates kept shipping it for
 * weeks afterwards.
 *
 * Asserted against the rendered output rather than the template directory,
 * because what matters is what a generated project contains.
 */

const PROFILES: ProfileName[] = ['product', 'control-plane']

/**
 * Every rendered migration, as one string.
 *
 * Read across the whole directory rather than out of a named file. The
 * assertions below were written against `00002_rls_policies.sql` alone, which
 * meant a policy added in a later migration — which is where a policy is
 * supposed to be added — was asserted about by nothing.
 */
function migrationSql(files: Map<string, string>): string {
  return [...files.entries()]
    .filter(([path]) => path.startsWith('supabase/migrations/') && path.endsWith('.sql'))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, content]) => content)
    .join('\n')
}

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

describe.each(PROFILES)('%s: policies are versioned, not re-applied', (profile) => {
  const files = render(profile)

  it('ships no .sql under supabase/policies', () => {
    const stray = [...files.keys()].filter(
      (p) => p.startsWith('supabase/policies/') && p.endsWith('.sql'),
    )
    expect(stray, 'a policy here is re-applied on top of the migrations').toEqual([])
  })

  it('leaves a README saying why the directory is empty', () => {
    // Without it the directory reads as a place to add policies, which is how
    // one gets added back.
    expect(files.has('supabase/policies/README.md')).toBe(true)
  })

  it('migrate.sh does not loop over the policies directory', () => {
    const script = files.get('local/scripts/migrate.sh')
    expect(script, 'migrate.sh is not rendered').toBeDefined()
    expect(script).not.toMatch(/for\s+file\s+in\s+.*supabase\/policies/)
  })

  it('migrate.sh still applies the migrations', () => {
    // The negative above is satisfied by a script that applies nothing at all,
    // so the positive has to be asserted beside it.
    expect(files.get('local/scripts/migrate.sh')).toMatch(
      /for\s+file\s+in\s+.*supabase\/migrations/,
    )
  })
})

describe('the product ships its policies as a migration', () => {
  const files = render('product')

  it('carries the tenant policies in a numbered migration', () => {
    const migration = files.get('supabase/migrations/00002_rls_policies.sql')
    expect(migration, 'the policies moved out of policies/ and must land here').toBeDefined()
    expect(migration).toContain('create policy "tenants_select_own"')
    expect(migration).toContain('current_tenant_id()')
  })

  it('scopes every policy by tenant rather than by authentication alone', () => {
    // `auth.role() = 'authenticated'` was the shape that leaked on the Control
    // Plane: it admits any signed-in caller to every row. Nothing here
    // authenticates through Supabase, so it is also always NULL.
    //
    // Read across every migration rather than out of 00002 alone. This was
    // written against that one file, so a policy added in a later migration --
    // which is where policies are supposed to be added -- was asserted about by
    // nothing at all.
    const sql = migrationSql(files)

    expect(sql).not.toContain('auth.role()')
    for (const statement of sql.split('create policy').slice(1)) {
      // Two predicates are acceptable, and only two.
      //
      // `current_tenant_id()` is the normal one: the row belongs to the tenant
      // making the request.
      //
      // `is_provisioning()` is the Control Plane creating a tenant, where there
      // is no tenant yet to be scoped by -- so those policies are unscoped by
      // necessity, and what keeps them narrow is that one transaction-local
      // flag, set by one dependency, reachable from one machine-only router.
      // Nothing derives it from a request.
      //
      // `current_organization_id()` is the customer's own first read, added by
      // 00004. It is a third predicate rather than a loophole, and the
      // difference is that it *is* a scope: it matches the single tenant whose
      // `zitadel_org_id` equals a transaction-local setting taken from a token
      // the API verified against ZITADEL -- the same provenance
      // `current_tenant_id()` has, and unique on the table, so it can never
      // admit two rows.
      //
      // It exists because the alternative is worse. Resolving a tenant is the
      // one read that cannot be scoped by tenant, since finding the tenant is
      // what establishes the scope; the usual answer is a `security definer`
      // function with the policies suspended, which is a privilege escalation
      // kept narrow by convention rather than by the database.
      //
      // Two properties keep it honest, and both are asserted below and in
      // `supabase/tests/040_organization_lookup.sql`: it appears on `select`
      // only, and it appears on `tenants` only. A write admitted by it, or a
      // settings row reachable through it, would make it the loophole this
      // comment says it is not.
      expect(statement, 'a policy with no tenant predicate admits every tenant').toMatch(
        /current_tenant_id\(\)|is_provisioning\(\)|current_organization_id\(\)/,
      )
    }
  })

  it('lets the organization lookup select one table, and never write', () => {
    // The narrowness the predicate above is allowed on the strength of.
    //
    // `current_organization_id()` is a lookup key, not a session: a caller
    // holding one has proved which organization they belong to and nothing
    // else. Admitting an update on it would let that fact rename somebody's
    // tenant; admitting it on `tenant_settings` would let it read a row that
    // resolving the tenant is the precondition for.
    const sql = migrationSql(files)

    for (const chunk of sql.split('create policy').slice(1)) {
      // Bounded at the statement terminator. Splitting on the keyword leaves
      // the following file's header comment attached to the last policy of the
      // previous one, and 00004's header names the very function this is
      // looking for -- so an unbounded chunk matched a policy that has nothing
      // to do with it.
      const statement = chunk.slice(0, chunk.indexOf(';'))
      if (!/current_organization_id\(\)/.test(statement)) continue

      const head = statement.slice(0, statement.indexOf('using'))
      expect(head, 'the organization lookup must be select-only').toMatch(/for\s+select/)
      expect(head, 'the organization lookup belongs on tenants alone').toMatch(
        /on\s+public\.tenants/,
      )
    }
  })

  it('sets the provisioning flag from nothing a caller can reach', () => {
    // The predicate above is only as good as what can turn it on. If a header,
    // a body field or a claim could set `app.provisioning`, every policy gated
    // on it would be reachable by asking.
    const sql = migrationSql(files)

    // Null when nothing set it, which is what makes the default false.
    expect(sql).toMatch(/current_setting\('app\.provisioning', true\)/)

    // And exactly one place sets it, on a session that carries no tenant.
    const helper = files.get('services/api/koras_api/core/database.py') ?? ''
    expect(helper).toContain('set_provisioning_context')
    expect(helper, 'the provisioning session must not also resolve a tenant').toMatch(
      /async def get_platform_session\(\) -> AsyncGenerator/,
    )
  })
})
