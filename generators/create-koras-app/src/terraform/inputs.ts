import type { GenerationContext } from '../generation/context.js'
import { stripTrailingSlashes } from '../url.js'

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

export const ENVIRONMENTS = ['dev', 'test', 'stg', 'prod'] as const

/**
 * Sensitive Terraform variables.
 *
 * Each is a map covering all four environments, so Terraform needs it as a
 * single JSON value. That is awkward to operate — rotating one instance's key
 * would mean regenerating the whole blob — so each can instead be supplied as
 * flat per-environment secrets and assembled here, in memory. The blob form
 * still works for anyone who prefers it.
 */
export const SECRET_VARIABLES = [
  {
    name: 'TF_VAR_supabase_environments',
    alias: 'TF_VAR_SUPABASE_ENVIRONMENTS',
    purpose: 'per-environment Supabase db_password and region',
    flat: ENVIRONMENTS.map((e) => `SUPABASE_DB_PASSWORD_${e.toUpperCase()}`),
    assemble: assembleSupabaseEnvironments,
  },
  {
    name: 'TF_VAR_fly_api_token',
    alias: 'TF_VAR_FLY_API_TOKEN',
    purpose: 'Fly.io token, so Terraform can write it as a deploy secret',
    // Assembled from the credential the Fly provider already reads. The
    // deploy pipeline needs the same token, and Terraform can only write a
    // value it holds as a variable -- so this hands the existing one over
    // rather than asking an operator to supply the same secret twice under a
    // second name, which is how two names for one credential end up rotated
    // apart.
    flat: ['FLY_API_TOKEN'],
    assemble: (env: NodeJS.ProcessEnv) => env.FLY_API_TOKEN,
  },
  {
    name: 'TF_VAR_vercel_token',
    alias: 'TF_VAR_VERCEL_TOKEN',
    purpose: 'Vercel token, so Terraform can write it as a deploy secret',
    flat: ['VERCEL_API_TOKEN'],
    assemble: (env: NodeJS.ProcessEnv) => env.VERCEL_API_TOKEN,
  },
  {
    name: 'TF_VAR_zitadel_instances',
    alias: 'TF_VAR_ZITADEL_INSTANCES',
    purpose: 'per-instance ZITADEL domain, port, insecure, jwt_profile_json',
    flat: ENVIRONMENTS.flatMap((e) => [
      `ZITADEL_${e.toUpperCase()}_DOMAIN`,
      `ZITADEL_${e.toUpperCase()}_SERVICE_ACCOUNT_KEY_JSON`,
    ]),
    assemble: assembleZitadelInstances,
  },
] as const

function value(env: NodeJS.ProcessEnv, name: string): string | undefined {
  const raw = env[name]
  return raw !== undefined && raw.trim() !== '' ? raw : undefined
}

/**
 * Builds TF_VAR_supabase_environments from SUPABASE_DB_PASSWORD_<ENV>.
 * SUPABASE_REGION_<ENV> is optional — the module falls back to supabase_region.
 */
export function assembleSupabaseEnvironments(env: NodeJS.ProcessEnv): string | undefined {
  const out: Record<string, { db_password: string; region?: string }> = {}

  for (const e of ENVIRONMENTS) {
    const password = value(env, `SUPABASE_DB_PASSWORD_${e.toUpperCase()}`)
    if (password === undefined) return undefined
    const region = value(env, `SUPABASE_REGION_${e.toUpperCase()}`)
    out[e] = region ? { db_password: password, region } : { db_password: password }
  }

  return JSON.stringify(out)
}

/**
 * Builds TF_VAR_zitadel_instances from the per-instance secrets. Port and
 * insecure default to 443/false and are only worth overriding for a
 * self-hosted instance.
 */
export function assembleZitadelInstances(env: NodeJS.ProcessEnv): string | undefined {
  const out: Record<
    string,
    {
      domain: string
      port: number
      insecure: boolean
      jwt_profile_json: string
      org_id?: string
    }
  > = {}

  for (const e of ENVIRONMENTS) {
    const key = e.toUpperCase()
    const domain = value(env, `ZITADEL_${key}_DOMAIN`)
    const profile = value(env, `ZITADEL_${key}_SERVICE_ACCOUNT_KEY_JSON`)
    if (domain === undefined || profile === undefined) return undefined

    out[e] = {
      // tolerate a pasted https:// prefix or trailing slash
      domain: stripTrailingSlashes(domain.replace(/^https?:\/\//, '')),
      port: Number(value(env, `ZITADEL_${key}_PORT`) ?? 443),
      insecure: value(env, `ZITADEL_${key}_INSECURE`) === 'true',
      jwt_profile_json: profile,
      // Only where the instance holds more than one organization. The module
      // finds the single active one by itself and refuses to guess otherwise,
      // naming both -- which is when this is worth setting, and not before.
      // Omitted rather than sent as null: the Terraform type is
      // `optional(string)`, and absent and null are different there.
      ...(value(env, `ZITADEL_${key}_ORG_ID`) !== undefined
        ? { org_id: value(env, `ZITADEL_${key}_ORG_ID`) }
        : {}),
    }
  }

  return JSON.stringify(out)
}

/**
 * Non-secret variables the operator must still supply — they describe the
 * target accounts and are specific to the KORAS estate, not to the project.
 */
export const ACCOUNT_VARIABLES = [
  { name: 'TF_VAR_github_org', alias: 'TF_VAR_GITHUB_ORG', purpose: 'GitHub organisation that owns the repository' },
  // The estate apex, which is the Cloudflare zone -- not the domain any one
  // project is served under. Reading it as the latter is what let the Control
  // Plane and every product ask Vercel for the same hostnames (R-028).
  //
  // Each project now carries its own `primary_domain` in terraform.tfvars, and
  // terraform.tfvars outranks a TF_VAR_ environment variable, so this no longer
  // decides what a project is served under. It stays because
  // `koras bootstrap:doctor` compares it against the zone the token can write,
  // which is an estate-level question and the right use of one shared value.
  { name: 'TF_VAR_primary_domain', alias: 'TF_VAR_PRIMARY_DOMAIN', purpose: 'estate apex (Cloudflare zone)' },
  { name: 'TF_VAR_supabase_org_id', alias: 'TF_VAR_SUPABASE_ORG_ID', purpose: 'Supabase organisation ID' },
  { name: 'TF_VAR_vercel_team_id', alias: 'TF_VAR_VERCEL_TEAM_ID', purpose: 'Vercel team ID' },
  { name: 'TF_VAR_fly_org_slug', alias: 'TF_VAR_FLY_ORG_SLUG', purpose: 'Fly.io organisation slug' },
  { name: 'TF_VAR_cloudflare_zone_id', alias: 'TF_VAR_CLOUDFLARE_ZONE_ID', purpose: 'Cloudflare zone for the primary domain' },
  // Upstash is configured through variables rather than a bare token because
  // `email` and `api_key` are required provider arguments with no environment
  // fallback. Unregistered, they slip past preflight and surface as three
  // "Missing required argument" errors after `init` has downloaded providers.
  { name: 'TF_VAR_upstash_email', alias: 'TF_VAR_UPSTASH_EMAIL', purpose: 'Upstash account email (Redis queue per environment)' },
  { name: 'TF_VAR_upstash_api_key', alias: 'TF_VAR_UPSTASH_API_KEY', purpose: 'Upstash management API key' },
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
  /** Flat per-environment secrets this value can be assembled from instead. */
  flat?: readonly string[]
  assemble?: (env: NodeJS.ProcessEnv) => string | undefined
}

/** Every input, with the uppercase alias Doppler is able to store. */
export function allInputs(): InputDefinition[] {
  return [
    ...PROVIDER_CREDENTIALS.map((c) => ({
      name: c.name,
      alias: 'alias' in c ? (c.alias as string) : undefined,
      purpose: `${c.provider} — ${c.purpose}`,
    })),
    ...SECRET_VARIABLES.map((v) => ({
      name: v.name,
      alias: v.alias,
      purpose: v.purpose,
      flat: v.flat,
      assemble: v.assemble,
    })),
    ...ACCOUNT_VARIABLES.map((v) => ({ name: v.name, alias: v.alias, purpose: v.purpose })),
  ]
}

/**
 * Resolves one input: the canonical name wins, then the uppercase alias, then
 * assembly from flat per-environment secrets.
 */
function readInput(env: NodeJS.ProcessEnv, input: InputDefinition): string | undefined {
  for (const key of [input.name, input.alias]) {
    if (key === undefined) continue
    const raw = env[key]
    if (raw !== undefined && raw.trim() !== '') return raw
  }
  return input.assemble?.(env)
}

export function preflightInputs(env: NodeJS.ProcessEnv = process.env): PreflightResult {
  const missing: MissingInput[] = []

  for (const input of allInputs()) {
    if (readInput(env, input) !== undefined) continue

    // Name the flat alternative too — it is the easier one to supply.
    const detail = input.flat
      ? `${input.purpose}
${' '.repeat(32)}or set ${input.flat[0]} … (${input.flat.length} values)`
      : input.purpose

    missing.push({ name: input.alias ?? input.name, detail })
  }

  return { ok: missing.length === 0, missing }
}

/**
 * Builds the environment Terraform is spawned with.
 *
 * Values stored under an uppercase alias, or as flat per-environment secrets,
 * are resolved to the canonical case-sensitive name Terraform reads. An
 * explicitly-set canonical name always wins.
 */
export function resolveTerraformEnv(env: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  const resolved: NodeJS.ProcessEnv = { ...env }

  for (const input of allInputs()) {
    const canonical = resolved[input.name]
    if (canonical === undefined || canonical.trim() === '') {
      const value = readInput(resolved, input)
      if (value !== undefined) resolved[input.name] = value
    }

    // Windows environment variable names are case-insensitive, so
    // TF_VAR_GITHUB_ORG and TF_VAR_github_org collide in the child process and
    // the alias wins — leaving Terraform to read a variable named GITHUB_ORG,
    // which matches nothing. Drop the alias once its value has been carried
    // over to the name Terraform actually looks for.
    if (input.alias && input.alias !== input.name) delete resolved[input.alias]
  }

  return resolved
}

export function formatMissingInputs(
  missing: MissingInput[],
  env: NodeJS.ProcessEnv = process.env,
): string {
  // `doppler run` injects these into the child environment. Their absence is
  // near-conclusive evidence that the command was run from a plain shell —
  // which is the actual cause almost every time, and far more useful to say
  // than listing fifteen names and leaving the operator to infer it.
  const insideDopplerRun = Boolean(env.DOPPLER_PROJECT ?? env.DOPPLER_CONFIG)

  const cause = insideDopplerRun
    ? [
        `The Doppler config in use (${env.DOPPLER_PROJECT ?? '?'}/${env.DOPPLER_CONFIG ?? '?'})`,
        'does not define every required secret. Add the names above to it.',
      ]
    : [
        'This command is not running under `doppler run` — DOPPLER_PROJECT is',
        'not set in this environment, so no secrets were injected.',
      ]

  return [
    `Terraform cannot run — ${missing.length} required input${missing.length === 1 ? '' : 's'} missing:`,
    '',
    ...missing.map((m) => `  ${m.name.padEnd(30)} ${m.detail}`),
    '',
    ...cause,
    '',
    'Supply them from Doppler:',
    '  doppler run --project koras-platform-bootstrap --config prod -- \\',
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
    // Component keys need not match their template directory, so Terraform is
    // told the directory rather than deriving it from the key. Deriving it gave
    // the control-plane profile a Vercel project rooted at apps/platform_admin,
    // a path that has never existed.
    application_source_dirs: Object.fromEntries(
      enabled(ctx.selections.applications, ctx.manifest.infrastructure.vercel.applications).map(
        (key) => [key, ctx.manifest.template_map.applications[key] ?? `apps/${key}`],
      ),
    ),
    supabase_region: ctx.defaults.infrastructure?.supabase_region ?? '',
  }
}
