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

// ── Profile manifest ───────────────────────────────────────────────────────

export const ProfileManifestSchema = z.object({
  schema_version: z.literal('1'),
  profile: z.enum(['product', 'control-plane']),
  applications: z.record(z.string(), ApplicationSchema),
  services: z.record(z.string(), ServiceSchema),
  capabilities: z.record(z.string(), z.boolean()),
  registration: RegistrationSchema,
  infrastructure: InfrastructureSchema,
  environments: z.array(z.string()),
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
    })
    .optional(),
  output: z
    .object({
      include_example_env: z.boolean().optional(),
      include_docker_compose: z.boolean().optional(),
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
