import type { DoctorCheck, DoctorContext, DoctorResult } from '../types.js'
import { requestJson, HttpError } from '../http.js'
import { require, value } from '../env.js'

const ENVIRONMENTS = ['DEV', 'TEST', 'STG', 'PROD'] as const

interface SupabaseOrganization {
  id?: unknown
  name?: unknown
}

/**
 * Confirms the token authenticates, the configured organization is among the
 * ones it can see, and a database password exists for all four environments.
 *
 * Passwords are only tested for presence — never read, compared, or printed.
 */
export async function checkSupabase(ctx: DoctorContext): Promise<DoctorResult> {
  const needed = require(ctx.env, ['SUPABASE_ACCESS_TOKEN', 'TF_VAR_supabase_org_id'], {
    TF_VAR_supabase_org_id: 'TF_VAR_SUPABASE_ORG_ID',
  })
  if (!needed.ok) return { passed: false, error: `Not set: ${needed.missing.join(', ')}.` }

  const missingPasswords = ENVIRONMENTS.map((e) => `SUPABASE_DB_PASSWORD_${e}`).filter(
    (name) => value(ctx.env, name) === undefined,
  )
  if (missingPasswords.length > 0) {
    return { passed: false, error: `Not set: ${missingPasswords.join(', ')}.` }
  }

  const orgId = needed.values.TF_VAR_supabase_org_id

  let organizations: SupabaseOrganization[]
  try {
    organizations = await requestJson<SupabaseOrganization[]>(
      ctx.fetchImpl,
      'https://api.supabase.com/v1/organizations',
      {
        headers: {
          authorization: `Bearer ${needed.values.SUPABASE_ACCESS_TOKEN}`,
          accept: 'application/json',
        },
      },
    )
  } catch (err) {
    if (err instanceof HttpError && (err.status === 401 || err.status === 403)) {
      return { passed: false, error: 'SUPABASE_ACCESS_TOKEN was rejected.' }
    }
    throw err
  }

  if (!Array.isArray(organizations)) {
    return { passed: false, error: 'Supabase did not return an organization list.' }
  }

  const visible = organizations.filter((o) => typeof o.id === 'string').map((o) => o.id as string)
  if (!visible.includes(orgId)) {
    return {
      passed: false,
      error:
        `Organization "${orgId}" is not visible to this token ` +
        `(${visible.length} organization(s) available).\n` +
        'Check TF_VAR_SUPABASE_ORG_ID.',
    }
  }

  return { passed: true }
}

export const supabaseCheck: DoctorCheck = { label: 'Supabase', run: checkSupabase }
