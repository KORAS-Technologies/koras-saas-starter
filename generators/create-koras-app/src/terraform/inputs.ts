import type { GenerationContext } from '../generation/context.js'

/**
 * Doppler secret names may only contain [A-Z0-9_], but Terraform matches
 * `TF_VAR_<name>` case-sensitively against the HCL variable, and `TF_TOKEN_`
 * encodes a hostname in lowercase. The two conventions cannot both be
 * satisfied by a single name.
 *
 * So every case-sensitive input has an uppercase ALIAS that Doppler can store.
 * The alias is accepted by preflight and mapped back to the canonical name
 * before Terraform is spawned — see `resolveTerraformEnv`.
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
    alias: 'TF_TOKEN_APP_TERRAFORM_IO',
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
    alias: 'TF_VAR_SUPABASE_ENVIRONMENTS',
    purpose: 'per-environment Supabase db_password and region',
  },
  {
    name: 'TF_VAR_zitadel_instances',
    alias: 'TF_VAR_ZITADEL_INSTANCES',
    purpose: 'per-instance ZITADEL domain, port, insecure, jwt_profile_json',
  },
] as const

/**
 * Non-secret variables the operator must still supply — they describe the
 * target accounts and are specific to the KORAS estate, not to the project.
 */
export const ACCOUNT_VARIABLES = [
  { name: 'TF_VAR_github_org', alias: 'TF_VAR_GITHUB_ORG', purpose: 'GitHub organisation that owns the repository' },
  { name: 'TF_VAR_primary_domain', alias: 'TF_VAR_PRIMARY_DOMAIN', purpose: 'apex domain for this project' },
  { name: 'TF_VAR_supabase_org_id', alias: 'TF_VAR_SUPABASE_ORG_ID', purpose: 'Supabase organisation ID' },
  { name: 'TF_VAR_vercel_team_id', alias: 'TF_VAR_VERCEL_TEAM_ID', purpose: 'Vercel team ID' },
  { name: 'TF_VAR_fly_org_slug', alias: 'TF_VAR_FLY_ORG_SLUG', purpose: 'Fly.io organisation slug' },
  { name: 'TF_VAR_cloudflare_zone_id', alias: 'TF_VAR_CLOUDFLARE_ZONE_ID', purpose: 'Cloudflare zone for the primary domain' },
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
interface InputDefinition {
  name: string
  alias?: string
  purpose: string
  provider?: string
}

/** Every input, with the uppercase alias Doppler is able to store. */
export function allInputs(): InputDefinition[] {
  return [
    ...PROVIDER_CREDENTIALS.map((c) => ({
      name: c.name,
      alias: 'alias' in c ? (c.alias as string) : undefined,
      purpose: `${c.provider} — ${c.purpose}`,
    })),
    ...SECRET_VARIABLES.map((v) => ({ name: v.name, alias: v.alias, purpose: v.purpose })),
    ...ACCOUNT_VARIABLES.map((v) => ({ name: v.name, alias: v.alias, purpose: v.purpose })),
  ]
}

function readInput(env: NodeJS.ProcessEnv, input: InputDefinition): string | undefined {
  for (const key of [input.name, input.alias]) {
    if (key === undefined) continue
    const value = env[key]
    if (value !== undefined && value.trim() !== '') return value
  }
  return undefined
}

export function preflightInputs(env: NodeJS.ProcessEnv = process.env): PreflightResult {
  const missing: MissingInput[] = []

  for (const input of allInputs()) {
    if (readInput(env, input) === undefined) {
      missing.push({ name: input.alias ?? input.name, detail: input.purpose })
    }
  }

  return { ok: missing.length === 0, missing }
}

/**
 * Builds the environment Terraform is spawned with.
 *
 * Values stored under an uppercase alias are copied to the canonical,
 * case-sensitive name Terraform actually reads. An explicitly-set canonical
 * name always wins, so an operator who exported `TF_VAR_github_org` directly
 * is never overridden by an alias.
 */
export function resolveTerraformEnv(env: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  const resolved: NodeJS.ProcessEnv = { ...env }

  for (const input of allInputs()) {
    if (!input.alias) continue
    const canonical = resolved[input.name]
    if (canonical !== undefined && canonical.trim() !== '') continue
    const aliased = resolved[input.alias]
    if (aliased !== undefined && aliased.trim() !== '') resolved[input.name] = aliased
  }

  return resolved
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
    'Doppler secret names allow only [A-Z0-9_], so the uppercase names above are',
    'what to store; the generator maps them to the case Terraform requires.',
    '',
    'Secret values are never written to disk, logged, or included in the',
    'registration payload.',
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
