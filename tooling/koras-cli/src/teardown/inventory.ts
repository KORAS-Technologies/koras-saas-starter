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
  vercelProjectIds: Record<string, string>
  flyApps: string[]
  redisDatabaseIds?: Record<string, string>
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
  'fly-app',
  'vercel-project',
  'upstash-database',
  'supabase-project',
  'zitadel-project',
  'doppler-project',
  'github-repository',
]

export function inventoryFromOutputs(outputs: ProvisionOutputsLike): Resource[] {
  const found: Resource[] = []

  const add = (kind: ResourceKind, name: string | undefined): void => {
    if (name && name.trim() !== '') found.push({ kind, name: name.trim() })
  }

  for (const name of outputs.flyApps) add('fly-app', name)
  for (const id of Object.values(outputs.vercelProjectIds)) add('vercel-project', id)
  for (const id of Object.values(outputs.redisDatabaseIds ?? {})) add('upstash-database', id)
  for (const ref of Object.values(outputs.supabaseProjectRefs)) add('supabase-project', ref)
  for (const id of Object.values(outputs.zitadelProjectIds)) add('zitadel-project', id)
  add('doppler-project', outputs.dopplerProject)
  add('github-repository', outputs.githubRepository)

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
