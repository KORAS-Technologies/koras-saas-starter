import type { FetchLike } from '../doctor/types.js'
import { apply, plan, formatPlan, teardownEnabled, type Resource, type DeleteResult } from './guards.js'
import { providerDeleters, UNIMPLEMENTED_KINDS, type ProviderCredentials } from './providers/index.js'
import { confirmTeardown, type ConfirmOptions } from './confirm.js'

/**
 * The teardown command, assembled from parts that each refuse on their own.
 *
 * Order matters and is the whole design: decide what may be deleted, report it,
 * and only then -- if explicitly enabled -- delete. A caller who stops after
 * the first two steps has a dry run, which is the default.
 */

export interface TeardownOptions {
  inventory: Resource[]
  credentials: ProviderCredentials
  fetchImpl: FetchLike
  env?: NodeJS.ProcessEnv
  /** Named on the prompt, and what the operator must type back. */
  projectSlug: string
  /** Injected for tests. Without it, a real TTY is required. */
  confirm?: ConfirmOptions
}

export interface TeardownOutcome {
  output: string
  /** True when something was attempted and failed. A dry run is never failed. */
  failed: boolean
}

export async function teardown(options: TeardownOptions): Promise<TeardownOutcome> {
  const env = options.env ?? process.env
  const decided = plan(options.inventory)
  const enabled = teardownEnabled(env)

  const lines: string[] = []

  if (!enabled) {
    lines.push(
      'DRY RUN — nothing will be deleted.',
      '',
      'Set KORAS_E2E_TEARDOWN=1 to delete what is listed below.',
      '',
    )
  }

  const deleters = providerDeleters(options.fetchImpl, options.credentials)

  // Named before anything runs, so a missing credential is one line at the top
  // rather than one failure per resource.
  const missing = [...new Set(decided.deletable.map((r) => r.kind))]
    .filter((kind) => !deleters[kind])
    .sort()

  if (missing.length > 0) {
    lines.push('No deleter for these kinds; they will be skipped:')
    for (const kind of missing) {
      const known = UNIMPLEMENTED_KINDS.find((u) => u.kind === kind)
      lines.push(`  ${kind} — ${known ? known.reason : 'credential not set'}`)
    }
    lines.push('')
  }

  let results: DeleteResult[] | undefined
  if (enabled && decided.deletable.length > 0) {
    // After the plan and before the deletion, so what is confirmed is what was
    // just described rather than what was asked for.
    const confirmed = await confirmTeardown(
      options.projectSlug,
      decided.deletable,
      options.confirm ?? {},
    )
    if (!confirmed) {
      const cancelled = [...lines, formatPlan(decided), '', 'Cancelled.']
      return { output: cancelled.join(String.fromCharCode(10)), failed: false }
    }
    results = await apply(decided, { deleters, env })
  }

  lines.push(formatPlan(decided, results))

  const failed = (results ?? []).some((r) => r.status === 'failed')
  if (failed) {
    lines.push('', 'Some deletions failed. Nothing was rolled back; re-running is safe.')
  }

  return { output: lines.join('\n'), failed }
}

/** Reads provider credentials from the environment, naming none of their values. */
export function credentialsFromEnv(env: NodeJS.ProcessEnv = process.env): ProviderCredentials {
  return {
    githubToken: env.GITHUB_TOKEN,
    dopplerToken: env.DOPPLER_TOKEN,
    supabaseToken: env.SUPABASE_ACCESS_TOKEN,
    upstashEmail: env.UPSTASH_EMAIL,
    upstashApiKey: env.UPSTASH_API_KEY,
    vercelToken: env.VERCEL_API_TOKEN,
    vercelTeamId: env.VERCEL_TEAM_ID,
    flyToken: env.FLY_API_TOKEN,
    // The same secret the Control Plane provisions ZITADEL with. Deliberately
    // the same one: a second credential able to delete projects would be a
    // second thing to rotate and one more to forget.
    zitadelServiceToken: env.ZITADEL_SERVICE_TOKEN,
  }
}
