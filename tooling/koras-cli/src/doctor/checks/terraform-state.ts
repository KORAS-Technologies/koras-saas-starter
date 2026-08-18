import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import yaml from 'js-yaml'
import type { DoctorCheck, DoctorContext, DoctorResult } from '../types.js'
import { requestJson, HttpError } from '../http.js'
import { value } from '../env.js'

/**
 * Remote state readiness.
 *
 * The starter has no bootstrap workspace to read: every workspace is created
 * per generated project (`backend.tf` pins `workspaces { name = "<slug>" }`),
 * so there is no state that exists before the first project. What can be
 * verified — and what actually blocks a bootstrap — is that the HCP token
 * authenticates, the organization exists, and workspaces under it are
 * readable. A failure here means `terraform init` will fail for every project.
 *
 * Both calls are GETs against the HCP API. No state is read into memory, no
 * output value is fetched, and nothing is modified.
 */

export const HCP_API = 'https://app.terraform.io/api/v2'

/**
 * The HCP organization, read from the profile defaults the generator renders
 * into `backend.tf` — not hard-coded, so changing the estate changes this too.
 */
export function terraformOrganization(repoRoot: string): string | undefined {
  for (const profile of ['product', 'control-plane']) {
    const path = join(repoRoot, 'profiles', profile, 'defaults.yaml')
    if (!existsSync(path)) continue
    const parsed = yaml.load(readFileSync(path, 'utf8')) as
      | { infrastructure?: { terraform_organization?: unknown } }
      | undefined
    const org = parsed?.infrastructure?.terraform_organization
    if (typeof org === 'string' && org.length > 0) return org
  }
  return undefined
}

export async function checkTerraformState(ctx: DoctorContext): Promise<DoctorResult> {
  const token =
    value(ctx.env, 'TF_TOKEN_app_terraform_io') ?? value(ctx.env, 'TF_TOKEN_APP_TERRAFORM_IO')
  if (!token) return { passed: false, error: 'Not set: TF_TOKEN_APP_TERRAFORM_IO.' }

  const organization = terraformOrganization(ctx.repoRoot)
  if (!organization) {
    return {
      passed: false,
      error: 'No terraform_organization in profiles/*/defaults.yaml — the backend has no organization.',
    }
  }

  const headers = {
    authorization: `Bearer ${token}`,
    'content-type': 'application/vnd.api+json',
    accept: 'application/vnd.api+json',
  }

  try {
    await requestJson(ctx.fetchImpl, `${HCP_API}/organizations/${encodeURIComponent(organization)}`, {
      headers,
    })
  } catch (err) {
    if (err instanceof HttpError && (err.status === 401 || err.status === 403)) {
      return { passed: false, error: 'TF_TOKEN_APP_TERRAFORM_IO was rejected by HCP Terraform.' }
    }
    if (err instanceof HttpError && err.status === 404) {
      return {
        passed: false,
        error:
          `HCP Terraform organization "${organization}" was not found.\n` +
          'Check terraform_organization in profiles/*/defaults.yaml.',
      }
    }
    throw err
  }

  // Proves state under the organization is readable, without needing any
  // particular workspace to exist yet.
  try {
    await requestJson(
      ctx.fetchImpl,
      `${HCP_API}/organizations/${encodeURIComponent(organization)}/workspaces?page%5Bsize%5D=1`,
      { headers },
    )
  } catch (err) {
    if (err instanceof HttpError) {
      return {
        passed: false,
        error:
          `Workspaces in "${organization}" are not readable (HTTP ${err.status}).\n` +
          'Check the token\'s organization access.',
      }
    }
    throw err
  }

  return { passed: true }
}

export const terraformStateCheck: DoctorCheck = {
  label: 'Terraform state',
  run: checkTerraformState,
}
