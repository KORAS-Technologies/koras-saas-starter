import { describe, it, expect } from 'vitest'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { parseTerraformOutputs } from '../src/terraform/outputs.js'
import { buildRegistration } from '../src/registration/contract.js'
import { decideRegistration } from '../src/registration/guard.js'

/**
 * The product half of the registration contract.
 *
 * The Control Plane's `ProductRegistrationRequest` sets `extra="forbid"`, so a
 * field invented here is a 422 rather than something quietly ignored. These
 * assert the payload against that schema as written, and against the rule the
 * schema exists to enforce: the Control Plane stores references and never
 * credentials.
 */

function ctxFor(profile: ProfileName, slug: string) {
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
  })
}

/**
 * Terraform output JSON of the shape a real apply produces, including two
 * outputs marked sensitive. Those are the point: the parser must drop them, so
 * a payload built from the result cannot carry them however it is written.
 */
const OUTPUTS = JSON.stringify({
  github_repository_full_name: { value: 'KORAS-Technologies/shop' },
  github_repository_url: { value: 'https://github.com/KORAS-Technologies/shop' },
  doppler_project_name: { value: 'shop' },
  supabase_project_refs: { value: { dev: 'ref-dev', test: 'ref-test', stg: 'ref-stg', prod: 'ref-prod' } },
  zitadel_project_ids: { value: { dev: '1', test: '2', stg: '3', prod: '4' } },
  vercel_project_ids: {
    value: { 'web-dev': 'prj_a', 'admin-dev': 'prj_b', 'web-prod': 'prj_c', 'admin-prod': 'prj_d' },
  },
  fly_app_names: {
    value: { 'api-dev': 'shop-api-dev', 'worker-dev': 'shop-worker-dev', 'api-prod': 'shop-api-prod' },
  },
  zitadel_client_ids: { value: { dev: 'client-dev' }, sensitive: true },
  redis_urls: { value: { dev: 'rediss://default:hunter2@example.upstash.io' }, sensitive: true },
})

describe('the registration payload', () => {
  const ctx = ctxFor('product', 'shop')
  const payload = buildRegistration(ctx, parseTerraformOutputs(OUTPUTS))

  it('identifies the product the way the registry does', () => {
    expect(payload.code).toBe('shop')
    expect(payload.slug).toBe('shop')
    expect(payload.profile).toBe('product')
    expect(payload.repository).toBe('KORAS-Technologies/shop')
  })

  it('describes every environment the profile declares', () => {
    expect(Object.keys(payload.environments).sort()).toEqual(['dev', 'prod', 'stg', 'test'])
  })

  it('keys fly apps by service and vercel projects by application', () => {
    // The outputs are flat and keyed for Terraform's convenience; the Control
    // Plane wants them per environment. A slug containing a hyphen is why the
    // service is recovered by trimming the ends rather than by splitting.
    expect(payload.environments.dev.infrastructure.fly_apps).toEqual({
      api: 'shop-api-dev',
      worker: 'shop-worker-dev',
    })
    expect(payload.environments.dev.infrastructure.vercel_projects).toEqual({
      web: 'prj_a',
      admin: 'prj_b',
    })
  })

  it('does not attribute another environment resources to dev', () => {
    expect(payload.environments.prod.infrastructure.fly_apps).toEqual({ api: 'shop-api-prod' })
    expect(payload.environments.prod.infrastructure.supabase_project_ref).toBe('ref-prod')
  })

  it('carries no credential, whatever the outputs held', () => {
    // The parser drops sensitive outputs and the payload is built from what
    // survives, so this holds by construction. Asserted anyway: the failure it
    // guards against writes a credential to a database, an audit log and a
    // backup in one request, and it would not be visible in a diff of this
    // file.
    const serialised = JSON.stringify(payload)
    expect(serialised).not.toContain('hunter2')
    expect(serialised).not.toContain('rediss://')
    expect(serialised).not.toContain('client-dev')
  })

  it('sends no field the Control Plane would refuse', () => {
    // `extra="forbid"` there. Every key here is one ProductRegistrationRequest
    // declares; anything else is a 422 at the edge rather than a warning.
    const allowed = new Set([
      'code', 'name', 'slug', 'repository', 'profile',
      'primary_domain', 'starter_version', 'profile_version', 'environments',
    ])
    expect(Object.keys(payload).filter((k) => !allowed.has(k))).toEqual([])

    const allowedRefs = new Set([
      'github_repository', 'doppler_project', 'doppler_config',
      'supabase_project_ref', 'supabase_api_url', 'zitadel_instance',
      'zitadel_project_id', 'zitadel_client_id', 'vercel_projects',
      'fly_apps', 'cloudflare_zone_id', 'platform_api_base_url',
    ])
    for (const env of Object.values(payload.environments)) {
      expect(Object.keys(env).sort()).toEqual(['infrastructure', 'services'])
      expect(Object.keys(env.infrastructure).filter((k) => !allowedRefs.has(k))).toEqual([])
    }
  })
})

describe('whether to register at all', () => {
  const product = loadProfile('product').manifest
  const controlPlane = loadProfile('control-plane').manifest

  it('registers a provisioned product', () => {
    expect(
      decideRegistration({ profile: 'product', manifest: product, skipRequested: false, provisioned: true }),
    ).toEqual({ register: true })
  })

  it('never registers the Control Plane', () => {
    // Invariant 2. The Control Plane refuses this at its own edge and in its
    // schema; this is the third refusal, and the only one that stops the
    // request being made.
    const decision = decideRegistration({
      profile: 'control-plane', manifest: controlPlane, skipRequested: false, provisioned: true,
    })
    expect(decision.register).toBe(false)
    expect(decision.reason).toBe('profile')
  })

  it('does not report --skip-registration as the reason the Control Plane skipped', () => {
    // The flag overrides nothing there. Saying it did would suggest passing it
    // is what prevented the call, and that dropping it would cause one.
    expect(
      decideRegistration({
        profile: 'control-plane', manifest: controlPlane, skipRequested: true, provisioned: true,
      }).reason,
    ).toBe('profile')
  })

  it('honours --skip-registration for a product', () => {
    expect(
      decideRegistration({ profile: 'product', manifest: product, skipRequested: true, provisioned: true }),
    ).toMatchObject({ register: false, reason: 'requested' })
  })

  it('skips when nothing was provisioned', () => {
    // R-001: a product may be generated, or provisioned, before any Control
    // Plane is live. That is the documented bootstrap order, not an error --
    // and there are no references to register either way.
    expect(
      decideRegistration({ profile: 'product', manifest: product, skipRequested: false, provisioned: false }),
    ).toMatchObject({ register: false, reason: 'not-provisioned' })
  })
})
