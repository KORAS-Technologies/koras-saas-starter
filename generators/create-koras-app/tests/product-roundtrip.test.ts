import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { templatePath } from './template-path'

/**
 * The round-trip harness, checked from the template text.
 *
 * Shipped 2026-09-20. Before it, every browser test in a generated product ran
 * with no API: `NEXT_PUBLIC_API_URL` unset, the shell in its documented
 * degraded state. That covers what a caller may *see* and cannot cover whether
 * a change reaches a database and comes back — which is the gap settings,
 * notifications and data import each record in their own status document, and
 * why each has a manual plan nobody has run.
 *
 * It earned itself on the first run. Two defects, neither visible to anything
 * else in this repository:
 *
 * - the API refuses to start on a connection whose role bypasses row-level
 *   security, so the first attempt connected as `postgres` and was stopped by
 *   the product's own guard — without which every isolation assertion in the
 *   suite would have passed vacuously;
 * - `SettingsFormLabels.resetTo` was a closure handed to a client component,
 *   so the preferences page threw on **every product whose API answered**. The
 *   same class as the notification bell in `728d916`, in a different feature,
 *   and invisible because the page's API-less state renders before the form.
 *
 * The properties below are the ones that would let it quietly stop being any
 * of that.
 */

const PRODUCT = join(templatePath('product', 'package.json.hbs'), '..')
const REPO = join(PRODUCT, '..', '..', '..')

function read(...segments: string[]): string {
  return readFileSync(join(PRODUCT, ...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

describe('the round-trip harness', () => {
  const config = read('playwright.config.ts.hbs')

  it('ships the three things it needs', () => {
    expect(existsSync(join(PRODUCT, 'e2e', 'support', 'identity.mjs'))).toBe(true)
    expect(existsSync(join(PRODUCT, 'e2e', 'support', 'seed.sql'))).toBe(true)
    expect(existsSync(join(PRODUCT, 'e2e', 'roundtrip', 'settings.spec.ts.hbs'))).toBe(true)
  })

  it('is off unless a database is offered', () => {
    // Opt-in, and that is the design. A suite that failed when Postgres was not
    // running is a suite people stop running, and the checks that need no
    // database are the ones that catch a focus trap.
    expect(config).toContain("const DATABASE_URL = process.env.E2E_DATABASE_URL ?? ''")
    expect(config).toContain('const ROUND_TRIP = Boolean(DATABASE_URL)')
    // Without it the API address is not even passed to the web application,
    // which is what leaves the shell in the degraded state every other test
    // asserts against.
    expect(config).toContain('...(ROUND_TRIP ? { NEXT_PUBLIC_API_URL: API_URL } : {})')
  })

  it('keeps the round-trip tests out of the other projects', () => {
    // Otherwise `desktop` and `mobile` would run them with no API and fail for
    // a reason that has nothing to do with either viewport.
    const desktop = config.slice(config.indexOf("name: 'desktop'"), config.indexOf("name: 'mobile'"))
    expect(desktop).toContain('testIgnore: /roundtrip\\//')
    expect(config).toContain("name: 'roundtrip'")
    expect(config).toContain('testMatch: /roundtrip\\//')
  })

  it('verifies a real token against a real key', () => {
    // The seam is the *provider*, not the verification. A flag inside the API
    // that relaxed it would be a bypass in shipped code, and the day somebody
    // sets it in an environment that matters it is not a fixture any more.
    const identity = read('e2e', 'support', 'identity.mjs')
    expect(identity).toContain('generateKeyPairSync')
    expect(identity).toContain('/.well-known/openid-configuration')
    expect(identity).toContain('jwks_uri')
    // Generated per run, never committed: a checked-in private key is a secret
    // scanner's finding forever and an invitation to reuse.
    expect(identity).not.toMatch(/BEGIN (RSA )?PRIVATE KEY/)

    const session = read('e2e', 'support', 'session.ts.hbs')
    expect(session).toContain("alg: 'RS256'")
    // ZITADEL's own claim shape. A list here mints a token the API accepts and
    // then resolves no roles and no tenant, which reads as a broken feature.
    expect(session).toContain("'urn:zitadel:iam:org:project:roles'")
    expect(session).toContain("'urn:zitadel:iam:org:id'")
  })

  it('agrees with itself about the issuer', () => {
    // `verify_token` pins the issuer, so a token minted under one spelling of
    // the address and verified against another is refused with the same 401 a
    // forged token gets. One value, passed to both.
    expect(config).toContain('E2E_IDENTITY_URL: IDENTITY_URL')
    expect(read('e2e', 'support', 'identity.mjs')).toContain(
      'process.env.E2E_IDENTITY_URL ??',
    )
    // And `127.0.0.1` everywhere, because a host that resolves to `::1` first
    // never reaches a server bound to the IPv4 address.
    expect(config).toContain('const API_URL = `http://127.0.0.1:${API_PORT}`')
    expect(config).toContain('const IDENTITY_URL = `http://127.0.0.1:${IDENTITY_PORT}`')
  })

  it('polls the health route this API actually serves', () => {
    // `/health` is a 404 here; everything is under `/api/v1`. Polling the wrong
    // one is a two-minute timeout for a process that started correctly.
    expect(config).toContain('url: `${API_URL}/api/v1/health`')
    // And the API is a workspace member, so it is not importable from the root.
    expect(config).toContain('--directory services/api')
  })

  it('seeds a role that row-level security applies to', () => {
    // The API refuses to start otherwise, and connecting as a superuser would
    // have produced a suite in which every isolation assertion passed
    // vacuously — the worst outcome for a harness whose purpose is to check
    // that a customer sees their own rows and nobody else's.
    const seed = read('e2e', 'support', 'seed.sql')
    expect(seed).toContain('nobypassrls')
    expect(seed).toContain('koras_e2e_app')
    // Two members, because one member cannot show that a person's own value is
    // theirs alone.
    expect(seed).toContain("'e2e-subject'")
    expect(seed).toContain("'e2e-colleague'")
    // Idempotent: a seed that cannot be re-applied is one people drop the
    // database to retry.
    expect(seed).toContain('on conflict')
  })

  it('is wired into the job that already had the database and the browser', () => {
    const workflow = readFileSync(
      join(REPO, '.github', 'workflows', 'generator-integration.yml'),
      'utf8',
    )
    expect(workflow).toContain('Prepare the round-trip database')
    expect(workflow).toContain('e2e/support/seed.sql')
    expect(workflow).toContain('E2E_DATABASE_URL')
    // Its own database, so the browser suite and the isolation suite cannot
    // fail for each other's reasons.
    expect(workflow).toContain('create database koras_e2e')
  })

  it('leaves no label crossing the boundary as a function', () => {
    // The defect this harness found. `SettingsFormLabels.resetTo` was
    // `(value: string) => string` on an object handed to a client component;
    // React cannot serialise that, and the preferences page threw on every
    // product whose API answered.
    const fields = read('packages', 'ui', 'src', 'settings', 'fields.ts')
    expect(fields).toContain('resetTo: string')
    expect(fields).not.toContain('resetTo: (value: string) => string')
    expect(fields).toContain('export function withValue(')
    for (const page of ['preferences', 'settings']) {
      const source = read('apps', 'web', 'src', 'app', 'dashboard', page, 'page.tsx.hbs')
      expect(source, `${page} still builds resetTo as a closure`).not.toMatch(
        /resetTo: \(value/,
      )
    }
  })
})
