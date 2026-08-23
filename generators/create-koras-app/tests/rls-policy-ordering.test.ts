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
    const migration = files.get('supabase/migrations/00002_rls_policies.sql') ?? ''
    expect(migration).not.toContain('auth.role()')
    for (const statement of migration.split('create policy').slice(1)) {
      expect(statement, 'a policy with no tenant predicate admits every tenant').toMatch(
        /current_tenant_id\(\)/,
      )
    }
  })
})
