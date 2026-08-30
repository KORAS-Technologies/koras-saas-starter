import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

/**
 * A route a stranger must reach has to be exempt from the session gate.
 *
 * The middleware protects everything by default, which is the right shape: a
 * new page is gated unless somebody says otherwise. The cost is that a route
 * whose entire purpose is to serve people who have no account has to be named,
 * and `/signup` was not.
 *
 * What that produced, observed on a deployed product on 2026-08-30:
 * `/signup` redirected to `/login?next=/signup`. You needed an account to make
 * one. And `/signup/verify` is where the confirmation email's link lands, so
 * its visitor has by definition never signed in -- the step that proves an
 * address is real was unreachable by the only person who could complete it.
 *
 * The pairing is what this asserts: an application that ships a signup surface
 * exempts it, and one that does not, does not.
 */

const PROFILES = join(__dirname, '..', '..', '..', 'profiles')

const APPS = [
  ['product', 'web'],
  ['product', 'admin'],
  ['control-plane', 'admin'],
  ['control-plane', 'portal'],
] as const

function middleware(profile: string, app: string): string {
  const path = join(PROFILES, profile, 'template', 'apps', app, 'src', 'middleware.ts.hbs')
  expect(existsSync(path), `${profile}/${app} has no middleware`).toBe(true)
  return readFileSync(path, 'utf8')
}

function shipsSignup(profile: string, app: string): boolean {
  return existsSync(join(PROFILES, profile, 'template', 'apps', app, 'src', 'app', 'signup'))
}

describe.each(APPS)('%s/%s middleware', (profile, app) => {
  const source = middleware(profile, app)
  const publicPaths = /const PUBLIC_PATHS = \[([^\]]*)\]/.exec(source)?.[1] ?? ''

  it('exempts signup exactly when the application serves one', () => {
    expect(publicPaths, 'no PUBLIC_PATHS found').not.toBe('')
    expect(publicPaths.includes("'/signup'")).toBe(shipsSignup(profile, app))
  })

  it('still gates everything else by default', () => {
    // The guard on the guard: an exemption list that grew to include the root
    // would make every assertion above vacuously true.
    expect(publicPaths).not.toContain("'/'")
    expect(source).toContain('PUBLIC_PATHS.some((path) => pathname.startsWith(path))')
  })
})

describe('the signup surface', () => {
  /**
   * Guards the pairing above. If the signup directory were ever removed, every
   * `shipsSignup` would return false and the exemption test would pass by
   * asserting that nobody exempts a route nobody serves.
   */
  it('exists in exactly one application, which is what makes the pairing meaningful', () => {
    const shipping = APPS.filter(([profile, app]) => shipsSignup(profile, app))
    expect(shipping).toEqual([['product', 'web']])
  })

  it('includes the verify page the confirmation email links to', () => {
    expect(
      existsSync(join(PROFILES, 'product', 'template', 'apps', 'web', 'src', 'app', 'signup', 'verify')),
    ).toBe(true)
  })
})
