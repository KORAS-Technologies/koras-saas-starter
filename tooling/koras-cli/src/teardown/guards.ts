/**
 * The rules governing deletion of acceptance-run infrastructure.
 *
 * These are the guards, and nothing here issues a provider call: `apply` takes
 * its deleters as arguments. `providers/` holds the implementations and
 * `run.ts` wires the two together, so this file can be read and reviewed as
 * what it is -- the answer to "may this name be deleted at all" -- without
 * anything that could act on the answer.
 *
 * Moved here from `tests/e2e/helpers/` when `koras teardown` needed it. It had
 * lived beside the acceptance tests, which made it look like test scaffolding;
 * it is the safety mechanism of a destructive command and belongs with the
 * command.
 *
 * This is the one part of the repository whose job is destruction, so it is
 * written to refuse rather than to succeed. Four independent guards stand
 * between a call and a deleted resource, and each is there because the failure
 * it prevents is unrecoverable.
 */

/** Every acceptance-run resource is named with this. Nothing else is deletable. */
export const E2E_PREFIX = 'koras-e2e-'

/**
 * Names that must survive any teardown, whatever else is true.
 *
 * None of these begins with the prefix, so the first guard already excludes
 * them. They are listed anyway: this file is the one place where a copy-paste
 * error deletes a production estate, and a redundant check costs nothing
 * against that.
 */
export const PROTECTED_NAMES = [
  'koras-control-plane',
  'koras-saas-starter',
  'sample-product',
  'docoris',
  'dianova',
  'legalapp',
] as const

/**
 * The kinds a provision creates.
 *
 * `zitadel-project` was listed here for a while with nothing to delete it, so
 * that an inventory could not report a complete teardown while leaving projects
 * behind. It has a deleter now, and the reason it did not is worth keeping: the
 * blocker recorded was "needs a service-account JWT exchange rather than a
 * bearer token", and that was simply untrue -- the same personal access token
 * the local provisioner already sends as `Authorization: Bearer` works against
 * the management API. Nothing tested the claim because nothing could: it was a
 * comment explaining an absence.
 */
export type ResourceKind =
  | 'github-repository'
  | 'doppler-project'
  | 'supabase-project'
  | 'upstash-database'
  | 'vercel-project'
  | 'fly-app'
  | 'zitadel-project'

export interface Resource {
  kind: ResourceKind
  /**
   * The name the guards judge.
   *
   * For most kinds this is also what the provider knows it by. For an opaque
   * id -- a Supabase ref, a Vercel project id -- it is the project slug joined
   * to that id, because an id contains no project name and the prefix guard
   * would refuse every one of them. What makes those safe to delete is the
   * project they belong to, so that is what the guard is given.
   */
  name: string
  /**
   * What to send the provider, when it differs from the guarded name.
   *
   * Kept separate rather than parsed back out of `name`: a GitHub repository is
   * `owner/repo` and splitting on the slash would hand the API a bare repo
   * name. Two meanings in one string is how that mistake gets made.
   */
  providerId?: string
  /**
   * Which instance the call goes to, for a provider that is not one global API.
   *
   * Every other provider here has a single endpoint, so the base URL is a
   * constant in the deleter. ZITADEL is self-hosted per environment, so the
   * inventory has to say which of four instances a project belongs to; a
   * constant would delete from whichever one was hardcoded.
   */
  endpoint?: string
  /**
   * The account or organization the call must act in.
   *
   * Only meaningful where the credential's own default context is not the right
   * one, which so far is ZITADEL alone. Its management API acts in the
   * organization of whoever holds the token, and an instance with two
   * organizations answers 404 for a project in the other -- indistinguishable
   * from a project that has already been deleted, and read as success.
   */
  scope?: string
  /**
   * Which environment produced it, where the credential differs per environment.
   *
   * Only ZITADEL so far, and not a stylistic choice: dev, test, stg and prod are
   * four separate ZITADEL instances, each with its own machine user. One token
   * cannot reach all four however it is obtained, so the token has to be chosen
   * per resource the way the endpoint already is.
   */
  environment?: string
}

export interface TeardownPlan {
  /** Safe to delete: correctly prefixed, not protected. */
  deletable: Resource[]
  /** Left alone, with the reason. Their presence does not stop the rest. */
  retained: Array<{ resource: Resource; reason: string }>
}

export function isDeletable(name: string): { ok: true } | { ok: false; reason: string } {
  const trimmed = name.trim()

  if (trimmed === '') return { ok: false, reason: 'the name is empty' }

  if (!trimmed.startsWith(E2E_PREFIX)) {
    return { ok: false, reason: `"${trimmed}" is not an acceptance-run resource (no ${E2E_PREFIX} prefix)` }
  }

  // A prefixed name that is only the prefix would match a great many things in
  // a provider that treats the argument as a filter rather than an identity.
  if (trimmed === E2E_PREFIX) {
    return { ok: false, reason: 'the name is the bare prefix, which identifies no single resource' }
  }

  for (const protectedName of PROTECTED_NAMES) {
    if (trimmed === protectedName || trimmed.endsWith(`/${protectedName}`)) {
      return { ok: false, reason: `"${trimmed}" is a protected estate resource` }
    }
  }

  // Path traversal and wildcards reach further than the caller named. A
  // provider that interpolates this into a URL would act on something else.
  if (/[*?]|\.\./.test(trimmed)) {
    return { ok: false, reason: `"${trimmed}" contains a wildcard or traversal sequence` }
  }

  return { ok: true }
}

/** Sorts an inventory into what may be deleted and what must not be. Pure. */
export function plan(inventory: Resource[]): TeardownPlan {
  const deletable: Resource[] = []
  const retained: Array<{ resource: Resource; reason: string }> = []

  for (const resource of inventory) {
    // A GitHub repository is `owner/name`; only the name is the identity the
    // prefix rule applies to.
    const identity = resource.kind === 'github-repository' ? resource.name.split('/').pop() ?? '' : resource.name
    const verdict = isDeletable(identity)
    if (verdict.ok) deletable.push(resource)
    else retained.push({ resource, reason: verdict.reason })
  }

  return { deletable, retained }
}

export interface DeleteResult {
  resource: Resource
  status: 'deleted' | 'failed' | 'skipped'
  detail?: string
}

export type Deleter = (resource: Resource) => Promise<void>

export interface ApplyOptions {
  /** Provider calls, injected so the guards can be tested without a provider. */
  deleters: Partial<Record<ResourceKind, Deleter>>
  env?: NodeJS.ProcessEnv
}

/** Whether teardown is permitted to delete anything at all. */
export function teardownEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
  return env.KORAS_E2E_TEARDOWN === '1'
}

/**
 * Deletes the deletable half of a plan.
 *
 * Every resource is re-checked immediately before its own delete call. The
 * plan was produced earlier and may have been filtered, mapped, or
 * concatenated since; re-checking means the guard applies to the argument
 * actually being deleted rather than to the list it once belonged to.
 *
 * One failure does not stop the rest. A half-torn-down estate is worse than a
 * fully torn-down one, and the caller gets every result to report.
 */
export async function apply(plan: TeardownPlan, options: ApplyOptions): Promise<DeleteResult[]> {
  const results: DeleteResult[] = []

  if (!teardownEnabled(options.env)) {
    return plan.deletable.map((resource) => ({
      resource,
      status: 'skipped' as const,
      detail: 'KORAS_E2E_TEARDOWN is not set to 1; nothing was deleted.',
    }))
  }

  for (const resource of plan.deletable) {
    const identity =
      resource.kind === 'github-repository' ? resource.name.split('/').pop() ?? '' : resource.name
    const verdict = isDeletable(identity)
    if (!verdict.ok) {
      results.push({ resource, status: 'skipped', detail: verdict.reason })
      continue
    }

    const deleter = options.deleters[resource.kind]
    if (!deleter) {
      results.push({ resource, status: 'skipped', detail: `no deleter for ${resource.kind}` })
      continue
    }

    try {
      await deleter(resource)
      results.push({ resource, status: 'deleted' })
    } catch (err) {
      results.push({
        resource,
        status: 'failed',
        detail: err instanceof Error ? err.message : String(err),
      })
    }
  }

  return results
}

/** A human-readable account of what teardown did or would do. */
export function formatPlan(plan: TeardownPlan, results?: DeleteResult[]): string {
  const lines: string[] = []

  lines.push(`Teardown — ${plan.deletable.length} deletable, ${plan.retained.length} retained`)

  for (const resource of plan.deletable) {
    const result = results?.find((r) => r.resource === resource)
    lines.push(`  ${result?.status ?? 'planned'}  ${resource.kind}  ${resource.name}`)
    if (result?.detail) lines.push(`      ${result.detail}`)
  }

  for (const { resource, reason } of plan.retained) {
    lines.push(`  retained  ${resource.kind}  ${resource.name}`)
    lines.push(`      ${reason}`)
  }

  return lines.join('\n')
}
