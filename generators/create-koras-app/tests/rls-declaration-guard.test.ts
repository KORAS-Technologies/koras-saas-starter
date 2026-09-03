import { describe, it, expect, beforeAll } from 'vitest'
import { join } from 'node:path'
import { loadProfile } from '../src/profiles/index.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { renderTemplate } from '../src/generation/engine.js'

/**
 * A transaction that has not said what it is for does not open.
 *
 * This replaced a pair of helpers -- `set_rls_context` and
 * `set_provisioning_context` -- that a caller had to remember to call, and the
 * direction the two designs fail in is the whole argument for the change.
 *
 *   a missed call         the query succeeds and returns MORE than it should
 *   a missed declaration  the transaction refuses to open
 *
 * A query that succeeds and over-returns looks exactly like a working feature.
 * That is not hypothetical: `koras-control-plane` shipped a helper of that
 * shape, nothing ever called it, the services connected as the table owner so
 * RLS never applied, and the policies sat inert while everyone believed they
 * were load bearing. It was found by connecting as the restricted role and
 * counting rows, not by anything failing.
 *
 * Promoted from that repository as TS-14. A product needs it more than the
 * Control Plane does: it is the profile with customer tenant tables.
 */

function render(profile: 'product' | 'control-plane'): Map<string, string> {
  const { manifest, defaults } = loadProfile(profile)
  const ctx = buildContext({
    projectName: `a-${profile}`,
    projectSlug: `a-${profile}`,
    profile,
    manifest,
    defaults,
    selections: resolveSelections(manifest, defaults),
    outputDir: join(__dirname, 'unused'),
    dryRun: true,
    provision: false,
  })
  return new Map(renderTemplate(ctx).map((f) => [f.outputPath, f.content.toString()]))
}

const PACKAGE = 'python-packages/koras-database/src/koras_database/__init__.py'

describe.each(['product', 'control-plane'] as const)('%s: the declaration guard', (profile) => {
  let files: Map<string, string>
  beforeAll(() => {
    files = render(profile)
  })

  it('refuses a transaction that declared nothing', () => {
    const pkg = files.get(PACKAGE) ?? ''
    expect(pkg).toContain('class UndeclaredCaller')
    // Raised, not logged and not defaulted. A default would be a caller.
    expect(pkg).toMatch(/raise UndeclaredCaller\(/)
  })

  it('installs on the engine, not on a session class', () => {
    // The engine is the narrower waist: it covers sessions built directly,
    // connections taken outside a session, and anything added later, none of
    // which a session-level listener would see.
    const pkg = files.get(PACKAGE) ?? ''
    expect(pkg).toMatch(/def install_rls\(engine: AsyncEngine\)/)
    expect(pkg).toMatch(/engine\.sync_engine/)
  })

  it('fires per transaction, not per session', () => {
    // The settings are transaction-local and repositories commit part-way
    // through their work. A context set at session open is gone for every
    // statement after the first commit.
    const pkg = files.get(PACKAGE) ?? ''
    expect(pkg).toMatch(/@event\.listens_for\([^)]*["']begin["']\)/)
  })

  it('carries the mechanism and none of the vocabulary', () => {
    // The seam. A product scopes rows by tenant; the Control Plane scopes them
    // by actor and organization. Neither vocabulary belongs in a shared
    // package, and the guard does not need to know either to refuse.
    const pkg = files.get(PACKAGE) ?? ''
    expect(pkg).toContain('class Declaration')
    expect(pkg, 'a setting name leaked into the shared package').not.toMatch(
      /['"]app\.(tenant_id|actor_type|zitadel_org_id)['"]/,
    )
  })

  it('binds the values rather than interpolating them', () => {
    // `SET` takes no bind parameters, so `SET LOCAL` would mean building a
    // statement out of a value that arrived in a token -- an injection vector
    // in the one function the tenant boundary depends on.
    const pkg = files.get(PACKAGE) ?? ''
    expect(pkg).toMatch(/set_config\('\{name\}', :\{parameter\}, true\)/)
  })
})

describe('product: what a transaction may be for', () => {
  let files: Map<string, string>
  beforeAll(() => {
    files = render('product')
  })

  const DECLARATIONS = 'python-packages/koras-tenant/src/koras_tenant/__init__.py'

  it('declares a tenant, a provisioning run, and an organization lookup', () => {
    const declarations = files.get(DECLARATIONS) ?? ''
    for (const name of ['class Tenant:', 'class Provisioning:', 'class OrganizationLookup:']) {
      expect(declarations, `${name} is not declared`).toContain(name)
    }
  })

  it('clears the provisioning flag when a tenant is declared', () => {
    // Transaction-local, so on any path reachable today it is already empty --
    // but "already empty" is a property of how sessions happen to be opened.
    // A tenant request that ran with the flag still set would read every
    // tenant's rows.
    const declarations = files.get(DECLARATIONS) ?? ''
    expect(declarations).toMatch(
      /class Tenant:[\s\S]*?def settings\(self\)[\s\S]*?["']app\.provisioning["']:\s*["']off["']/,
    )
  })

  it('declares the lookup that runs before a tenant exists', () => {
    // The declaration a guard makes necessary and a pair of helpers did not.
    // `resolve_tenant` runs on a session with no tenant context -- finding the
    // tenant is what it is for -- so it must still say what it is.
    const declarations = files.get(DECLARATIONS) ?? ''
    expect(declarations).toMatch(/declare\(OrganizationLookup\(/)
  })

  it('installs the guard where the engine is made', () => {
    const engine = files.get('services/api/koras_api/core/engine.py') ?? ''
    expect(engine).toContain('install_rls(engine)')
  })

  it('leaves no caller of the retired helpers', () => {
    // The point of retiring them rather than leaving them beside the guard: a
    // helper that still exists is one somebody will call, and calling it is
    // exactly the failure mode this replaced.
    for (const [path, content] of files) {
      if (!path.endsWith('.py')) continue
      expect(content, `${path} still calls a retired helper`).not.toMatch(
        /set_rls_context|set_provisioning_context|set_organization_context/,
      )
    }
  })
})
