import { z } from 'zod'

// ── Shared ─────────────────────────────────────────────────────────────────

const FrameworkSchema = z.enum(['nextjs', 'fastapi', 'arq', 'apscheduler', 'litellm'])

const ApplicationSchema = z.object({
  required: z.boolean(),
  framework: FrameworkSchema,
  description: z.string().optional(),
})

const ServiceSchema = z.object({
  required: z.boolean(),
  framework: FrameworkSchema,
  description: z.string().optional(),
})

const VercelInfraSchema = z.object({
  applications: z.array(z.string()),
})

const FlyInfraSchema = z.object({
  services: z.array(z.string()),
})

const InfrastructureSchema = z.object({
  supabase: z.boolean(),
  zitadel: z.boolean(),
  doppler: z.boolean(),
  vercel: VercelInfraSchema,
  fly: FlyInfraSchema,
  cloudflare: z.boolean(),
})

const RegistrationSchema = z.object({
  registers_as_product: z.boolean(),
  endpoint: z.string().optional(),
})

// Maps component keys to template subtree paths. A subtree is generated only
// when its component is enabled — this is how the capability matrix reaches
// template selection without profile-specific branching in the generator.
const TemplateMapSchema = z.object({
  applications: z.record(z.string(), z.string()).default({}),
  services: z.record(z.string(), z.string()).default({}),
  capabilities: z.record(z.string(), z.string()).default({}),
})

export type TemplateMap = z.infer<typeof TemplateMapSchema>

// Directories copied verbatim from the starter repository into the generated
// project. Used for assets that must stay single-sourced rather than being
// duplicated into each profile template (Terraform modules, for example).
const SharedAssetSchema = z.object({
  source: z.string(),
  target: z.string(),
})

export type SharedAsset = z.infer<typeof SharedAssetSchema>

// ── Profile manifest ───────────────────────────────────────────────────────

export const ProfileManifestSchema = z.object({
  schema_version: z.literal('1'),
  profile: z.enum(['product', 'control-plane']),
  // Version of the profile itself, independent of both the manifest schema
  // version and the starter version. Recorded in every generated project's
  // .koras/project.yaml, so a project can be traced back to the profile
  // revision that produced it. Semver: bump the major on a breaking change to
  // the generated structure.
  version: z.string().regex(/^\d+\.\d+\.\d+(?:[-+].*)?$/, 'must be a semantic version'),
  applications: z.record(z.string(), ApplicationSchema),
  services: z.record(z.string(), ServiceSchema),
  capabilities: z.record(z.string(), z.boolean()),
  registration: RegistrationSchema,
  infrastructure: InfrastructureSchema,
  environments: z.array(z.string()),
  template_map: TemplateMapSchema.default({
    applications: {},
    services: {},
    capabilities: {},
  }),
  shared_assets: z.array(SharedAssetSchema).default([]),
})

export type ProfileManifest = z.infer<typeof ProfileManifestSchema>

// ── Profile defaults ────────────────────────────────────────────────────────

export const ProfileDefaultsSchema = z.object({
  schema_version: z.literal('1'),
  applications: z.record(z.string(), z.boolean()).optional(),
  services: z.record(z.string(), z.boolean()).optional(),
  capabilities: z.record(z.string(), z.union([z.boolean(), z.string()])).optional(),
  infrastructure: z
    .object({
      supabase_region: z.string().optional(),
      fly_region: z.string().optional(),
      vercel_framework: z.string().optional(),
      terraform_organization: z.string().optional(),
      // Estate-level Doppler location of the provisioning credentials.
      // The CLI re-invokes itself under `doppler run` with these when the
      // inputs are not already in the environment.
      doppler_project: z.string().optional(),
      doppler_config: z.string().optional(),
    })
    .optional(),
  output: z
    .object({
      include_example_env: z.boolean().optional(),
      include_docker_compose: z.boolean().optional(),
    })
    .optional(),
  local: z
    .object({
      ports: z
        .object({
          supabase_db: z.number().int().optional(),
          zitadel: z.number().int().optional(),
          redis: z.number().int().optional(),
          mail_smtp: z.number().int().optional(),
          mail_ui: z.number().int().optional(),
          minio_api: z.number().int().optional(),
          minio_console: z.number().int().optional(),
          proxy_http: z.number().int().optional(),
          proxy_https: z.number().int().optional(),
          // Dev-server ports for host-run apps and services. Preferences
          // only: local/scripts/ports.sh resolves the actual values.
          app_web: z.number().int().optional(),
          app_admin: z.number().int().optional(),
          app_marketing: z.number().int().optional(),
          app_portal: z.number().int().optional(),
          service_api: z.number().int().optional(),
          service_ai_gateway: z.number().int().optional(),
        })
        .optional(),
    })
    .optional(),
})

export type ProfileDefaults = z.infer<typeof ProfileDefaultsSchema>

// ── Component selections (resolved at generation time) ─────────────────────

export interface ComponentSelections {
  applications: Record<string, boolean>
  services: Record<string, boolean>
  capabilities: Record<string, boolean>
}

// ── Loaded profile (manifest + defaults merged) ────────────────────────────

export interface LoadedProfile {
  manifest: ProfileManifest
  defaults: ProfileDefaults
}
