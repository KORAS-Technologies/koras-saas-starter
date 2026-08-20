import type { DoctorCheck, DoctorContext, DoctorResult } from '../types.js'
import { requestJson, HttpError } from '../http.js'
import { require } from '../env.js'

/**
 * Lists the account's Redis databases — a read-only GET that both proves the
 * credential pair works and confirms the account exists.
 *
 * Upstash authenticates the management API with HTTP Basic using the account
 * email as the user and the management API key as the password. Both are
 * required arguments of the Terraform provider, with no environment fallback,
 * so a missing one is not a degraded run: `terraform plan` cannot be produced
 * at all.
 */
export async function checkUpstash(ctx: DoctorContext): Promise<DoctorResult> {
  const needed = require(ctx.env, ['TF_VAR_upstash_email', 'TF_VAR_upstash_api_key'], {
    TF_VAR_upstash_email: 'TF_VAR_UPSTASH_EMAIL',
    TF_VAR_upstash_api_key: 'TF_VAR_UPSTASH_API_KEY',
  })
  if (!needed.ok) return { passed: false, error: `Not set: ${needed.missing.join(', ')}.` }

  const basic = Buffer.from(
    `${needed.values.TF_VAR_upstash_email}:${needed.values.TF_VAR_upstash_api_key}`,
  ).toString('base64')

  try {
    await requestJson<unknown>(ctx.fetchImpl, 'https://api.upstash.com/v2/redis/databases', {
      method: 'GET',
      headers: { authorization: `Basic ${basic}`, accept: 'application/json' },
    })
  } catch (err) {
    if (err instanceof HttpError && (err.status === 401 || err.status === 403)) {
      return {
        passed: false,
        error: 'Upstash rejected the credentials. Check TF_VAR_UPSTASH_EMAIL and TF_VAR_UPSTASH_API_KEY.',
      }
    }
    throw err
  }

  return { passed: true }
}

export const upstashCheck: DoctorCheck = { label: 'Upstash', run: checkUpstash }
