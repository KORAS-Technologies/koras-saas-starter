import { describe, it, expect } from 'vitest'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { parseTerraformOutputs } from '../src/terraform/outputs.js'
import { buildRegistration, type ProductRegistration } from '../src/registration/contract.js'
import { BASE_URL_VAR, TOKEN_VAR } from '../src/registration/config.js'
import { registerProduct, type FetchLike } from '../src/registration/client.js'
import { runRegistration } from '../src/registration/index.js'
import {
  compareRegistration,
  parseStoredEnvironments,
  type StoredEnvironment,
} from '../src/registration/verify.js'

/**
 * Confirming the registry from the response.
 *
 * `registration.test.ts` asserts what the payload says and
 * `registration-client.test.ts` what happens when it is sent. This asserts
 * what a 201 is taken to mean: until 2026-09-15 it meant *accepted*, and a
 * payload stored wrongly was indistinguishable from one stored correctly (F7).
 * The Control Plane now echoes what it stored, and every test here drives the
 * three shapes that echo can take -- matching, differing, and absent.
 */

const TOKEN = 'cp_live_2f7a91d4e6b8c3a5f0'
const CONFIGURED = { [BASE_URL_VAR]: 'https://control-plane.koras.io', [TOKEN_VAR]: TOKEN }
const CONFIG = {
  baseUrl: 'https://control-plane.koras.io',
  token: TOKEN,
  endpoint: '/api/platform/v1/products',
}

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

const OUTPUTS = parseTerraformOutputs(
  JSON.stringify({
    github_repository_full_name: { value: 'KORAS-Technologies/shop' },
    doppler_project_name: { value: 'shop' },
    cloudflare_zone_id: { value: 'zone-1' },
    supabase_project_refs: { value: { dev: 'ref-dev', prod: 'ref-prod' } },
    zitadel_project_ids: { value: { dev: '1', prod: '4' } },
    vercel_project_ids: { value: { 'web-dev': 'prj_a', 'admin-dev': 'prj_b' } },
    fly_app_names: { value: { 'api-dev': 'shop-api-dev', 'worker-dev': 'shop-worker-dev' } },
    zitadel_client_ids: { value: { dev: 'client-dev' }, sensitive: true },
  }),
)

const PAYLOAD = buildRegistration(ctxFor('product', 'shop'), OUTPUTS)

/** Every field the Control Plane's `InfrastructureReferences` declares, as it answers an absent one. */
const ABSENT: Record<string, unknown> = {
  github_repository: null,
  doppler_project: null,
  doppler_config: null,
  supabase_project_ref: null,
  supabase_api_url: null,
  zitadel_instance: null,
  zitadel_project_id: null,
  zitadel_client_id: null,
  vercel_projects: {},
  fly_apps: {},
  cloudflare_zone_id: null,
  platform_api_base_url: null,
  application_base_url: null,
}

/**
 * The echo a correct Control Plane produces for this payload: nulls for what
 * was not sent, and the maps in an order the database chose rather than the
 * order they were sent in.
 */
function echoOf(payload: ProductRegistration): StoredEnvironment[] {
  return Object.entries(payload.environments).map(([environment, spec]) => {
    const infrastructure: Record<string, unknown> = { ...ABSENT, ...spec.infrastructure }
    for (const map of ['vercel_projects', 'fly_apps'] as const) {
      const value = infrastructure[map]
      if (value && typeof value === 'object') {
        infrastructure[map] = Object.fromEntries(Object.entries(value).reverse())
      }
    }
    return { environment, infrastructure, services: [...spec.services].reverse() }
  })
}

function responseFor(stored: StoredEnvironment[] | undefined): string {
  const base = {
    id: 'a2b1',
    code: 'shop',
    name: 'shop',
    slug: 'shop',
    profile: 'product',
    status: 'registered',
    environments: Object.keys(PAYLOAD.environments),
  }
  return JSON.stringify(stored === undefined ? base : { ...base, stored_environments: stored })
}

function answering(body: string, status = 201): FetchLike {
  return () => Promise.resolve({ ok: status < 400, status, text: () => Promise.resolve(body) })
}

/** A mismatching echo: one reference and one service list changed, in two environments. */
function driftedEcho(): StoredEnvironment[] {
  const stored = echoOf(PAYLOAD)
  const dev = stored.find((e) => e.environment === 'dev')!
  dev.infrastructure.fly_apps = { api: 'someone-elses-api-dev', worker: 'shop-worker-dev' }
  const prod = stored.find((e) => e.environment === 'prod')!
  prod.services = []
  return stored
}

// ── reading the echo ─────────────────────────────────────────────────────────

describe('reading what the Control Plane says it stored', () => {
  it('finds the stored environments in a response that carries them', () => {
    const stored = parseStoredEnvironments(responseFor(echoOf(PAYLOAD)))
    expect(stored).toBeDefined()
    expect(stored!.map((e) => e.environment).sort()).toEqual(
      Object.keys(PAYLOAD.environments).sort(),
    )
  })

  it('answers undefined for the older response shape, rather than throwing', () => {
    // A Control Plane deployed before 2026-09-15 answers names only. That is
    // not a malformed response; it is a response that says less.
    expect(parseStoredEnvironments(responseFor(undefined))).toBeUndefined()
  })

  it('answers undefined for no body, a non-JSON body, and a malformed field', () => {
    expect(parseStoredEnvironments('')).toBeUndefined()
    expect(parseStoredEnvironments('created')).toBeUndefined()
    expect(parseStoredEnvironments('{"stored_environments": "dev"}')).toBeUndefined()
    expect(
      parseStoredEnvironments('{"stored_environments": [{"environment": "dev"}]}'),
    ).toBeUndefined()
  })
})

// ── comparing it ─────────────────────────────────────────────────────────────

describe('comparing the payload with the registry', () => {
  it('confirms an echo that stores every reference as sent', () => {
    // Nulls for what was not sent and maps in another order are the registry
    // describing the same facts, not differences.
    expect(compareRegistration(PAYLOAD, echoOf(PAYLOAD))).toEqual({ confirmed: true })
  })

  it('ignores a reference the registry holds that this payload did not send', () => {
    // References upsert and never prune: a value registered last time and
    // omitted this time is meant to survive, and the echo lists it.
    const stored = echoOf(PAYLOAD)
    stored.find((e) => e.environment === 'prod')!.infrastructure.zitadel_client_id = 'kept'
    expect(compareRegistration(PAYLOAD, stored)).toEqual({ confirmed: true })
  })

  it('names the paths that differ, and nothing else', () => {
    const result = compareRegistration(PAYLOAD, driftedEcho())
    expect(result.confirmed).toBe(false)
    if (result.confirmed) return
    expect(result.differences).toEqual(['dev.infrastructure.fly_apps', 'prod.services'])
  })

  it('treats an environment missing from the echo as not stored', () => {
    const stored = echoOf(PAYLOAD).filter((e) => e.environment !== 'test')
    const result = compareRegistration(PAYLOAD, stored)
    expect(result.confirmed).toBe(false)
    if (result.confirmed) return
    expect(result.differences).toEqual(['test (not stored)'])
  })

  it('treats a sent reference the registry answers null for as a difference', () => {
    const stored = echoOf(PAYLOAD)
    stored.find((e) => e.environment === 'dev')!.infrastructure.supabase_project_ref = null
    const result = compareRegistration(PAYLOAD, stored)
    expect(result.confirmed).toBe(false)
    if (result.confirmed) return
    expect(result.differences).toEqual(['dev.infrastructure.supabase_project_ref'])
  })
})

// ── the client ───────────────────────────────────────────────────────────────

describe('the client and the echo', () => {
  it('hands the stored environments up with a registered outcome', async () => {
    const outcome = await registerProduct(CONFIG, PAYLOAD, {
      fetchImpl: answering(responseFor(echoOf(PAYLOAD))),
    })
    expect(outcome.status).toBe('registered')
    if (outcome.status !== 'registered') return
    expect(outcome.stored).toHaveLength(Object.keys(PAYLOAD.environments).length)
  })

  it('still registers on a 201 with nothing to read', async () => {
    const outcome = await registerProduct(CONFIG, PAYLOAD, { fetchImpl: answering('') })
    expect(outcome.status).toBe('registered')
    if (outcome.status !== 'registered') return
    expect(outcome.stored).toBeUndefined()
  })
})

// ── the step ─────────────────────────────────────────────────────────────────

describe('the registration step and the echo', () => {
  const run = (body: string) =>
    runRegistration(ctxFor('product', 'shop'), OUTPUTS, {
      skipRequested: false,
      provisioned: true,
      env: CONFIGURED,
      fetchImpl: answering(body),
    })

  it('reports the registry confirmed when the echo matches', async () => {
    const report = await run(responseFor(echoOf(PAYLOAD)))
    expect(report.kind).toBe('registered')
    if (report.kind !== 'registered') return
    expect(report.confirmation).toBe('confirmed')
    expect(report.detail).toContain('confirmed')
  })

  it('fails the step when the registry differs from what was sent', async () => {
    // Accepted is not stored. The estate is intact and the registry
    // describing it is wrong, and re-sending the same payload would store it
    // the same way, so this is not retryable.
    const report = await run(responseFor(driftedEcho()))
    expect(report.kind).toBe('failed')
    if (report.kind !== 'failed') return
    expect(report.retryable).toBe(false)
    expect(report.correlationId).toBeDefined()
    expect(report.detail).toContain('dev.infrastructure.fly_apps')
    expect(report.detail).toContain('prod.services')
  })

  it('names the differing keys and never the values on either side', async () => {
    const report = await run(responseFor(driftedEcho()))
    if (report.kind !== 'failed') return
    expect(report.detail).not.toContain('someone-elses-api-dev')
    expect(report.detail).not.toContain('shop-api-dev')
    expect(report.detail).not.toContain(TOKEN)
  })

  it('accepts an older Control Plane as registered but not confirmed', async () => {
    // The bootstrap order (R-001) is unaffected: a Control Plane that answers
    // names only is not a failure, and saying it was would fail the first
    // product in every estate whose registry predates the field.
    const report = await run(responseFor(undefined))
    expect(report.kind).toBe('registered')
    if (report.kind !== 'registered') return
    expect(report.confirmation).toBe('unconfirmed')
    expect(report.detail).toContain('not confirmed')
  })
})
