import { describe, it, expect } from 'vitest'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext, primaryDomain } from '../src/generation/context.js'

/**
 * No two projects may ask for the same hostname.
 *
 * This is the check that was missing when R-028 happened. Every other test here
 * reads one generated project, and a collision is invisible from inside one:
 * `admin` is the right label for the Control Plane's staff application and the
 * right label for a product's operations UI, and both were correct on their own
 * terms. What was wrong was that they landed in the same namespace, because
 * `primary_domain` came from one `TF_VAR_primary_domain` shared by the whole
 * bootstrap Doppler config.
 *
 * It surfaced as `domain_already_in_use` from Vercel, half way through an apply
 * that had already created eight projects -- and because the OIDC redirect URIs
 * and the DNS records are both derived from the domain map, a naming conflict
 * presented as an identity and DNS outage.
 *
 * So this compares projects to each other rather than to the template, and it
 * compares the property that actually collides: the fully-qualified hostname.
 */

function ctxFor(profile: ProfileName, slug: string, domain?: string) {
  const { manifest, defaults } = loadProfile(profile)
  return buildContext({
    projectName: slug,
    projectSlug: slug,
    profile,
    manifest,
    defaults,
    selections: resolveSelections(manifest, defaults),
    outputDir: '.',
    dryRun: true,
    provision: false,
    domain,
  })
}

/**
 * Every hostname a project's Vercel projects would answer on.
 *
 * Mirrors the vercel module: one project per application per environment, the
 * environment suffixed except in prod, and the label taken from
 * `application_hostnames` where the key and the label differ.
 */
const HOSTNAME_LABELS: Record<string, string> = {
  portal: 'account',
  platform_admin: 'admin',
  web: 'app',
}

function hostnames(ctx: ReturnType<typeof ctxFor>): string[] {
  const domain = primaryDomain(ctx)
  const apps = Object.entries(ctx.selections.applications)
    .filter(([, on]) => on)
    .map(([key]) => HOSTNAME_LABELS[key] ?? key.replace(/_/g, '-'))

  return apps.flatMap((label) =>
    ctx.manifest.environments.map((env) =>
      env === 'prod' ? `${label}.${domain}` : `${label}-${env}.${domain}`,
    ),
  )
}

describe('no two projects claim the same hostname', () => {
  it('separates the Control Plane from a product', () => {
    const platform = hostnames(ctxFor('control-plane', 'koras-control-plane'))
    const product = hostnames(ctxFor('product', 'sample-product'))

    const shared = platform.filter((h) => product.includes(h))
    expect(shared).toEqual([])
  })

  it('separates two products from each other', () => {
    const first = hostnames(ctxFor('product', 'docoris'))
    const second = hostnames(ctxFor('product', 'dianova'))

    const shared = first.filter((h) => second.includes(h))
    expect(shared).toEqual([])
  })

  it('is not vacuous — a shared apex does collide', () => {
    // The pre-R-028 arrangement, asserted directly. Without this, narrowing the
    // derivation back to the apex would leave the two tests above passing on an
    // empty set and say nothing.
    const apex = 'korastechnologies.com'
    const platform = hostnames(ctxFor('control-plane', 'koras-control-plane', apex))
    const product = hostnames(ctxFor('product', 'sample-product', apex))

    expect(platform.filter((h) => product.includes(h))).toContain(`admin.${apex}`)
  })
})

describe('the domain a project is served under', () => {
  it('gives the Control Plane the apex, because it is the platform', () => {
    expect(primaryDomain(ctxFor('control-plane', 'koras-control-plane'))).toBe(
      'korastechnologies.com',
    )
  })

  it('namespaces a product beneath the apex', () => {
    expect(primaryDomain(ctxFor('product', 'sample-product'))).toBe(
      'sample-product.korastechnologies.com',
    )
  })

  it('lets a product with its own brand domain say so', () => {
    // The case docs/INFRASTRUCTURE_PLAN.md documents, with docoris.app.
    expect(primaryDomain(ctxFor('product', 'docoris', 'docoris.app'))).toBe('docoris.app')
  })

  it('ignores a blank --domain rather than emitting an empty suffix', () => {
    // `--domain ""` reaching the template unchecked would render
    // `primary_domain = ""`, which disables domain attachment silently and
    // leaves every application without a hostname — R-021, reintroduced.
    expect(primaryDomain(ctxFor('product', 'docoris', '   '))).toBe(
      'docoris.korastechnologies.com',
    )
  })
})
