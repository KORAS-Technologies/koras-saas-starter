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
  /** Explicit --domain, when the project has its own brand domain. */
  domain?: string
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
  domain?: string
}): GenerationContext {
  return { ...params }
}

/**
 * The domain this project's hostnames are issued under.
 *
 * Not the estate apex. Every project used to receive the apex, because
 * `primary_domain` arrived as one `TF_VAR_primary_domain` shared by the whole
 * bootstrap Doppler config -- so the Control Plane and every product asked
 * Vercel for the same names, and the second one to apply was refused with
 * `domain_already_in_use`. Half an estate had been created by then, and because
 * the OIDC redirect URIs and the DNS records are both derived from the domain
 * map, a hostname conflict presented as an identity and DNS outage. See R-028.
 *
 * The Control Plane keeps the apex: it is the platform, and `admin.<apex>` is
 * the name that belongs to it. A product is namespaced beneath it, so
 * `admin.<slug>.<apex>` and `admin.<apex>` cannot meet -- and neither can two
 * products, which was the same defect one step further out.
 *
 * `--domain` overrides both, for a product with its own brand domain. That is
 * the case docs/INFRASTRUCTURE_PLAN.md has always documented, with `docoris.app`.
 */
export function primaryDomain(ctx: GenerationContext): string {
  if (ctx.domain !== undefined && ctx.domain.trim() !== '') return ctx.domain.trim()

  const apex = ctx.defaults.infrastructure?.domain_apex ?? ''
  if (apex === '') return ''

  return ctx.profile === 'control-plane' ? apex : `${ctx.projectSlug}.${apex}`
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

    // Component key to source directory, for the Vercel module. Written into
    // terraform.tfvars so the module never has to guess the path.
    applicationSourceDirs: Object.fromEntries(
      enabledInfra(
        ctx.manifest.infrastructure.vercel.applications,
        ctx.selections.applications,
      ).map((key) => [key, ctx.manifest.template_map.applications[key] ?? `apps/${key}`]),
    ),
    flyServices: enabledInfra(ctx.manifest.infrastructure.fly.services, ctx.selections.services),
    flyApps: flyAppNames(ctx),
    zitadelProject: zitadelProjectName(ctx),

    registersAsProduct: ctx.manifest.registration.registers_as_product,
    registrationEndpoint: ctx.manifest.registration.endpoint ?? '',

    supabaseRegion: ctx.defaults.infrastructure?.supabase_region ?? '',
    flyRegion: ctx.defaults.infrastructure?.fly_region ?? '',
    vercelFramework: ctx.defaults.infrastructure?.vercel_framework ?? 'nextjs',
    tfOrganization: ctx.defaults.infrastructure?.terraform_organization ?? 'koras',
    primaryDomain: primaryDomain(ctx),

    ports: {
      supabaseDb: ctx.defaults.local?.ports?.supabase_db ?? 54322,
      zitadel: ctx.defaults.local?.ports?.zitadel ?? 8080,
      redis: ctx.defaults.local?.ports?.redis ?? 6379,
      mailSmtp: ctx.defaults.local?.ports?.mail_smtp ?? 1025,
      mailUi: ctx.defaults.local?.ports?.mail_ui ?? 8025,
      minioApi: ctx.defaults.local?.ports?.minio_api ?? 9000,
      minioConsole: ctx.defaults.local?.ports?.minio_console ?? 9001,
      proxyHttp: ctx.defaults.local?.ports?.proxy_http ?? 8090,
      proxyHttps: ctx.defaults.local?.ports?.proxy_https ?? 8443,
      otlpGrpc: ctx.defaults.local?.ports?.otlp_grpc ?? 4317,
      otlpHttp: ctx.defaults.local?.ports?.otlp_http ?? 4318,
      appWeb: ctx.defaults.local?.ports?.app_web ?? 3000,
      appAdmin: ctx.defaults.local?.ports?.app_admin ?? 3001,
      appMarketing: ctx.defaults.local?.ports?.app_marketing ?? 3002,
      appPortal: ctx.defaults.local?.ports?.app_portal ?? 3011,
      serviceApi: ctx.defaults.local?.ports?.service_api ?? 8000,
      serviceAiGateway: ctx.defaults.local?.ports?.service_ai_gateway ?? 4000,
    },
  }
}
