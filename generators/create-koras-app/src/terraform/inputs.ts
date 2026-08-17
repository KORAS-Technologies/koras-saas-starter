import type { GenerationContext } from '../generation/context.js'

/**
 * Provider tokens Terraform needs. Every one is read from the environment —
 * Doppler is the authority and nothing is written to disk or into state.
 */
export const PROVIDER_CREDENTIALS = [
  { name: 'GITHUB_TOKEN', provider: 'GitHub', purpose: 'repository, branches, environments' },
  { name: 'DOPPLER_TOKEN', provider: 'Doppler', purpose: 'project and per-environment configs' },
  { name: 'SUPABASE_ACCESS_TOKEN', provider: 'Supabase', purpose: 'one project per environment' },
  { name: 'VERCEL_API_TOKEN', provider: 'Vercel', purpose: 'one project per enabled application' },
  { name: 'FLY_API_TOKEN', provider: 'Fly.io', purpose: 'one app per service per environment' },
  { name: 'CLOUDFLARE_API_TOKEN', provider: 'Cloudflare', purpose: 'DNS records' },
  // The generated backend.tf uses `backend "remote"`, so `init` needs a token
  // for app.terraform.io before any provider is even contacted. `terraform
  // login` writes one to ~/.terraform.d, but CI and Doppler-injected shells
  // supply it here.
  {
    name: 'TF_TOKEN_app_terraform_io',
    provider: 'HCP Terraform',
    purpose: 'remote state backend (or run `terraform login`)',
  },
] as const

/**
 * Sensitive Terraform variables. These carry per-environment secrets and are
 * passed as TF_VAR_* JSON rather than through the committed tfvars file.
 */
export const SECRET_VARIABLES = [
  {
    name: 'TF_VAR_supabase_environments',
    purpose: 'per-environment Supabase db_password and region',
  },
  {
    name: 'TF_VAR_zitadel_instances',
    purpose: 'per-instance ZITADEL domain, port, insecure, jwt_profile_json',
  },
] as const

/**
 * Non-secret variables the operator must still supply — they describe the
 * target accounts and are specific to the KORAS estate, not to the project.
 */
export const ACCOUNT_VARIABLES = [
  { name: 'TF_VAR_github_org', purpose: 'GitHub organisation that owns the repository' },
  { name: 'TF_VAR_primary_domain', purpose: 'apex domain for this project' },
  { name: 'TF_VAR_supabase_org_id', purpose: 'Supabase organisation ID' },
  { name: 'TF_VAR_vercel_team_id', purpose: 'Vercel team ID' },
  { name: 'TF_VAR_fly_org_slug', purpose: 'Fly.io organisation slug' },
  { name: 'TF_VAR_cloudflare_zone_id', purpose: 'Cloudflare zone for the primary domain' },
] as const

export interface MissingInput {
  name: string
  detail: string
}

export interface PreflightResult {
  ok: boolean
  missing: MissingInput[]
}

/**
 * Checks every credential and variable Terraform will need BEFORE running it.
 * Terraform surfaces missing variables one at a time and only after `init` has
 * downloaded providers; this reports the whole list up front.
 */
export function preflightInputs(env: NodeJS.ProcessEnv = process.env): PreflightResult {
  const missing: MissingInput[] = []

  const requireVar = (name: string, detail: string) => {
    const value = env[name]
    if (value === undefined || value.trim() === '') missing.push({ name, detail })
  }

  for (const c of PROVIDER_CREDENTIALS) requireVar(c.name, `${c.provider} — ${c.purpose}`)
  for (const v of SECRET_VARIABLES) requireVar(v.name, v.purpose)
  for (const v of ACCOUNT_VARIABLES) requireVar(v.name, v.purpose)

  return { ok: missing.length === 0, missing }
}

export function formatMissingInputs(missing: MissingInput[]): string {
  return [
    `Terraform cannot run — ${missing.length} required input${missing.length === 1 ? '' : 's'} missing:`,
    '',
    ...missing.map((m) => `  ${m.name.padEnd(30)} ${m.detail}`),
    '',
    'Supply them from Doppler:',
    '  doppler run --project koras-platform-bootstrap --config <config> -- \\',
    '    pnpm create-koras-app <project> --profile <profile> --provision',
    '',
    'Or export them in the current shell. Secret values are never written to',
    'disk, logged, or included in the registration payload.',
  ].join('\n')
}

/** Terraform working directory inside a generated project. */
export function terraformDirectory(projectRoot: string): string {
  return `${projectRoot}/infrastructure/terraform`.replace(/\\/g, '/')
}

export interface ProjectTfvars {
  profile?: string
  projectSlug?: string
  enabledApps: string[]
  enabledServices: string[]
}

/**
 * Reads the committed terraform.tfvars of an already-generated project.
 *
 * With `--provision-only` the project on disk is the source of truth — its
 * component selections may differ from what the profile defaults would produce
 * today. Terraform reads this file itself; parsing it here is only so the
 * runner can report accurately and warn on a profile mismatch.
 */
export function readProjectTfvars(contents: string): ProjectTfvars {
  const scalar = (key: string): string | undefined =>
    new RegExp(`^\\s*${key}\\s*=\\s*"([^"]*)"`, 'm').exec(contents)?.[1]

  const list = (key: string): string[] => {
    const raw = new RegExp(`^\\s*${key}\\s*=\\s*(\\[[^\\]]*\\])`, 'm').exec(contents)?.[1]
    if (!raw) return []
    try {
      return JSON.parse(raw) as string[]
    } catch {
      return []
    }
  }

  return {
    profile: scalar('profile'),
    projectSlug: scalar('project_slug'),
    enabledApps: list('enabled_apps'),
    enabledServices: list('enabled_services'),
  }
}

/**
 * Variables the generator itself contributes. All non-secret, and already
 * rendered into the committed terraform.tfvars — so `plan` needs no extra
 * -var flags. This exists so the runner can echo what Terraform will act on,
 * and so tests can assert the generator → Terraform contract.
 */
export function generatorProvidedInputs(ctx: GenerationContext): Record<string, unknown> {
  const enabled = (selected: Record<string, boolean>, declared: string[]) =>
    declared.filter((name) => selected[name] === true)

  return {
    profile: ctx.profile,
    project_name: ctx.projectName,
    project_slug: ctx.projectSlug,
    enabled_apps: enabled(
      ctx.selections.applications,
      ctx.manifest.infrastructure.vercel.applications,
    ),
    enabled_services: enabled(ctx.selections.services, ctx.manifest.infrastructure.fly.services),
    supabase_region: ctx.defaults.infrastructure?.supabase_region ?? '',
  }
}
