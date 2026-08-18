import type { DoctorCheck, DoctorContext, DoctorResult } from '../types.js'
import { requestJson, HttpError } from '../http.js'
import { require, value } from '../env.js'

interface GitNamespace {
  /** Organization or user login the Vercel GitHub App is installed on. */
  slug?: unknown
}

/**
 * Reads the authenticated user, the configured team, and the GitHub accounts
 * Vercel can import from. Deploys nothing.
 */
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

  // Every Vercel project this provisions is created from a GitHub repository,
  // which only works if Vercel's GitHub App is installed on the organization
  // that owns it. A token and team that are both perfectly valid still produce
  // `repo_not_found` at apply time when it is not — and the App defaults to the
  // personal account of whoever connected it, which is the usual state.
  //
  // The endpoint rejects a teamId, so this reports what the token's account can
  // see. That is the same set Vercel resolves the repository against.
  const org = value(ctx.env, 'TF_VAR_github_org')
  if (org) {
    let namespaces: GitNamespace[]
    try {
      namespaces = await requestJson<GitNamespace[]>(
        ctx.fetchImpl,
        'https://api.vercel.com/v1/integrations/git-namespaces?provider=github',
        { headers },
      )
    } catch (err) {
      if (err instanceof HttpError) {
        return {
          passed: false,
          error: `Could not list Vercel's connected GitHub accounts (HTTP ${err.status}).`,
        }
      }
      throw err
    }

    const connected = (Array.isArray(namespaces) ? namespaces : [])
      .map((n) => n.slug)
      .filter((s): s is string => typeof s === 'string')

    if (!connected.some((slug) => slug.toLowerCase() === org.toLowerCase())) {
      return {
        passed: false,
        error:
          `Vercel's GitHub App is not installed on "${org}", so projects cannot\n` +
          `be created from its repositories. Connected: ${connected.join(', ') || 'none'}.\n` +
          'Install it for the organization from Vercel → Settings → Git; an org\n' +
          'owner may need to approve it.',
      }
    }
  }

  return { passed: true }
}

export const vercelCheck: DoctorCheck = { label: 'Vercel', run: checkVercel }
