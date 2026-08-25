/**
 * The rules governing deletion of the infrastructure an acceptance run creates.
 *
 * **This module deletes nothing.** Every `Deleter` is injected, and no provider
 * implementation exists anywhere in the repository, so the tests below exercise
 * the guards against stubs. Read that as the current state rather than as a
 * design: the guards are the part worth having first, because they are what a
 * real deleter would have to pass through, but a live acceptance run cannot be
 * cleaned up by this file today.
 *
 * It also knows three resource kinds against the seven providers a provision
 * writes to. Upstash, ZITADEL, Vercel and Fly are absent, and `prevent_destroy`
 * is set on five resource types, so `terraform destroy` is not an alternative
 * either. See Phase 13 in IMPLEMENTATION_ROADMAP.md.
 *
 * This is the one helper in the repository whose job is destruction, so it is
 * written to refuse rather than to succeed. Four independent guards stand
 * between a call and a deleted resource, and each is there because the failure
 * it prevents is unrecoverable:
 *
 *  1. **A name prefix.** Only resources named `koras-e2e-...` can be deleted.
 *     A test that provisioned `docoris` cannot tear down `docoris`; it fails
 *     the run instead and leaves the resource for a human. This is the guard
 *     that matters, because it holds even when every other one is misused.
 *  2. **An explicit opt-in.** `KORAS_E2E_TEARDOWN=1`. Absent, the helper
 *     reports what it would delete and deletes nothing.
 *  3. **Dry run by default.** `plan()` is a pure function over the inventory.
 *     `apply()` is the only thing that issues a DELETE.
 *  4. **A protected list.** Names the estate must never lose, checked after
 *     the prefix rule rather than instead of it — belt and braces on the one
 *     mistake that cannot be undone.
 *
 * Nothing here runs during an ordinary `pnpm test`. The acceptance tests that
 * call it are themselves gated behind `KORAS_E2E_LIVE=1`.
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

export type ResourceKind = 'github-repository' | 'doppler-project' | 'supabase-project'

export interface Resource {
  kind: ResourceKind
  /** The name or ref the provider knows it by. */
  name: string
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
