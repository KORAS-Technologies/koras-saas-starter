import type { DoctorCheck, DoctorContext, DoctorResult } from '../types.js'
import { requestJson, HttpError } from '../http.js'
import { require } from '../env.js'

/** Reads the configured organization. Creates nothing. */
export async function checkGitHub(ctx: DoctorContext): Promise<DoctorResult> {
  const needed = require(ctx.env, ['GITHUB_TOKEN', 'TF_VAR_github_org'], {
    TF_VAR_github_org: 'TF_VAR_GITHUB_ORG',
  })
  if (!needed.ok) return { passed: false, error: missingMessage(needed.missing) }

  const org = needed.values.TF_VAR_github_org

  try {
    await requestJson(ctx.fetchImpl, `https://api.github.com/orgs/${encodeURIComponent(org)}`, {
      headers: {
        authorization: `Bearer ${needed.values.GITHUB_TOKEN}`,
        accept: 'application/vnd.github+json',
        'user-agent': 'koras-bootstrap-doctor',
      },
    })
  } catch (err) {
    if (err instanceof HttpError && err.status === 401) {
      return { passed: false, error: 'GITHUB_TOKEN was rejected. Check the token and its expiry.' }
    }
    if (err instanceof HttpError && (err.status === 403 || err.status === 404)) {
      return {
        passed: false,
        error:
          `Organization "${org}" is not accessible (HTTP ${err.status}).\n` +
          'Check TF_VAR_GITHUB_ORG and that the token has org read access.',
      }
    }
    throw err
  }

  return { passed: true }
}

function missingMessage(missing: string[]): string {
  return `Not set: ${missing.join(', ')}.`
}

export const githubCheck: DoctorCheck = { label: 'GitHub', run: checkGitHub }
