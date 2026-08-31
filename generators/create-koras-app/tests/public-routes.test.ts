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

  /**
   * The second list, and why it has to be a second list.
   *
   * `apps/web` serves a public homepage at `/`, so one path has to be exempt
   * that the prefix list above cannot express: `'/'` is a prefix of everything.
   * It is matched with `includes` on the whole pathname instead, which cannot
   * widen -- `/dashboard` does not equal `/`.
   *
   * Asserted per application rather than in one place, because the value of the
   * exemption is that only one application has it. `apps/admin` has no public
   * surface and must not acquire one by copying this file.
   */
  it('exempts the root exactly when the application serves a public homepage', () => {
    const exact = /const PUBLIC_EXACT_PATHS = \[([^\]]*)\]/.exec(source)?.[1]
    const servesPublicHome = profile === 'product' && app === 'web'

    if (!servesPublicHome) {
      expect(exact ?? '', `${profile}/${app} exempts a path it should not`).toBe('')
      return
    }

    expect(exact, 'no PUBLIC_EXACT_PATHS found').toBeTruthy()
    // Exactly one, and exactly the root. A second entry here is a route that
    // stopped being gated without anybody deciding it should.
    expect((exact ?? '').match(/'[^']*'/g)).toEqual(["'/'"])
    expect(source).toContain('PUBLIC_EXACT_PATHS.includes(pathname)')
  })

  /**
   * The authenticated landing page moved when `/` became public.
   *
   * If `/dashboard` ever disappears, the exemption above stops being a trade --
   * the root would be public and there would be nothing behind the gate for a
   * signed-in person to land on, which is the shape a bad merge leaves behind.
   */
  it('keeps a gated landing page for the application that opened its root', () => {
    if (profile !== 'product' || app !== 'web') return
    expect(
      existsSync(join(PROFILES, 'product', 'template', 'apps', 'web', 'src', 'app', 'dashboard')),
    ).toBe(true)
  })

  /**
   * Static files are not pages.
   *
   * The favicon and the product logo are served from `app/` and `public/`. Left
   * inside the matcher, an anonymous browser asking for either is answered with
   * a redirect to the sign-in page -- so the tab has no icon and a configured
   * logo renders broken on the public homepage. Neither path can ever be a
   * route, because those files occupy them.
   */
  it('excludes the brand assets the public pages need', () => {
    if (profile !== 'product' || app !== 'web') return
    const matcher = /matcher: \[([^\]]*)\]/.exec(source)?.[1] ?? ''
    expect(matcher).toContain('icon.svg')
    expect(matcher).toContain('brand/')
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

describe('the signup page is rendered per request', () => {
  const page = readFileSync(
    join(PROFILES, 'product', 'template', 'apps', 'web', 'src', 'app', 'signup', 'page.tsx.hbs'),
    'utf8',
  )

  /**
   * The catalogue is not a property of the build. It is empty when a product is
   * generated and fills in whenever somebody marks a plan self-serve, which is
   * normally long after the last deploy.
   *
   * `availablePlans` fetches with `cache: 'no-store'`, which would opt the
   * route into dynamic rendering by itself -- except that it also catches its
   * own failures, so the signal never reaches Next and the route prerenders
   * with whatever the fetch returned at build time. On 2026-08-30 that was an
   * empty list produced by a catch swallowing a 500, and "signing up online is
   * not available yet" went into static HTML. Creating a plan afterwards
   * changed nothing: `X-Nextjs-Prerender: 1`, served from cache.
   */
  it('declares itself dynamic, which the catch would otherwise hide', () => {
    expect(page).toContain("export const dynamic = 'force-dynamic'")
  })

  /**
   * The reason the declaration is needed rather than redundant. If the fetch
   * ever stops catching, `cache: 'no-store'` carries the route on its own and
   * this becomes belt and braces -- but while the catch is there, it does not.
   */
  it('still fetches the catalogue without caching it', () => {
    const actions = readFileSync(
      join(PROFILES, 'product', 'template', 'apps', 'web', 'src', 'app', 'signup', 'actions.ts.hbs'),
      'utf8',
    )
    expect(actions).toContain("cache: 'no-store'")
  })

  /**
   * The verify page needs no declaration: it reads `searchParams`, which makes
   * the route dynamic in its own right. Asserted so that a refactor removing
   * that does not silently make an email link land on a prerendered page.
   */
  it('leaves verify dynamic by its use of searchParams', () => {
    const verify = readFileSync(
      join(PROFILES, 'product', 'template', 'apps', 'web', 'src', 'app', 'signup', 'verify', 'page.tsx.hbs'),
      'utf8',
    )
    expect(verify).toContain('searchParams')
  })
})
