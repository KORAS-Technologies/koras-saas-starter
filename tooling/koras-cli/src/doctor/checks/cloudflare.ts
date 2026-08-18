import type { DoctorCheck, DoctorContext, DoctorResult } from '../types.js'
import { requestJson, HttpError } from '../http.js'
import { require } from '../env.js'

interface CloudflareEnvelope<T> {
  success?: unknown
  result?: T
  errors?: Array<{ message?: unknown }>
}

/**
 * Verifies the token, reads the configured zone, and confirms the zone really
 * is the primary domain — a valid token pointed at the wrong zone is the
 * failure that would otherwise surface as DNS appearing in someone else's
 * domain during a bootstrap.
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

  try {
    const verify = await requestJson<CloudflareEnvelope<{ status?: unknown }>>(
      ctx.fetchImpl,
      'https://api.cloudflare.com/client/v4/user/tokens/verify',
      { headers },
    )
    if (verify.success !== true) {
      return { passed: false, error: 'CLOUDFLARE_API_TOKEN is not valid.' }
    }
    if (verify.result?.status !== undefined && verify.result.status !== 'active') {
      return {
        passed: false,
        error: `CLOUDFLARE_API_TOKEN is "${String(verify.result.status)}", not active.`,
      }
    }
  } catch (err) {
    if (err instanceof HttpError && (err.status === 401 || err.status === 403)) {
      return { passed: false, error: 'CLOUDFLARE_API_TOKEN was rejected.' }
    }
    throw err
  }

  const zoneId = needed.values.TF_VAR_cloudflare_zone_id
  const domain = needed.values.TF_VAR_primary_domain

  let zone: CloudflareEnvelope<{ name?: unknown; status?: unknown }>
  try {
    zone = await requestJson(
      ctx.fetchImpl,
      `https://api.cloudflare.com/client/v4/zones/${encodeURIComponent(zoneId)}`,
      { headers },
    )
  } catch (err) {
    if (err instanceof HttpError) {
      return {
        passed: false,
        error:
          `Zone "${zoneId}" is not accessible (HTTP ${err.status}).\n` +
          'Check TF_VAR_CLOUDFLARE_ZONE_ID and the token scope.',
      }
    }
    throw err
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

export const cloudflareCheck: DoctorCheck = { label: 'Cloudflare', run: checkCloudflare }
