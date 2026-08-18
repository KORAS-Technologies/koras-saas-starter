import type { DoctorCheck, DoctorContext, DoctorResult } from '../types.js'
import { requestJson, HttpError } from '../http.js'
import { require } from '../env.js'

interface CloudflareEnvelope<T> {
  success?: unknown
  result?: T
  errors?: Array<{ message?: unknown }>
}

/**
 * Reads the configured zone and confirms it really is the primary domain — a
 * valid token pointed at the wrong zone is the failure that would otherwise
 * surface as DNS appearing in someone else's domain during a bootstrap.
 *
 * Reads only. No DNS, SSL, Workers, R2, Pages, WAF, zone, or domain changes.
 */
export async function checkCloudflare(ctx: DoctorContext): Promise<DoctorResult> {
  const needed = require(
    ctx.env,
    ['CLOUDFLARE_API_TOKEN', 'TF_VAR_cloudflare_zone_id', 'TF_VAR_primary_domain'],
    {
      TF_VAR_cloudflare_zone_id: 'TF_VAR_CLOUDFLARE_ZONE_ID',
      TF_VAR_primary_domain: 'TF_VAR_PRIMARY_DOMAIN',
    },
  )
  if (!needed.ok) return { passed: false, error: `Not set: ${needed.missing.join(', ')}.` }

  const headers = {
    authorization: `Bearer ${needed.values.CLOUDFLARE_API_TOKEN}`,
    accept: 'application/json',
  }

  const zoneId = needed.values.TF_VAR_cloudflare_zone_id
  const domain = needed.values.TF_VAR_primary_domain

  // Reading the zone is the primary check, because it is what Terraform
  // actually does. `/user/tokens/verify` is not a substitute: a token scoped
  // to a single zone can be perfectly good yet unable to call it, so treating
  // verify as the gate would fail a working credential.
  let zone: CloudflareEnvelope<{ name?: unknown; status?: unknown }>
  try {
    zone = await requestJson(
      ctx.fetchImpl,
      `https://api.cloudflare.com/client/v4/zones/${encodeURIComponent(zoneId)}`,
      { headers },
    )
  } catch (err) {
    if (err instanceof HttpError) {
      // Ask Cloudflare why. Its own message ("Invalid API Token",
      // "Authentication error") distinguishes a bad token from a token that
      // simply cannot see this zone — which "was rejected" never did.
      const detail = describe(err.body) ?? `HTTP ${err.status}`
      return {
        passed: false,
        error:
          `Zone "${zoneId}" is not readable: ${detail}\n` +
          'Check CLOUDFLARE_API_TOKEN, TF_VAR_CLOUDFLARE_ZONE_ID, and that the\n' +
          'token grants Zone:Read (and DNS:Edit for provisioning) on that zone.',
      }
    }
    throw err
  }

  if (zone.success !== true) {
    return {
      passed: false,
      error: `Zone "${zoneId}" is not readable: ${describe(JSON.stringify(zone)) ?? 'unknown error'}`,
    }
  }

  const name = zone.result?.name
  if (typeof name !== 'string') {
    return { passed: false, error: `Zone "${zoneId}" did not report a domain name.` }
  }

  // The zone may legitimately be the apex of a subdomain of the primary domain.
  if (name !== domain && !domain.endsWith(`.${name}`)) {
    return {
      passed: false,
      error:
        `Zone "${zoneId}" is "${name}", which does not match TF_VAR_PRIMARY_DOMAIN "${domain}".`,
    }
  }

  return { passed: true }
}

/**
 * Cloudflare's own error text, e.g. `Invalid API Token (10000)`.
 *
 * Its errors are structured and non-sensitive — a code and a message, never a
 * credential — so surfacing them turns an unactionable "was rejected" into
 * something an operator can fix. The redactor still sees this on the way out.
 */
export function describe(body: string): string | undefined {
  try {
    const parsed = JSON.parse(body) as CloudflareEnvelope<unknown>
    const messages = (parsed.errors ?? [])
      .map((e) => {
        const code = (e as { code?: unknown }).code
        return typeof e.message === 'string'
          ? typeof code === 'number'
            ? `${e.message} (${code})`
            : e.message
          : undefined
      })
      .filter((m): m is string => m !== undefined)
    return messages.length > 0 ? messages.join('; ') : undefined
  } catch {
    return undefined
  }
}

export const cloudflareCheck: DoctorCheck = { label: 'Cloudflare', run: checkCloudflare }
