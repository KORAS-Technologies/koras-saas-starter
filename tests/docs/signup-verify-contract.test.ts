import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * Two shapes the Control Plane builds a verification link out of.
 *
 * The link used to come from `SIGNUP_VERIFY_BASE_URL`, one value on a platform
 * that runs many products: two products meant either a wrong domain in half the
 * emails or a per-product setting added by hand at every launch. It is derived
 * from `products.primary_domain` now, which registration already carries.
 *
 * Deriving it means the Control Plane assembles
 *
 *     https://app.<primary_domain>/signup/verify?token=...          (prod)
 *     https://app-<env>.<primary_domain>/signup/verify?token=...     (all others)
 *
 * and every part of that belongs to *this* repository. The `app` label is the
 * vercel module's mapping of the `web` application; the `-<env>` suffix on
 * everything but prod is that module's domain rule; `/signup/verify` is the
 * route the product template ships.
 *
 * The environment half is asserted because leaving it out is a mistake already
 * made. A first draft of the derivation built `app.<domain>` unconditionally,
 * which is right for prod and wrong for the three environments a customer is
 * most likely to be signing up in while the thing is being tested. Change either here and the Control Plane
 * keeps sending links to a page that no longer exists -- with nothing failing,
 * because the only symptom is a customer who cannot finish signing up and has
 * no way to report why.
 *
 * So the coupling is asserted where the change would be made, rather than in
 * the repository that depends on it. That is the only end of a cross-repository
 * contract this repository can hold.
 */

const ROOT = join(__dirname, '..', '..')

describe('the shape the Control Plane builds a verification link from', () => {
  it('serves the web application at the `app` hostname', () => {
    const variables = readFileSync(
      join(ROOT, 'infrastructure', 'terraform', 'modules', 'vercel', 'variables.tf'),
      'utf8',
    )
    const defaults = variables.slice(variables.indexOf('variable "application_hostnames"'))

    expect(
      /\bweb\s*=\s*"app"/.test(defaults),
      'application_hostnames no longer maps web -> app. The Control Plane builds ' +
        'https://app.<primary_domain>/signup/verify from this; change it there in ' +
        'the same breath, or verification emails point at a host that does not exist.',
    ).toBe(true)
  })

  it('suffixes every environment but prod', () => {
    // `app.<domain>` for prod and `app-<env>.<domain>` otherwise. A derivation
    // that ignores this sends three of four environments to a host that does
    // not resolve -- which is what the setting it replaces actually did: it
    // held web-dev.<domain> while DNS held app-dev.<domain>.
    const main = readFileSync(
      join(ROOT, 'infrastructure', 'terraform', 'modules', 'vercel', 'main.tf'),
      'utf8',
    )

    expect(
      /environment == "prod"/.test(main),
      'the vercel module no longer special-cases prod when building a domain. ' +
        'The Control Plane derives app-<env>.<primary_domain> from this rule for ' +
        'every environment but prod; change it there too.',
    ).toBe(true)

    expect(
      /}-\$\{environment\}\.\$\{var\.primary_domain}/.test(main),
      'the non-prod domain is no longer <label>-<environment>.<primary_domain>.',
    ).toBe(true)
  })

  it('ships the signup verification page at /signup/verify', () => {
    // The route is the path half of the same link. A rename here is invisible
    // to anything that builds only the host.
    const page = join(
      ROOT,
      'profiles',
      'product',
      'template',
      'apps',
      'web',
      'src',
      'app',
      'signup',
      'verify',
      'page.tsx.hbs',
    )

    expect(
      existsSync(page),
      'apps/web/src/app/signup/verify/page.tsx.hbs is gone. The Control Plane ' +
        'sends customers to /signup/verify; moving the route without moving that ' +
        'breaks signup for every product at once.',
    ).toBe(true)
  })

  it('reads the token from the query string, which is what an email can carry', () => {
    const page = readFileSync(
      join(
        ROOT,
        'profiles', 'product', 'template', 'apps', 'web', 'src', 'app',
        'signup', 'verify', 'page.tsx.hbs',
      ),
      'utf8',
    )
    expect(page).toContain('searchParams')
    expect(page).toContain('token')
  })
})
