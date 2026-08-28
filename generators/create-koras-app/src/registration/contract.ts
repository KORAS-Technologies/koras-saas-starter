import type { GenerationContext } from '../generation/context.js'
import {
  resolveStarterVersion,
  resolveProfileVersion,
} from '../generation/project-manifest.js'
import { primaryDomain } from '../generation/context.js'
import type { ProvisionOutputs } from '../terraform/outputs.js'

/**
 * The registration payload, as the Control Plane defines it.
 *
 * **Specification:** `koras-control-plane/docs/PRODUCT_REGISTRATION_CONTRACT.md`.
 * That document is authoritative for both directions — what this file sends,
 * and the Product Platform API a product must serve so the Control Plane can
 * call back into it. Where it and this file disagree, it is right and this is
 * the bug. The pointer is here because its absence had a cost: a second
 * document describing this contract was written in the Control Plane
 * repository, contradicting the real one in four places, because nothing
 * connected an implementation to its specification.
 *
 * Mirrors `ProductRegistrationRequest` in the Control Plane's
 * `schemas/product.py`, which sets `extra="forbid"` — so a field this side
 * invents is not ignored, it is a 422. That strictness is the reason these
 * types are written against the schema rather than around it.
 *
 * References only. The Control Plane stores pointers to infrastructure and
 * never the credentials for it, enforced there by a schema with no field for
 * one and enforced here by building the payload from outputs Terraform did not
 * mark sensitive. Two independent checks for the same rule, because a payload
 * that leaks a credential leaks it to a database, an audit log and a backup at
 * once.
 */

/** Matches the Control Plane's `InfrastructureReferences`. */
export interface InfrastructureReferences {
  github_repository?: string
  doppler_project?: string
  doppler_config?: string
  supabase_project_ref?: string
  supabase_api_url?: string
  zitadel_instance?: string
  zitadel_project_id?: string
  zitadel_client_id?: string
  vercel_projects?: Record<string, string>
  fly_apps?: Record<string, string>
  cloudflare_zone_id?: string
  platform_api_base_url?: string
}

/** Matches the Control Plane's `ProductEnvironmentSpec`. */
export interface ProductEnvironmentSpec {
  infrastructure: InfrastructureReferences
  services: string[]
}

/** Matches the Control Plane's `ProductRegistrationRequest`. */
export interface ProductRegistration {
  code: string
  name: string
  slug: string
  repository?: string
  profile: string
  primary_domain?: string
  starter_version?: string
  profile_version?: string
  environments: Record<string, ProductEnvironmentSpec>
}

/**
 * Fly app names for one environment, keyed by service.
 *
 * The outputs carry a flat list of `<slug>-<service>-<env>` names because that
 * is what Terraform emits. The Control Plane wants a map per environment, and
 * the service is the part in the middle — recovered by removing the two ends
 * rather than by splitting on hyphens, since a slug may contain them.
 */
function flyAppsFor(environment: string, slug: string, names: string[]): Record<string, string> {
  const prefix = `${slug}-`
  const suffix = `-${environment}`
  const apps: Record<string, string> = {}

  for (const name of names) {
    if (!name.startsWith(prefix) || !name.endsWith(suffix)) continue
    const service = name.slice(prefix.length, name.length - suffix.length)
    if (service !== '') apps[service] = name
  }
  return apps
}

/** Vercel project ids for one environment, keyed by application. */
function vercelProjectsFor(
  environment: string,
  ids: Record<string, string>,
): Record<string, string> {
  const suffix = `-${environment}`
  const projects: Record<string, string> = {}

  for (const [key, id] of Object.entries(ids)) {
    if (!key.endsWith(suffix)) continue
    projects[key.slice(0, key.length - suffix.length)] = id
  }
  return projects
}

/** Drops undefined members, so an absent reference is absent rather than null. */
function present<T extends object>(value: T): T {
  return Object.fromEntries(Object.entries(value).filter(([, v]) => v !== undefined)) as T
}

/**
 * Build the payload for a provisioned project.
 *
 * Deliberately takes the parsed outputs rather than raw Terraform JSON: the
 * parser has already dropped every output Terraform marked sensitive, so a
 * credential cannot reach here even by mistake. `zitadel_client_id` is a field
 * the Control Plane accepts and this does not send, because the Terraform
 * output carrying it is marked sensitive — un-marking an output so a payload
 * can carry it is exactly the trade this contract exists to refuse.
 */
export function buildRegistration(
  ctx: GenerationContext,
  outputs: ProvisionOutputs,
): ProductRegistration {
  const environments: Record<string, ProductEnvironmentSpec> = {}
  const services = Object.entries(ctx.selections.services)
    .filter(([, on]) => on)
    .map(([name]) => name)
    .sort()

  for (const environment of ctx.manifest.environments) {
    environments[environment] = {
      infrastructure: present({
        github_repository: outputs.githubRepository || undefined,
        doppler_project: outputs.dopplerProject || undefined,
        doppler_config: environment,
        supabase_project_ref: outputs.supabaseProjectRefs[environment],
        zitadel_instance: environment,
        zitadel_project_id: outputs.zitadelProjectIds[environment],
        vercel_projects: vercelProjectsFor(environment, outputs.vercelProjectIds),
        fly_apps: flyAppsFor(environment, ctx.projectSlug, outputs.flyApps),
      }),
      services,
    }
  }

  const domain = primaryDomain(ctx)

  return present({
    // `code` is the registry's stable identity for the product and `slug` is
    // what its infrastructure is named after. They are the same value here
    // because the generator has no separate notion of a product code, and
    // sending one that disagreed with the other would make the registry
    // disagree with the estate.
    code: ctx.projectSlug,
    name: ctx.projectName,
    slug: ctx.projectSlug,
    repository: outputs.githubRepository || undefined,
    profile: ctx.profile,
    primary_domain: domain || undefined,
    // The contract's reason for holding these: they record what each product
    // was generated from, so the Control Plane can identify the ones needing
    // an upgrade. The fields were declared on the interface from the start and
    // never populated, so every product registered so far reads as generated
    // from nothing in particular -- and the registry column is overwritten from
    // the request, so a later registration that omitted them would blank a
    // correct value rather than leave it alone.
    starter_version: resolveStarterVersion(),
    profile_version: resolveProfileVersion(ctx),
    environments,
  })
}
