import type { DoctorCheck, DoctorContext, DoctorResult } from '../types.js'
import { requestJson, HttpError } from '../http.js'
import { require } from '../env.js'

interface FlyResponse {
  data?: { organizations?: { nodes?: Array<{ slug?: unknown }> } }
  errors?: Array<{ message?: unknown }>
}

/**
 * A single GraphQL *query* listing the organizations the token can see. The
 * Fly CLI is never invoked, so there is no path to `deploy`, `launch`, or
 * `apps create`.
 */
export async function checkFly(ctx: DoctorContext): Promise<DoctorResult> {
  const needed = require(ctx.env, ['FLY_API_TOKEN', 'TF_VAR_fly_org_slug'], {
    TF_VAR_fly_org_slug: 'TF_VAR_FLY_ORG_SLUG',
  })
  if (!needed.ok) return { passed: false, error: `Not set: ${needed.missing.join(', ')}.` }

  let response: FlyResponse
  try {
    response = await requestJson<FlyResponse>(ctx.fetchImpl, 'https://api.fly.io/graphql', {
      method: 'POST',
      headers: {
        authorization: `Bearer ${needed.values.FLY_API_TOKEN}`,
        'content-type': 'application/json',
        accept: 'application/json',
      },
      body: JSON.stringify({ query: 'query { organizations { nodes { slug } } }' }),
    })
  } catch (err) {
    if (err instanceof HttpError && (err.status === 401 || err.status === 403)) {
      return { passed: false, error: 'FLY_API_TOKEN was rejected.' }
    }
    throw err
  }

  // GraphQL reports authentication failures as a 200 with an errors array.
  if (response.errors && response.errors.length > 0) {
    return { passed: false, error: 'Fly.io rejected the request. Check FLY_API_TOKEN.' }
  }

  const slug = needed.values.TF_VAR_fly_org_slug
  const visible = (response.data?.organizations?.nodes ?? [])
    .map((node) => node.slug)
    .filter((s): s is string => typeof s === 'string')

  if (!visible.includes(slug)) {
    return {
      passed: false,
      error:
        `Organization "${slug}" is not visible to this token ` +
        `(${visible.length} organization(s) available).\n` +
        'Check TF_VAR_FLY_ORG_SLUG.',
    }
  }

  return { passed: true }
}

export const flyCheck: DoctorCheck = { label: 'Fly.io', run: checkFly }
