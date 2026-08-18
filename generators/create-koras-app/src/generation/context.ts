import type { ProfileManifest, ProfileDefaults, ComponentSelections } from '../profiles/types.js'
import type { ProfileName } from '../profiles/loader.js'

export interface GenerationContext {
  projectName: string
  projectSlug: string
  profile: ProfileName
  manifest: ProfileManifest
  defaults: ProfileDefaults
  selections: ComponentSelections
  outputDir: string
  dryRun: boolean
  provision: boolean
}

export function buildContext(params: {
  projectName: string
  projectSlug: string
  profile: ProfileName
  manifest: ProfileManifest
  defaults: ProfileDefaults
  selections: ComponentSelections
  outputDir: string
  dryRun: boolean
  provision: boolean
}): GenerationContext {
  return { ...params }
}

function enabledKeys(selected: Record<string, boolean>): string[] {
  return Object.entries(selected)
    .filter(([, on]) => on)
    .map(([name]) => name)
    .sort()
}

/** Components the profile declares deployable to Vercel/Fly, filtered by selection. */
function enabledInfra(declared: string[], selected: Record<string, boolean>): string[] {
  return declared.filter((name) => selected[name] === true)
}

export interface EnvironmentNaming {
  env: string
  doppler: string
  supabase: string
  branch: string
}

const ENV_TO_BRANCH: Record<string, string> = {
  dev: 'develop',
  test: 'test',
  stg: 'staging',
  prod: 'main',
}

export function environmentNaming(ctx: GenerationContext): EnvironmentNaming[] {
  return ctx.manifest.environments.map((env) => ({
    env,
    doppler: `${ctx.projectSlug}-${env}`,
    supabase: `${ctx.projectSlug}-${env}`,
    branch: ENV_TO_BRANCH[env] ?? env,
  }))
}

/** Fly app names: <slug>-<service>-<env>, service key hyphenated. */
export function flyAppNames(ctx: GenerationContext): string[] {
  const services = enabledInfra(ctx.manifest.infrastructure.fly.services, ctx.selections.services)
  return ctx.manifest.environments.flatMap((env) =>
    services.map((svc) => `${ctx.projectSlug}-${svc.replace(/_/g, '-')}-${env}`),
  )
}

/**
 * Vercel project names: <slug>-<app>, app key hyphenated.
 *
 * Component keys are identifiers and may contain underscores
 * (`platform_admin`); Vercel accepts lowercase alphanumerics and hyphens only
 * and rejects the rest at plan time. The keys themselves still go to Terraform
 * as `enabled_apps` — the module needs them to look components up — so this is
 * a separate value, used wherever a real project name is meant.
 */
export function vercelProjectNames(ctx: GenerationContext): string[] {
  return enabledInfra(ctx.manifest.infrastructure.vercel.applications, ctx.selections.applications)
    .map((app) => `${ctx.projectSlug}-${app.replace(/_/g, '-')}`)
}

/** ZITADEL project name carries no environment suffix — the instance is the environment. */
export function zitadelProjectName(ctx: GenerationContext): string {
  return ctx.projectSlug
}

export function contextToTemplateVars(ctx: GenerationContext): Record<string, unknown> {
  const applications = enabledKeys(ctx.selections.applications)
  const services = enabledKeys(ctx.selections.services)
  const capabilities = enabledKeys(ctx.selections.capabilities)

  return {
    projectName: ctx.projectName,
    projectSlug: ctx.projectSlug,
    profile: ctx.profile,
    isProduct: ctx.profile === 'product',
    isControlPlane: ctx.profile === 'control-plane',

    selections: ctx.selections,
    // Handlebars-friendly lookups: {{#if apps.marketing}} / {{#if capability.billing}}
    apps: ctx.selections.applications,
    service: ctx.selections.services,
    capability: ctx.selections.capabilities,

    enabledApplications: applications,
    enabledServices: services,
    enabledCapabilities: capabilities,

    // {key, path} pairs — component keys do not always match template directories
    // (control-plane's `platform_admin` lives in `apps/admin`).
    applicationTargets: applications.map((key) => ({
      key,
      path: ctx.manifest.template_map.applications[key] ?? `apps/${key}`,
    })),
    serviceTargets: services.map((key) => ({
      key,
      path: ctx.manifest.template_map.services[key] ?? `services/${key}`,
    })),

    environments: ctx.manifest.environments,
    environmentNaming: environmentNaming(ctx),

    vercelProjects: enabledInfra(
      ctx.manifest.infrastructure.vercel.applications,
      ctx.selections.applications,
    ),
    vercelProjectNames: vercelProjectNames(ctx),
    flyServices: enabledInfra(ctx.manifest.infrastructure.fly.services, ctx.selections.services),
    flyApps: flyAppNames(ctx),
    zitadelProject: zitadelProjectName(ctx),

    registersAsProduct: ctx.manifest.registration.registers_as_product,
    registrationEndpoint: ctx.manifest.registration.endpoint ?? '',

    supabaseRegion: ctx.defaults.infrastructure?.supabase_region ?? '',
    flyRegion: ctx.defaults.infrastructure?.fly_region ?? '',
    vercelFramework: ctx.defaults.infrastructure?.vercel_framework ?? 'nextjs',
    tfOrganization: ctx.defaults.infrastructure?.terraform_organization ?? 'koras',
  }
}
