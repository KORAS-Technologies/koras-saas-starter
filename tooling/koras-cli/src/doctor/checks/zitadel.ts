import { createSign, randomUUID } from 'node:crypto'
import type { DoctorCheck, DoctorContext, DoctorResult } from '../types.js'
import { request, requestJson, HttpError, safeHost } from '../http.js'
import { value } from '../env.js'

/**
 * One check per ZITADEL instance. Each environment is a separate instance with
 * its own domain and service account, so each is verified independently — a
 * working DEV credential says nothing about PROD.
 *
 * The credential is exercised end to end: the service-account JSON is parsed,
 * a short-lived assertion is signed in memory, exchanged for an access token
 * via the JWT-bearer grant, and used for one read (`/auth/v1/me`). Presence of
 * the JSON alone would not catch a rotated or revoked key.
 *
 * Nothing is written to disk, and no part of the credential — key, assertion,
 * or access token — is ever printed.
 */

export const ZITADEL_ENVIRONMENTS = ['DEV', 'TEST', 'STG', 'PROD'] as const
export type ZitadelEnvironment = (typeof ZITADEL_ENVIRONMENTS)[number]

interface ServiceAccountKey {
  keyId: string
  key: string
  userId: string
}

/** Tolerates a pasted https:// prefix or trailing slash, as the generator does. */
export function normalizeDomain(domain: string): string {
  return domain.replace(/^https?:\/\//, '').replace(/\/+$/, '')
}

export function parseServiceAccountKey(raw: string): ServiceAccountKey {
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    throw new Error('Service-account JSON could not be parsed.')
  }

  const key = parsed as Record<string, unknown>
  const missing = (['keyId', 'key', 'userId'] as const).filter(
    (field) => typeof key[field] !== 'string' || (key[field] as string).length === 0,
  )
  if (missing.length > 0) {
    throw new Error(`Service-account JSON is missing: ${missing.join(', ')}.`)
  }

  return {
    keyId: key.keyId as string,
    key: key.key as string,
    userId: key.userId as string,
  }
}

function base64url(input: Buffer | string): string {
  return Buffer.from(input).toString('base64url')
}

/** Signs a short-lived RS256 assertion. Never leaves this process. */
export function buildAssertion(account: ServiceAccountKey, audience: string, now: number): string {
  const header = { alg: 'RS256', typ: 'JWT', kid: account.keyId }
  const payload = {
    iss: account.userId,
    sub: account.userId,
    aud: audience,
    iat: now,
    exp: now + 300,
    jti: randomUUID(),
  }

  const signingInput = `${base64url(JSON.stringify(header))}.${base64url(JSON.stringify(payload))}`
  const signature = createSign('RSA-SHA256').update(signingInput).sign(account.key)
  return `${signingInput}.${base64url(signature)}`
}

export function makeZitadelCheck(environment: ZitadelEnvironment): DoctorCheck {
  return {
    label: `ZITADEL ${environment}`,
    run: (ctx) => checkZitadel(ctx, environment),
  }
}

export async function checkZitadel(
  ctx: DoctorContext,
  environment: ZitadelEnvironment,
): Promise<DoctorResult> {
  const domainVar = `ZITADEL_${environment}_DOMAIN`
  const keyVar = `ZITADEL_${environment}_SERVICE_ACCOUNT_KEY_JSON`

  const rawDomain = value(ctx.env, domainVar)
  const rawKey = value(ctx.env, keyVar)

  const missing = [rawDomain ? undefined : domainVar, rawKey ? undefined : keyVar].filter(Boolean)
  if (missing.length > 0) return { passed: false, error: `Not set: ${missing.join(', ')}.` }

  const domain = normalizeDomain(rawDomain as string)
  const base = `https://${domain}`

  let account: ServiceAccountKey
  try {
    account = parseServiceAccountKey(rawKey as string)
  } catch (err) {
    return { passed: false, error: `${(err as Error).message}\nCheck ${keyVar}.` }
  }

  // Reachability, and the issuer to use as the assertion audience.
  let issuer: string
  try {
    const discovery = await requestJson<{ issuer?: unknown }>(
      ctx.fetchImpl,
      `${base}/.well-known/openid-configuration`,
      { headers: { accept: 'application/json' } },
    )
    issuer = typeof discovery.issuer === 'string' ? discovery.issuer : base
  } catch (err) {
    if (err instanceof HttpError) {
      return {
        passed: false,
        error: `${domain} returned HTTP ${err.status} for OIDC discovery.\nCheck ${domainVar}.`,
      }
    }
    return { passed: false, error: `${domain} is not reachable.\nCheck ${domainVar}.` }
  }

  // JWT-bearer grant. Mints a short-lived read token; changes nothing.
  let accessToken: string
  try {
    const body = new URLSearchParams({
      grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
      scope: 'openid profile urn:zitadel:iam:org:project:id:zitadel:aud',
      assertion: buildAssertion(account, issuer, Math.floor(Date.now() / 1000)),
    }).toString()

    const token = await requestJson<{ access_token?: unknown }>(
      ctx.fetchImpl,
      `${base}/oauth/v2/token`,
      {
        method: 'POST',
        headers: {
          'content-type': 'application/x-www-form-urlencoded',
          accept: 'application/json',
        },
        body,
      },
    )

    if (typeof token.access_token !== 'string') {
      return { passed: false, error: `${domain} returned no access token.\nCheck ${keyVar}.` }
    }
    accessToken = token.access_token
  } catch (err) {
    if (err instanceof HttpError) {
      return {
        passed: false,
        error:
          `Authentication failed (HTTP ${err.status}).\n` + `Check ${domainVar} and ${keyVar}.`,
      }
    }
    // A malformed private key fails at sign time, before any request.
    return {
      passed: false,
      error: `Authentication failed: ${(err as Error).message}\nCheck ${keyVar}.`,
    }
  }

  // One read, to prove the token is usable and not merely issued.
  // GetMyUser on the Auth API — the least-privileged read a service account
  // can make, so this tests the credential rather than any granted role.
  try {
    await request(ctx.fetchImpl, `${base}/auth/v1/users/me`, {
      headers: { authorization: `Bearer ${accessToken}`, accept: 'application/json' },
    })
  } catch (err) {
    if (err instanceof HttpError) {
      // 401/403 is the credential; 404 is the endpoint. Reporting a missing
      // endpoint as a permissions problem sends the operator to the wrong
      // place entirely — which is what an earlier version of this check did.
      const cause =
        err.status === 401 || err.status === 403
          ? "Check the service account's permissions."
          : `${safeHost(base)} does not expose the Auth API at /auth/v1/users/me.`
      return {
        passed: false,
        error: `Authenticated, but the read request returned HTTP ${err.status}.\n${cause}`,
      }
    }
    throw err
  }

  return { passed: true }
}

export const zitadelChecks: DoctorCheck[] = ZITADEL_ENVIRONMENTS.map(makeZitadelCheck)
