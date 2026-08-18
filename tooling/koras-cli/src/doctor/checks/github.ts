import type { DoctorCheck, DoctorContext, DoctorResult } from '../types.js'
import { requestJson, HttpError } from '../http.js'
import { require } from '../env.js'

interface OrganizationProfile {
  /** Present only when the token has real access to the organization. */
  members_can_create_repositories?: boolean
}

/** Reads the configured organization. Creates nothing. */
export async function checkGitHub(ctx: DoctorContext): Promise<DoctorResult> {
  const needed = require(ctx.env, ['GITHUB_TOKEN', 'TF_VAR_github_org'], {
    TF_VAR_github_org: 'TF_VAR_GITHUB_ORG',
  })
  if (!needed.ok) return { passed: false, error: missingMessage(needed.missing) }

  const org = needed.values.TF_VAR_github_org

  let profile: OrganizationProfile
  try {
    profile = await requestJson<OrganizationProfile>(
      ctx.fetchImpl,
      `https://api.github.com/orgs/${encodeURIComponent(org)}`,
      {
        headers: {
          authorization: `Bearer ${needed.values.GITHUB_TOKEN}`,
          accept: 'application/vnd.github+json',
          'user-agent': 'koras-bootstrap-doctor',
        },
      },
    )
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

  // A 200 from /orgs/{org} proves almost nothing: the organization profile is
  // public, so ANY valid token reads it — including one with no access to the
  // organization at all. That is how a token which cannot create repositories
  // passed this check, and the failure only surfaced during `terraform apply`,
  // after four Supabase projects had already been created.
  //
  // Fields like `members_can_create_repositories` are returned only when the
  // token actually has organization visibility, so their absence separates
  // "read the public profile" from "has access to this org".
  if (profile.members_can_create_repositories === undefined) {
    return {
      passed: false,
      error:
        `GITHUB_TOKEN can read the public profile of "${org}" but has no access\n` +
        'to the organization itself, so it cannot create repositories.\n' +
        'A fine-grained token needs the organization as its resource owner,\n' +
        'Organization Administration: Read and write, and approval by an owner.\n' +
        'Provisioning also needs repository Contents and Environments: Read and\n' +
        'write. No API exposes those, so they fail later, during apply.',
    }
  }

  if (profile.members_can_create_repositories === false) {
    return {
      passed: false,
      error:
        `Organization "${org}" does not allow members to create repositories.\n` +
        'An owner must enable it, or the token must belong to an owner.',
    }
  }

  return { passed: true }
}

function missingMessage(missing: string[]): string {
  return `Not set: ${missing.join(', ')}.`
}

export const githubCheck: DoctorCheck = { label: 'GitHub', run: checkGitHub }
