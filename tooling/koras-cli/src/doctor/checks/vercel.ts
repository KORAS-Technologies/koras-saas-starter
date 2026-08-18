import type { DoctorCheck, DoctorContext, DoctorResult } from '../types.js'
import { requestJson, HttpError } from '../http.js'
import { require } from '../env.js'

/** Reads the authenticated user and the configured team. Deploys nothing. */
export async function checkVercel(ctx: DoctorContext): Promise<DoctorResult> {
  const needed = require(ctx.env, ['VERCEL_API_TOKEN', 'TF_VAR_vercel_team_id'], {
    TF_VAR_vercel_team_id: 'TF_VAR_VERCEL_TEAM_ID',
  })
  if (!needed.ok) return { passed: false, error: `Not set: ${needed.missing.join(', ')}.` }

  const headers = {
    authorization: `Bearer ${needed.values.VERCEL_API_TOKEN}`,
    accept: 'application/json',
  }

  try {
    await requestJson(ctx.fetchImpl, 'https://api.vercel.com/v2/user', { headers })
  } catch (err) {
    if (err instanceof HttpError && (err.status === 401 || err.status === 403)) {
      return { passed: false, error: 'VERCEL_API_TOKEN was rejected.' }
    }
    throw err
  }

  const teamId = needed.values.TF_VAR_vercel_team_id
  try {
    await requestJson(
      ctx.fetchImpl,
      `https://api.vercel.com/v2/teams/${encodeURIComponent(teamId)}`,
      { headers },
    )
  } catch (err) {
    if (err instanceof HttpError) {
      return {
        passed: false,
        error:
          `Team "${teamId}" is not accessible (HTTP ${err.status}).\n` +
          'Check TF_VAR_VERCEL_TEAM_ID and the token scope.',
      }
    }
    throw err
  }

  return { passed: true }
}

export const vercelCheck: DoctorCheck = { label: 'Vercel', run: checkVercel }
