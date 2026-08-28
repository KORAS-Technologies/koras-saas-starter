import type { Resource, ResourceKind } from './guards.js'

/**
 * What a provision created, read from the Terraform outputs it produced.
 *
 * The alternative is asking each provider to list everything and filtering by
 * name, and it is worse in both directions: it can miss a resource whose name
 * does not match the pattern, and it can match one that was never ours. State
 * is the record of what this configuration actually made.
 *
 * Takes the parsed outputs rather than raw JSON, so a value Terraform marked
 * sensitive cannot arrive here -- the parser drops those, and a teardown has no
 * business holding a credential in the first place.
 */

export interface ProvisionOutputsLike {
  githubRepository: string
  dopplerProject: string
  supabaseProjectRefs: Record<string, string>
  zitadelProjectIds: Record<string, string>
  /**
   * Required, for the reason redisDatabaseIds below is.
   *
   * A ZITADEL project id is not enough to delete by. Without the organization
   * the delete lands in whichever one the token belongs to, and an id that is
   * not there answers 404 -- which this code reads as "already gone" and counts
   * as a success. Optional would mean every caller could omit it and get that
   * outcome silently.
   */
  zitadelOrgIds: Record<string, string>
  /**
   * Which instance holds each environment's project.
   *
   * Required for the same reason: ZITADEL is self-hosted per environment, so
   * there is no single API to fall back to.
   */
  zitadelDomains: Record<string, string>
  /**
   * Hostname -> Cloudflare DNS record id, and the zone holding them.
   *
   * Required, like the two above and for the same reason -- except this one was
   * not optional, it was absent. The module exported record_ids all along and
   * nothing above it asked, so eight records outlived an estate.
   */
  cloudflareRecordIds: Record<string, string>
  cloudflareZoneId: string
  /**
   * The HCP Terraform workspace holding this estate's state, and its org.
   *
   * Not a `terraform output` -- it is read from the project's own backend.tf,
   * which is where the generator renders it. Teardown never invokes Terraform,
   * so nothing else would remove the workspace, and it was the last thing on
   * the "delete this by hand" list.
   *
   * Deleted last. It is the record of what everything else was, and a run that
   * fails halfway is easier to finish while the state still describes the
   * estate.
   */
  terraformOrganization: string
  terraformWorkspace: string
  vercelProjectIds: Record<string, string>
  flyApps: string[]
  /**
   * Required, not optional.
   *
   * It was optional, and the module exported no such output, so
   * `outputs.redisDatabaseIds` was always undefined and Upstash never entered
   * the inventory. Teardown reported "26 deletable, 0 retained" and left four
   * billing databases alive -- a complete-looking run, missing a whole
   * provider, with nothing to notice.
   *
   * Optional here means "the caller may omit it", and every caller did.
   * Required makes a missing output a type error at the boundary instead of an
   * absence discovered from a bill.
   */
  redisDatabaseIds: Record<string, string>
}

/**
 * Deletion order.
 *
 * Roughly most-dependent first. Nothing here strictly requires it -- these are
 * separate providers with no foreign keys between them -- but a Fly app removed
 * before the Doppler config holding its credentials means a half-torn-down
 * estate reads in the order somebody would fix it.
 */
const ORDER: ResourceKind[] = [
  // First: a DNS record pointing at an application that no longer exists is the
  // one leftover a visitor can see.
  'cloudflare-record',
  'fly-app',
  'vercel-project',
  'upstash-database',
  'supabase-project',
  'zitadel-project',
  'doppler-project',
  'github-repository',
  // Last: it is the record of what the rest were.
  'terraform-workspace',
]

export function inventoryFromOutputs(outputs: ProvisionOutputsLike): Resource[] {
  const found: Resource[] = []

  const add = (
    kind: ResourceKind,
    name: string | undefined,
    extra: {
      endpoint?: string
      scope?: string
      environment?: string
      providerId?: string
    } = {},
  ): void => {
    if (name && name.trim() !== '') found.push({ kind, name: name.trim(), ...extra })
  }

  for (const name of outputs.flyApps) add('fly-app', name)
  for (const id of Object.values(outputs.vercelProjectIds)) add('vercel-project', id)
  for (const id of Object.values(outputs.redisDatabaseIds)) add('upstash-database', id)
  for (const ref of Object.values(outputs.supabaseProjectRefs)) add('supabase-project', ref)
  // Paired by environment, because that is the only thing that relates them.
  // An environment with a project and no org is kept rather than dropped: it
  // still needs deleting, and the deleter says so plainly instead of this
  // silently shortening the inventory.
  for (const [env, id] of Object.entries(outputs.zitadelProjectIds)) {
    add('zitadel-project', id, {
      endpoint: outputs.zitadelDomains[env],
      scope: outputs.zitadelOrgIds[env],
      environment: env,
    })
  }
  for (const [hostname, id] of Object.entries(outputs.cloudflareRecordIds)) {
    // Guarded by hostname, which carries the project name, and deleted by id.
    add('cloudflare-record', hostname, { providerId: id, scope: outputs.cloudflareZoneId })
  }
  add('doppler-project', outputs.dopplerProject)
  add('github-repository', outputs.githubRepository)
  add('terraform-workspace', outputs.terraformWorkspace, {
    scope: outputs.terraformOrganization,
  })

  const rank = new Map(ORDER.map((kind, index) => [kind, index]))
  return found.sort((a, b) => (rank.get(a.kind) ?? 0) - (rank.get(b.kind) ?? 0))
}

/**
 * The guards check names, and several of these are opaque ids.
 *
 * A Supabase ref, a Vercel project id and an Upstash database id carry no
 * project name, so `koras-e2e-` cannot appear in them and the prefix guard
 * would refuse every one. The guard is right and the input is wrong: what makes
 * those safe to delete is the *project* they belong to, which is known here and
 * lost by the time a bare id reaches the guard.
 *
 * So an id-shaped resource is given a guarded name derived from the project,
 * and keeps the id in `providerId` for the call. Nothing is weakened: a project
 * not named `koras-e2e-` still fails the guard.
 */
export function qualify(resources: Resource[], projectSlug: string): Resource[] {
  const opaque: ResourceKind[] = [
    'supabase-project',
    'vercel-project',
    'upstash-database',
    'zitadel-project',
  ]

  return resources.map((resource) =>
    opaque.includes(resource.kind)
      ? { ...resource, name: `${projectSlug}-${resource.kind}-${resource.name}`, providerId: resource.name }
      : resource,
  )
}

/** What to send the provider: the id when there is one, else the name. */
export function providerId(resource: Resource): string {
  return resource.providerId ?? resource.name
}
