import { describe, it, expect } from 'vitest'
import { loadProfile } from '../src/profiles/index.js'
import type { ProfileName } from '../src/profiles/loader.js'
import { resolveSelections } from '../src/profiles/validator.js'
import { buildContext } from '../src/generation/context.js'
import { parseTerraformOutputs } from '../src/terraform/outputs.js'
import { buildRegistration } from '../src/registration/contract.js'
import {
  resolveRegistrationConfig,
  registrationUrl,
  BASE_URL_VAR,
  TOKEN_VAR,
} from '../src/registration/config.js'
import { registerProduct, type FetchLike } from '../src/registration/client.js'
import { runRegistration } from '../src/registration/index.js'

/**
 * The transport half of the registration contract.
 *
 * `registration.test.ts` asserts what the payload says; this asserts what
 * happens when it is sent. Every test drives an injected fetch, so the suite
 * makes no network call and needs no Control Plane running — the acceptance
 * criterion's "against a running Control Plane" is met by a double that
 * answers the way the real one does, which is also the only form of it that
 * can run in CI.
 */

const TOKEN = 'cp_live_2f7a91d4e6b8c3a5f0'

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
    supabase_project_refs: { value: { dev: 'ref-dev' } },
    zitadel_project_ids: { value: { dev: '1' } },
    vercel_project_ids: { value: { 'web-dev': 'prj_a' } },
    fly_app_names: { value: { 'api-dev': 'shop-api-dev' } },
    zitadel_client_ids: { value: { dev: 'client-dev' }, sensitive: true },
  }),
)

const CONFIG = {
  baseUrl: 'https://control-plane.koras.io',
  token: TOKEN,
  endpoint: '/api/platform/v1/products',
}

/** A fetch double that records the one request it is given. */
function recordingFetch(response: { ok: boolean; status: number; body?: string }): {
  fetch: FetchLike
  calls: Array<{ url: string; init: Record<string, unknown> }>
} {
  const calls: Array<{ url: string; init: Record<string, unknown> }> = []
  const fetch: FetchLike = (url, init) => {
    calls.push({ url, init: (init ?? {}) as Record<string, unknown> })
    return Promise.resolve({
      ok: response.ok,
      status: response.status,
      text: () => Promise.resolve(response.body ?? ''),
    })
  }
  return { fetch, calls }
}

// ── configuration ────────────────────────────────────────────────────────────

describe('resolving where the Control Plane is', () => {
  const endpoint = '/api/platform/v1/products'

  it('reads both halves from the environment Doppler injected', () => {
    const result = resolveRegistrationConfig({
      endpoint,
      env: { [BASE_URL_VAR]: 'https://control-plane.koras.io', [TOKEN_VAR]: TOKEN },
    })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.config.baseUrl).toBe('https://control-plane.koras.io')
    // A stored token is carried as a credential *source*, unspent. It becomes
    // the bearer in `resolveBearer`, which is also where a key would be
    // exchanged for one — so both credentials reach the client the same way.
    expect(result.config.credential).toEqual({ kind: 'token', token: TOKEN })
  })

  it('lets the flag override the estate default', () => {
    const result = resolveRegistrationConfig({
      endpoint,
      urlOverride: 'https://staging-cp.koras.io',
      env: { [BASE_URL_VAR]: 'https://control-plane.koras.io', [TOKEN_VAR]: TOKEN },
    })
    expect(result.ok && result.config.baseUrl).toBe('https://staging-cp.koras.io')
  })

  it('treats an unconfigured Control Plane as absent rather than broken', () => {
    const result = resolveRegistrationConfig({ endpoint, env: {} })
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.problem.kind).toBe('no-base-url')
  })

  it('refuses to send a bearer token over plaintext to a remote host', () => {
    const result = resolveRegistrationConfig({
      endpoint,
      urlOverride: 'http://control-plane.koras.io',
      env: { [TOKEN_VAR]: TOKEN },
    })
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.problem.kind).toBe('bad-base-url')
    expect(result.problem.kind === 'bad-base-url' && result.problem.detail).toContain('https')
  })

  it('allows plaintext loopback, so a local Control Plane is testable', () => {
    for (const url of ['http://localhost:8000', 'http://127.0.0.1:8000']) {
      const result = resolveRegistrationConfig({
        endpoint,
        urlOverride: url,
        env: { [TOKEN_VAR]: TOKEN },
      })
      expect(result.ok, url).toBe(true)
    }
  })

  it('names a configured Control Plane with no token a misconfiguration', () => {
    const result = resolveRegistrationConfig({
      endpoint,
      env: { [BASE_URL_VAR]: 'https://control-plane.koras.io' },
    })
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.problem.kind).toBe('no-token')
    expect(result.problem.kind === 'no-token' && result.problem.detail).toContain(TOKEN_VAR)
  })

  it('never carries the token in the message naming the missing token', () => {
    const result = resolveRegistrationConfig({
      endpoint,
      env: { [BASE_URL_VAR]: 'https://control-plane.koras.io', OTHER: TOKEN },
    })
    const detail = result.ok ? '' : 'detail' in result.problem ? result.problem.detail : ''
    expect(detail).not.toContain(TOKEN)
  })

  it('refuses credentials embedded in the base URL', () => {
    // The same mistake as a token on the command line, arriving by a different
    // door: it would travel in the request and appear in a printed baseUrl.
    const result = resolveRegistrationConfig({
      endpoint,
      urlOverride: 'https://someone:hunter2@control-plane.koras.io',
      env: { [TOKEN_VAR]: TOKEN },
    })
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.problem.kind).toBe('bad-base-url')
    expect(result.problem.kind === 'bad-base-url' && result.problem.detail).not.toContain('hunter2')
  })

  it('joins base and endpoint without doubling the separator', () => {
    const result = resolveRegistrationConfig({
      endpoint,
      urlOverride: 'https://control-plane.koras.io/',
      env: { [TOKEN_VAR]: TOKEN },
    })
    expect(result.ok && registrationUrl(result.config)).toBe(
      'https://control-plane.koras.io/api/platform/v1/products',
    )
  })
})

// ── the request itself ───────────────────────────────────────────────────────

describe('sending the registration', () => {
  const payload = buildRegistration(ctxFor('product', 'shop'), OUTPUTS)

  it('posts JSON to the endpoint the profile declares, with a bearer token', async () => {
    const { fetch, calls } = recordingFetch({ ok: true, status: 201 })
    const outcome = await registerProduct(CONFIG, payload, {
      fetchImpl: fetch,
      correlationId: 'corr-1',
    })

    expect(outcome.status).toBe('registered')
    expect(calls).toHaveLength(1)
    expect(calls[0].url).toBe('https://control-plane.koras.io/api/platform/v1/products')
    expect(calls[0].init.method).toBe('POST')

    const headers = calls[0].init.headers as Record<string, string>
    expect(headers.authorization).toBe(`Bearer ${TOKEN}`)
    expect(headers['content-type']).toBe('application/json')
    expect(headers['x-koras-correlation-id']).toBe('corr-1')
  })

  it('sends the payload the contract built, unaltered', async () => {
    const { fetch, calls } = recordingFetch({ ok: true, status: 201 })
    await registerProduct(CONFIG, payload, { fetchImpl: fetch })
    expect(JSON.parse(calls[0].init.body as string)).toEqual(payload)
  })

  it('puts no credential in the request body', async () => {
    const { fetch, calls } = recordingFetch({ ok: true, status: 201 })
    await registerProduct(CONFIG, payload, { fetchImpl: fetch })
    const body = calls[0].init.body as string
    expect(body).not.toContain(TOKEN)
    expect(body).not.toContain('client-dev')
  })

  it('does not retry a refusal', async () => {
    const { fetch, calls } = recordingFetch({ ok: false, status: 422, body: '{"detail":"bad"}' })
    const outcome = await registerProduct(CONFIG, payload, { fetchImpl: fetch })

    expect(outcome.status).toBe('rejected')
    if (outcome.status !== 'rejected') return
    expect(outcome.httpStatus).toBe(422)
    expect(calls).toHaveLength(1)
  })

  it('separates the Control Plane being broken from the payload being wrong', async () => {
    const { fetch } = recordingFetch({ ok: false, status: 503, body: 'upstream unavailable' })
    const outcome = await registerProduct(CONFIG, payload, { fetchImpl: fetch })
    expect(outcome.status).toBe('unreachable')
  })

  it('reports a transport failure without throwing at the caller', async () => {
    const fetch: FetchLike = () => Promise.reject(new Error('ECONNREFUSED 10.0.0.1:443'))
    const outcome = await registerProduct(CONFIG, payload, { fetchImpl: fetch })
    expect(outcome.status).toBe('unreachable')
  })

  it('gives up rather than hanging on a Control Plane that never answers', async () => {
    const fetch: FetchLike = (_url, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new Error('aborted')))
      })
    const outcome = await registerProduct(CONFIG, payload, { fetchImpl: fetch, timeoutMs: 20 })

    expect(outcome.status).toBe('unreachable')
    if (outcome.status !== 'unreachable') return
    expect(outcome.detail).toContain('did not respond')
  })

  it('redacts a token the Control Plane quotes back in its own error', async () => {
    const { fetch } = recordingFetch({
      ok: false,
      status: 401,
      body: `{"detail":"token ${TOKEN} is expired"}`,
    })
    const outcome = await registerProduct(CONFIG, payload, {
      fetchImpl: fetch,
      env: { [TOKEN_VAR]: TOKEN },
    })

    expect(outcome.status).toBe('rejected')
    if (outcome.status !== 'rejected') return
    expect(outcome.detail).not.toContain(TOKEN)
  })

  it('redacts its own token even when the environment does not name it', async () => {
    // The redactor blanks values of sensibly-named environment variables. That
    // covered the token only by coincidence of naming: a caller passing a
    // narrower env left it in clear. The client knows the secret it is using,
    // so it redacts that value rather than trusting a variable name to exist.
    const { fetch } = recordingFetch({
      ok: false,
      status: 401,
      body: `{"detail":"token ${TOKEN} is expired"}`,
    })
    const outcome = await registerProduct(CONFIG, payload, { fetchImpl: fetch, env: {} })

    expect(outcome.status).toBe('rejected')
    if (outcome.status !== 'rejected') return
    expect(outcome.detail).not.toContain(TOKEN)
  })

  it('names the host but never the token when a request fails', async () => {
    const fetch: FetchLike = () => Promise.reject(new Error('boom'))
    const outcome = await registerProduct(CONFIG, payload, { fetchImpl: fetch })
    if (outcome.status !== 'unreachable') return
    expect(outcome.detail).toContain('control-plane.koras.io')
    expect(outcome.detail).not.toContain(TOKEN)
  })
})

// ── the step as a whole ──────────────────────────────────────────────────────

describe('the registration step', () => {
  const CONFIGURED = { [BASE_URL_VAR]: 'https://control-plane.koras.io', [TOKEN_VAR]: TOKEN }

  it('registers a provisioned product', async () => {
    const { fetch, calls } = recordingFetch({ ok: true, status: 201 })
    const report = await runRegistration(ctxFor('product', 'shop'), OUTPUTS, {
      skipRequested: false,
      provisioned: true,
      env: CONFIGURED,
      fetchImpl: fetch,
    })

    expect(report.kind).toBe('registered')
    expect(calls).toHaveLength(1)
  })

  it('emits zero registration calls for the Control Plane', async () => {
    const { fetch, calls } = recordingFetch({ ok: true, status: 201 })
    const report = await runRegistration(ctxFor('control-plane', 'cp'), OUTPUTS, {
      skipRequested: false,
      provisioned: true,
      env: CONFIGURED,
      fetchImpl: fetch,
    })

    expect(report.kind).toBe('skipped')
    if (report.kind !== 'skipped') return
    expect(report.reason).toBe('profile')
    expect(calls).toHaveLength(0)
  })

  it('sends nothing when --skip-registration was passed', async () => {
    const { fetch, calls } = recordingFetch({ ok: true, status: 201 })
    const report = await runRegistration(ctxFor('product', 'shop'), OUTPUTS, {
      skipRequested: true,
      provisioned: true,
      env: CONFIGURED,
      fetchImpl: fetch,
    })

    expect(report.kind).toBe('skipped')
    expect(calls).toHaveLength(0)
  })

  it('skips rather than fails when no Control Plane is configured yet', async () => {
    const { fetch, calls } = recordingFetch({ ok: true, status: 201 })
    const report = await runRegistration(ctxFor('product', 'shop'), OUTPUTS, {
      skipRequested: false,
      provisioned: true,
      env: {},
      fetchImpl: fetch,
    })

    expect(report.kind).toBe('skipped')
    if (report.kind !== 'skipped') return
    expect(report.reason).toBe('not-configured')
    expect(calls).toHaveLength(0)
  })

  it('fails rather than skips when a Control Plane is named but unauthorised', async () => {
    const report = await runRegistration(ctxFor('product', 'shop'), OUTPUTS, {
      skipRequested: false,
      provisioned: true,
      env: { [BASE_URL_VAR]: 'https://control-plane.koras.io' },
    })

    expect(report.kind).toBe('failed')
    if (report.kind !== 'failed') return
    expect(report.retryable).toBe(false)
  })

  it('marks an unreachable Control Plane retryable and a refusal not', async () => {
    const unreachable = await runRegistration(ctxFor('product', 'shop'), OUTPUTS, {
      skipRequested: false,
      provisioned: true,
      env: CONFIGURED,
      fetchImpl: () => Promise.reject(new Error('ECONNREFUSED')),
    })
    expect(unreachable.kind === 'failed' && unreachable.retryable).toBe(true)

    const { fetch } = recordingFetch({ ok: false, status: 422, body: 'nope' })
    const refused = await runRegistration(ctxFor('product', 'shop'), OUTPUTS, {
      skipRequested: false,
      provisioned: true,
      env: CONFIGURED,
      fetchImpl: fetch,
    })
    expect(refused.kind === 'failed' && refused.retryable).toBe(false)
  })

  it('registers nothing when nothing was provisioned', async () => {
    const { fetch, calls } = recordingFetch({ ok: true, status: 201 })
    const report = await runRegistration(ctxFor('product', 'shop'), undefined, {
      skipRequested: false,
      provisioned: false,
      env: CONFIGURED,
      fetchImpl: fetch,
    })

    expect(report.kind).toBe('skipped')
    if (report.kind !== 'skipped') return
    expect(report.reason).toBe('not-provisioned')
    expect(calls).toHaveLength(0)
  })
})
