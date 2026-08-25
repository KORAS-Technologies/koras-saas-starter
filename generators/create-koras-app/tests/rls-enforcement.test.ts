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

describe.each(PROFILES)('%s: RLS applies to the connecting role', (profile) => {
  const files = render(profile)
  const sql = migrations(files)

  it('ships migrations to assert about', () => {
    expect(sql, 'no migrations rendered').not.toBe('')
  })

  it('forces RLS on every table it enables it on', () => {
    const enabled = [...sql.matchAll(/alter table (public\.\w+) enable row level security/g)].map(
      (m) => m[1],
    )
    const forced = [...sql.matchAll(/alter table (public\.\w+) force row level security/g)].map(
      (m) => m[1],
    )

    expect(enabled.length, 'no table enables RLS').toBeGreaterThan(0)
    expect(
      enabled.filter((t) => !forced.includes(t)),
      'these tables enable RLS without forcing it; the owner bypasses their policies',
    ).toEqual([])
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
