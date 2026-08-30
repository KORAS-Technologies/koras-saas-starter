import { describe, it, expect } from 'vitest'
import { generateKeyPairSync, createVerify } from 'node:crypto'
import {
  audienceScope,
  buildAssertion,
  mintToken,
  parseServiceAccountKey,
  resolveBearer,
  type ServiceAccountKey,
} from '../src/registration/token.js'
import {
  resolveRegistrationConfig,
  BASE_URL_VAR,
  TOKEN_VAR,
  KEY_VAR,
  PROJECT_ID_VAR,
  INSTANCE_OVERRIDE_VAR,
  deriveInstance,
} from '../src/registration/config.js'
import type { FetchLike } from '../src/registration/client.js'

/**
 * F2a: the generator holds a key and mints a token per call.
 *
 * The defect this covers is not a crash. `KORAS_CONTROL_PLANE_TOKEN` held a
 * finished bearer whose measured lifetime is 43,199 seconds, so a value stored
 * today stopped working tomorrow — and failed as a misconfiguration, which is
 * the right failure arriving every single day.
 *
 * Everything here runs against a generated key pair and an injected fetch. No
 * network call, no real ZITADEL, and no credential in the repository.
 */

const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })

const KEY: ServiceAccountKey = {
  type: 'serviceaccount',
  keyId: 'key-1',
  key: privateKey.export({ type: 'pkcs8', format: 'pem' }).toString(),
  userId: '388065508789893846',
}

const INSTANCE = 'https://auth-dev.korastechnologies.com'
const PROJECT_ID = '386896303700837805'

/** A JWT-shaped token. Only the dot count matters to the code under test. */
const JWT = 'header.payload.signature'

function decodeSegment(segment: string): Record<string, unknown> {
  return JSON.parse(Buffer.from(segment, 'base64url').toString('utf8')) as Record<string, unknown>
}

function exchange(response: {
  ok?: boolean
  status?: number
  body?: string
}): { fetch: FetchLike; calls: Array<{ url: string; body: string }> } {
  const calls: Array<{ url: string; body: string }> = []
  const fetch: FetchLike = (url, init) => {
    calls.push({ url, body: String(init?.body ?? '') })
    return Promise.resolve({
      ok: response.ok ?? true,
      status: response.status ?? 200,
      text: () => Promise.resolve(response.body ?? JSON.stringify({ access_token: JWT, expires_in: 43199 })),
    })
  }
  return { fetch, calls }
}

// ── the key itself ───────────────────────────────────────────────────────────

describe('reading a service-account key', () => {
  it('accepts the shape ZITADEL downloads', () => {
    const parsed = parseServiceAccountKey(JSON.stringify(KEY))
    expect(parsed).toMatchObject({ type: 'serviceaccount', userId: KEY.userId })
  })

  it.each([
    ['not JSON at all', 'this is not json', 'is not valid JSON.'],
    ['a JSON array', '[]', 'is not a JSON object.'],
    ['some other key type', '{"type":"application"}', 'does not have type "serviceaccount".'],
    [
      'a key missing its user',
      JSON.stringify({ type: 'serviceaccount', keyId: 'k', key: 'pem' }),
      'is missing userId.',
    ],
  ])('refuses %s', (_label, raw, detail) => {
    expect(parseServiceAccountKey(raw)).toEqual({ detail })
  })

  /**
   * The one test here that is about disclosure rather than correctness. A
   * malformed key is exactly when an operator pastes the error somewhere, and
   * the private key must not be in it.
   */
  it('never repeats the key material back in a failure', () => {
    const secret = 'SUPER-SECRET-PEM-MATERIAL'
    const parsed = parseServiceAccountKey(JSON.stringify({ type: 'nope', key: secret }))
    expect(JSON.stringify(parsed)).not.toContain(secret)
  })
})

// ── the assertion ────────────────────────────────────────────────────────────

describe('the assertion ZITADEL exchanges', () => {
  it('is signed by the key, and verifies against its public half', () => {
    const assertion = buildAssertion(KEY, INSTANCE, 1_700_000_000)
    const [header, payload, signature] = assertion.split('.')

    const verifier = createVerify('RSA-SHA256')
    verifier.update(`${header}.${payload}`)
    expect(verifier.verify(publicKey, Buffer.from(signature, 'base64url'))).toBe(true)
  })

  it('names the key id in the header, so ZITADEL knows which key to check', () => {
    const [header] = buildAssertion(KEY, INSTANCE, 1_700_000_000).split('.')
    expect(decodeSegment(header)).toMatchObject({ alg: 'RS256', kid: KEY.keyId })
  })

  /**
   * The audience is the *instance*, not the Control Plane. This assertion is
   * addressed to ZITADEL; only the token that comes back is addressed onward.
   * Getting it backwards is a refused grant, and it is an easy thing to
   * "correct" wrongly while reading the file.
   */
  it('is addressed to ZITADEL rather than to the Control Plane', () => {
    const [, payload] = buildAssertion(KEY, INSTANCE, 1_700_000_000).split('.')
    expect(decodeSegment(payload)).toMatchObject({
      iss: KEY.userId,
      sub: KEY.userId,
      aud: INSTANCE,
      iat: 1_700_000_000,
    })
  })

  it('expires, so a captured assertion is not a standing credential', () => {
    const [, payload] = buildAssertion(KEY, INSTANCE, 1_700_000_000).split('.')
    const claims = decodeSegment(payload) as { iat: number; exp: number }
    expect(claims.exp).toBeGreaterThan(claims.iat)
    expect(claims.exp - claims.iat).toBeLessThanOrEqual(600)
  })
})

// ── the exchange ─────────────────────────────────────────────────────────────

describe('exchanging the assertion for a token', () => {
  it('asks for the project audience, or the Control Plane answers 401', async () => {
    const { fetch, calls } = exchange({})
    const outcome = await mintToken(
      { key: KEY, instance: INSTANCE, projectId: PROJECT_ID },
      { fetchImpl: fetch },
    )

    expect(outcome).toMatchObject({ ok: true, token: JWT, expiresIn: 43199 })
    expect(calls[0].url).toBe(`${INSTANCE}/oauth/v2/token`)

    const sent = new URLSearchParams(calls[0].body)
    expect(sent.get('grant_type')).toBe('urn:ietf:params:oauth:grant-type:jwt-bearer')
    expect(sent.get('scope')).toBe(audienceScope(PROJECT_ID))
    expect(sent.get('assertion')).toBeTruthy()
  })

  /**
   * The finding from A.2 that cost the most to discover. A service account on
   * ZITADEL's default access token type issues an *opaque* token: the grant
   * succeeds, and every registration then fails 401 in a way that reads
   * exactly like an expired token. Caught here, while the cause is still
   * visible.
   */
  it('refuses an opaque token rather than presenting one the Control Plane cannot verify', async () => {
    const { fetch } = exchange({ body: JSON.stringify({ access_token: 'opaque-blob', expires_in: 43199 }) })
    const outcome = await mintToken(
      { key: KEY, instance: INSTANCE, projectId: PROJECT_ID },
      { fetchImpl: fetch },
    )

    expect(outcome).toMatchObject({ ok: false, retryable: false })
    if (outcome.ok) return
    expect(outcome.detail).toContain('opaque')
    expect(outcome.detail).toContain(KEY.userId)
  })

  it('treats a refused grant as permanent and a broken ZITADEL as retryable', async () => {
    const refused = await mintToken(
      { key: KEY, instance: INSTANCE, projectId: PROJECT_ID },
      { fetchImpl: exchange({ ok: false, status: 400 }).fetch },
    )
    expect(refused).toMatchObject({ ok: false, retryable: false })

    const broken = await mintToken(
      { key: KEY, instance: INSTANCE, projectId: PROJECT_ID },
      { fetchImpl: exchange({ ok: false, status: 503 }).fetch },
    )
    expect(broken).toMatchObject({ ok: false, retryable: true })
  })

  /**
   * The request body carried a signed assertion. A server that echoes its
   * input would echo that, so the refusal never quotes the response.
   */
  it('does not quote the exchange response, which may echo the assertion', async () => {
    const outcome = await mintToken(
      { key: KEY, instance: INSTANCE, projectId: PROJECT_ID },
      { fetchImpl: exchange({ ok: false, status: 400, body: 'assertion=SENSITIVE-ECHO' }).fetch },
    )
    expect(outcome.ok).toBe(false)
    if (outcome.ok) return
    expect(outcome.detail).not.toContain('SENSITIVE-ECHO')
  })

  it('reports an unusable private key without throwing', async () => {
    const outcome = await mintToken(
      { key: { ...KEY, key: 'not-a-pem' }, instance: INSTANCE, projectId: PROJECT_ID },
      { fetchImpl: exchange({}).fetch },
    )
    expect(outcome).toMatchObject({ ok: false, retryable: false })
    if (outcome.ok) return
    expect(outcome.detail).toContain('not a usable RSA private key')
  })

  it('never throws when the instance cannot be reached', async () => {
    const outcome = await mintToken(
      { key: KEY, instance: INSTANCE, projectId: PROJECT_ID },
      { fetchImpl: () => Promise.reject(new Error('ECONNREFUSED')) },
    )
    expect(outcome).toMatchObject({ ok: false, retryable: true })
  })
})

// ── choosing a credential ────────────────────────────────────────────────────

describe('choosing between a key and a stored token', () => {
  const endpoint = '/api/platform/v1/products'
  const baseUrl = 'https://koras-control-plane-api-dev.fly.dev'
  const withKey = {
    [BASE_URL_VAR]: baseUrl,
    [KEY_VAR]: JSON.stringify(KEY),
    [PROJECT_ID_VAR]: PROJECT_ID,
    ZITADEL_DEV_DOMAIN: 'auth-dev.korastechnologies.com',
  }

  it('prefers the key, because a stored token goes stale and a key does not', () => {
    const result = resolveRegistrationConfig({
      endpoint,
      env: { ...withKey, [TOKEN_VAR]: 'a-stored-token' },
    })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.config.credential.kind).toBe('key')
  })

  it('still accepts a stored token when no key is configured', () => {
    const result = resolveRegistrationConfig({
      endpoint,
      env: { [BASE_URL_VAR]: baseUrl, [TOKEN_VAR]: 'a-stored-token' },
    })
    expect(result.ok && result.config.credential).toEqual({
      kind: 'token',
      token: 'a-stored-token',
    })
  })

  /**
   * A damaged key must not fall through to whatever token is also lying about.
   * Falling back would mean an operator who stored a key, then broke it, went
   * on using an expiring token they believed they had replaced.
   */
  it('refuses a malformed key rather than falling back to the token', () => {
    const result = resolveRegistrationConfig({
      endpoint,
      env: { ...withKey, [KEY_VAR]: '{"type":"application"}', [TOKEN_VAR]: 'a-stored-token' },
    })
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.problem.kind).toBe('bad-key')
  })

  it('refuses a key with no project id, which would mint a token the Control Plane 401s', () => {
    const env = { ...withKey } as Record<string, string>
    delete env[PROJECT_ID_VAR]
    const result = resolveRegistrationConfig({ endpoint, env })
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.problem.kind).toBe('bad-key')
    expect(result.problem.detail).toContain(PROJECT_ID_VAR)
  })

  it('names both credentials when neither is set', () => {
    const result = resolveRegistrationConfig({ endpoint, env: { [BASE_URL_VAR]: baseUrl } })
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.problem.kind).toBe('no-token')
    expect(result.problem.detail).toContain(KEY_VAR)
  })
})

// ── deriving the instance ────────────────────────────────────────────────────

describe('deriving which ZITADEL minted the registrar', () => {
  /**
   * Derived from the Control Plane URL rather than answered separately,
   * because a separately-answered instance can disagree with the Control Plane
   * it belongs to — and that mismatch is a 401 indistinguishable from an
   * expired token.
   */
  it.each([
    ['dev', 'https://koras-control-plane-api-dev.fly.dev'],
    ['test', 'https://koras-control-plane-api-test.fly.dev'],
    ['stg', 'https://koras-control-plane-api-stg.fly.dev'],
    ['prod', 'https://koras-control-plane-api-prod.fly.dev'],
  ])('reads %s out of the Control Plane hostname', (env, url) => {
    const result = deriveInstance(url, { [`ZITADEL_${env.toUpperCase()}_DOMAIN`]: `auth-${env}.example.com` })
    expect(result).toEqual({ ok: true, instance: `https://auth-${env}.example.com` })
  })

  /**
   * `ZITADEL_<ENV>_DOMAIN` holds a bare hostname in this estate. The scheme is
   * added rather than assumed: the 2026-08-30 teardown's first ZITADEL delete
   * went out as http and was answered 301, and reading that as success would
   * have left four projects standing.
   */
  it('adds the scheme a bare hostname does not carry', () => {
    expect(deriveInstance('https://x-api-dev.fly.dev', { ZITADEL_DEV_DOMAIN: 'auth.example.com' }))
      .toEqual({ ok: true, instance: 'https://auth.example.com' })
  })

  it('leaves an explicit scheme alone, and trims a trailing slash', () => {
    expect(deriveInstance('https://x-api-dev.fly.dev', { ZITADEL_DEV_DOMAIN: 'https://auth.example.com/' }))
      .toEqual({ ok: true, instance: 'https://auth.example.com' })
  })

  it('accepts an override for a Control Plane on a custom hostname', () => {
    const result = deriveInstance('https://cp.internal.example', {
      [INSTANCE_OVERRIDE_VAR]: 'auth.example.com',
    })
    expect(result).toEqual({ ok: true, instance: 'https://auth.example.com' })
  })

  it('refuses to guess when the hostname encodes no environment', () => {
    const result = deriveInstance('https://cp.internal.example', {})
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.detail).toContain(INSTANCE_OVERRIDE_VAR)
  })

  it('says which variable is missing rather than guessing an instance', () => {
    const result = deriveInstance('https://x-api-stg.fly.dev', {})
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.detail).toContain('ZITADEL_STG_DOMAIN')
  })
})

// ── the whole resolution ─────────────────────────────────────────────────────

describe('resolving a credential source into a bearer', () => {
  it('passes a stored token through unchanged', async () => {
    const resolved = await resolveBearer({
      baseUrl: 'https://cp.example',
      endpoint: '/e',
      credential: { kind: 'token', token: 'stored' },
    })
    expect(resolved).toMatchObject({ ok: true, minted: false })
    if (!resolved.ok) return
    expect(resolved.config.token).toBe('stored')
  })

  it('mints from a key, and says that it did', async () => {
    const resolved = await resolveBearer(
      {
        baseUrl: 'https://cp.example',
        endpoint: '/e',
        credential: { key: KEY, instance: INSTANCE, kind: 'key', projectId: PROJECT_ID },
      },
      { fetchImpl: exchange({}).fetch },
    )
    expect(resolved).toMatchObject({ ok: true, minted: true, expiresIn: 43199 })
    if (!resolved.ok) return
    expect(resolved.config.token).toBe(JWT)
  })

  it('reports a failed mint without throwing, so a provisioned estate stands', async () => {
    const resolved = await resolveBearer(
      {
        baseUrl: 'https://cp.example',
        endpoint: '/e',
        credential: { key: KEY, instance: INSTANCE, kind: 'key', projectId: PROJECT_ID },
      },
      { fetchImpl: exchange({ ok: false, status: 401 }).fetch },
    )
    expect(resolved).toMatchObject({ ok: false, retryable: false })
  })
})
