import { createSign } from 'node:crypto'
import type { FetchLike } from './client.js'
import type { CredentialSource, RegistrationConfig, RegistrationSource } from './config.js'

/**
 * Turning a stored credential into the bearer registration actually presents.
 *
 * The credential this has to produce is a ZITADEL access token for the
 * `registrar` service account, and the exchange returns a lifetime of 43,199
 * seconds -- measured against the dev instance on 2026-08-28. A finished token
 * stored in Doppler therefore stops working twelve hours after somebody put it
 * there, and fails as a misconfiguration: loudly, correctly, and daily.
 *
 * So the stored thing should be the *key*, and the token should be minted per
 * call. That is what the ZITADEL Terraform provider already does with the
 * `ZITADEL_DEV_SERVICE_ACCOUNT_KEY_JSON` family; registration was the one
 * caller that never adopted it.
 *
 * The signing here is the same exchange `scripts/mint-control-plane-token.mjs`
 * performs, moved where the generator can reach it. That script stays as the
 * operator's diagnostic -- it probes the Control Plane and names the cause of a
 * refusal -- but it is no longer the only thing that can mint, which is what
 * made a twelve-hour credential into standing configuration.
 *
 * Nothing in this file logs a key, an assertion, or a token.
 */

/** A ZITADEL service-account key, as downloaded from the console. */
export interface ServiceAccountKey {
  type: string
  keyId: string
  key: string
  userId: string
}

export interface KeyProblem {
  detail: string
}

export function isKeyProblem(value: ServiceAccountKey | KeyProblem): value is KeyProblem {
  return 'detail' in value
}

/**
 * Validate the JSON blob without ever putting its contents in the result.
 *
 * Every failure message here describes the *shape* that was wrong. A message
 * quoting the offending value would put private key material into an operator's
 * terminal the one time the key is malformed -- which is exactly when somebody
 * is most likely to paste the output into an issue.
 */
export function parseServiceAccountKey(raw: string): ServiceAccountKey | KeyProblem {
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return { detail: 'is not valid JSON.' }
  }

  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { detail: 'is not a JSON object.' }
  }

  const candidate = parsed as Partial<ServiceAccountKey>

  if (candidate.type !== 'serviceaccount') {
    return { detail: 'does not have type "serviceaccount".' }
  }

  const missing = (['keyId', 'key', 'userId'] as const).filter((field) => {
    const value = candidate[field]
    return typeof value !== 'string' || value.trim() === ''
  })

  if (missing.length > 0) {
    return { detail: `is missing ${missing.join(', ')}.` }
  }

  return {
    type: candidate.type,
    keyId: candidate.keyId as string,
    key: candidate.key as string,
    userId: candidate.userId as string,
  }
}

function base64url(input: Buffer | string): string {
  return Buffer.from(input)
    .toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

/**
 * How long the assertion itself is valid.
 *
 * It is spent immediately; this is slack for clock skew between this machine
 * and ZITADEL, not a lifetime anything relies on.
 */
const ASSERTION_LIFETIME_SECONDS = 300

/**
 * The signed assertion ZITADEL exchanges for a token.
 *
 * Issuer and subject are the service user. The audience is the ZITADEL
 * instance, *not* the Control Plane: this assertion is addressed to ZITADEL,
 * and only the token that comes back is addressed to the Control Plane. Getting
 * that backwards produces a refused grant rather than a 401, which is at least
 * a legible failure.
 */
export function buildAssertion(
  key: ServiceAccountKey,
  instance: string,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): string {
  const signingInput = [
    base64url(JSON.stringify({ alg: 'RS256', typ: 'JWT', kid: key.keyId })),
    base64url(
      JSON.stringify({
        iss: key.userId,
        sub: key.userId,
        aud: instance,
        iat: nowSeconds,
        exp: nowSeconds + ASSERTION_LIFETIME_SECONDS,
      }),
    ),
  ].join('.')

  const signer = createSign('RSA-SHA256')
  signer.update(signingInput)
  return `${signingInput}.${base64url(signer.sign(key.key))}`
}

/**
 * The reserved scope that puts a project into the token's audience.
 *
 * Not implicit: ZITADEL includes a project only when asked, and the Control
 * Plane accepts a token addressed to its own project or client id and nothing
 * else. Omitting this yields a perfectly valid token that every registration
 * then rejects with 401.
 */
export function audienceScope(projectId: string): string {
  return `openid urn:zitadel:iam:org:project:id:${projectId}:aud`
}

export type MintOutcome =
  | { ok: true; token: string; expiresIn: number }
  /** `retryable` separates a transport failure from a credential that will never work. */
  | { ok: false; detail: string; retryable: boolean }

export interface MintOptions {
  fetchImpl?: FetchLike
  timeoutMs?: number
  nowSeconds?: number
}

export const DEFAULT_MINT_TIMEOUT_MS = 15_000

/**
 * Exchange the assertion for an access token.
 *
 * Never throws, for the same reason the registration client never throws: this
 * runs after `terraform apply` has created real infrastructure, and a credential
 * problem is not a reason to unwind an estate that succeeded.
 */
export async function mintToken(
  source: { key: ServiceAccountKey; instance: string; projectId: string },
  options: MintOptions = {},
): Promise<MintOutcome> {
  const fetchImpl = options.fetchImpl ?? (globalThis.fetch as unknown as FetchLike)
  if (typeof fetchImpl !== 'function') {
    return { ok: false, retryable: false, detail: 'No fetch implementation is available.' }
  }

  let assertion: string
  try {
    assertion = buildAssertion(source.key, source.instance, options.nowSeconds)
  } catch (err) {
    // A signing failure is the private key being unusable -- wrong format, or
    // not a key at all. Reported by error class rather than quoted, because
    // OpenSSL error strings have been known to echo the input they choked on.
    return {
      ok: false,
      retryable: false,
      detail:
        'The service-account key is present but could not sign an assertion; it is not a ' +
        `usable RSA private key (${err instanceof Error ? err.name : 'unknown error'}).`,
    }
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? DEFAULT_MINT_TIMEOUT_MS)
  timer.unref?.()

  let response: Awaited<ReturnType<FetchLike>>
  try {
    response = await fetchImpl(`${source.instance}/oauth/v2/token`, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
        assertion,
        scope: audienceScope(source.projectId),
      }).toString(),
      signal: controller.signal,
    })
  } catch (err) {
    const aborted = controller.signal.aborted
    return {
      ok: false,
      retryable: true,
      detail: aborted
        ? `${source.instance} did not answer the token exchange in time.`
        : `${source.instance} could not be reached for the token exchange: ${
            err instanceof Error ? err.message : String(err)
          }`,
    }
  } finally {
    clearTimeout(timer)
  }

  if (!response.ok) {
    // The response body is deliberately not quoted. A refused grant answers
    // with an OAuth error object, but this is the one exchange whose request
    // body carried a signed assertion, and a server that echoes its input
    // would echo that.
    return {
      ok: false,
      // 5xx is ZITADEL failing rather than the credential being wrong.
      retryable: response.status >= 500,
      detail:
        `${source.instance} refused the token exchange (HTTP ${response.status}). ` +
        'Check that the key belongs to that instance and has not been revoked.',
    }
  }

  let body: { access_token?: unknown; expires_in?: unknown }
  try {
    body = JSON.parse(await response.text()) as typeof body
  } catch {
    return {
      ok: false,
      retryable: true,
      detail: `${source.instance} returned a token response that is not JSON.`,
    }
  }

  const token = typeof body.access_token === 'string' ? body.access_token : ''
  if (token === '') {
    return {
      ok: false,
      retryable: false,
      detail: `${source.instance} returned no access token in an otherwise successful exchange.`,
    }
  }

  // A service account left on ZITADEL's default access token type issues an
  // *opaque* token. The Control Plane verifies against a JWKS key set, so it
  // cannot verify one at all: the grant succeeds and every registration then
  // fails with 401, which reads exactly like an expired token. Caught here,
  // where the cause is still visible and can be named.
  if (token.split('.').length !== 3) {
    return {
      ok: false,
      retryable: false,
      detail:
        `${source.instance} returned an opaque token, which the Control Plane cannot verify. ` +
        `Set the access token type of service user ${source.key.userId} to JWT.`,
    }
  }

  const expiresIn = typeof body.expires_in === 'number' ? body.expires_in : 0
  return { ok: true, token, expiresIn }
}

export type BearerResolution =
  | { ok: true; config: RegistrationConfig; minted: boolean; expiresIn?: number }
  | { ok: false; detail: string; retryable: boolean }

/**
 * The credential source resolved into a config the client can post with.
 *
 * A stored token is used as it stands; a key is exchanged for one. Which of the
 * two is preferred is decided in `config.ts`, where both are read.
 */
export async function resolveBearer(
  source: RegistrationSource,
  options: MintOptions = {},
): Promise<BearerResolution> {
  const credential: CredentialSource = source.credential

  if (credential.kind === 'token') {
    return {
      ok: true,
      minted: false,
      config: { baseUrl: source.baseUrl, endpoint: source.endpoint, token: credential.token },
    }
  }

  const outcome = await mintToken(credential, options)
  if (!outcome.ok) return { ok: false, detail: outcome.detail, retryable: outcome.retryable }

  return {
    ok: true,
    minted: true,
    expiresIn: outcome.expiresIn,
    config: { baseUrl: source.baseUrl, endpoint: source.endpoint, token: outcome.token },
  }
}
