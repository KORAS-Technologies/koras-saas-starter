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

/**
 * The first name that holds a value.
 *
 * The estate stores several of these under a `TF_VAR_` prefix, because
 * Terraform needed them as variables before teardown needed them as
 * credentials. Reading only the bare name is how Upstash came to be skipped on
 * a real estate: `UPSTASH_EMAIL` was unset, `TF_VAR_UPSTASH_EMAIL` held the
 * value, and teardown reported "credential not set" and moved on -- leaving
 * four databases that bill. The same shape as R-040, one layer up: a lookup
 * that finds nothing and a run that calls itself complete.
 */
function first(env: NodeJS.ProcessEnv, ...names: string[]): string | undefined {
  for (const name of names) {
    const value = env[name]
    if (value !== undefined && value.trim() !== '') return value
  }
  return undefined
}

/**
 * Per-instance ZITADEL tokens, keyed by environment.
 *
 * Absent environments are simply not in the map: the deleter refuses a resource
 * whose environment it holds no token for, by name, rather than reaching for
 * another instance's credential.
 */
function zitadelTokensFromEnv(env: NodeJS.ProcessEnv): Record<string, string> {
  const shared = first(env, 'ZITADEL_SERVICE_TOKEN')
  const tokens: Record<string, string> = {}
  for (const name of ['dev', 'test', 'stg', 'prod']) {
    const token = first(env, `ZITADEL_${name.toUpperCase()}_SERVICE_TOKEN`) ?? shared
    if (token) tokens[name] = token
  }
  return tokens
}

/** Reads provider credentials from the environment, naming none of their values. */
export function credentialsFromEnv(env: NodeJS.ProcessEnv = process.env): ProviderCredentials {
  return {
    githubToken: first(env, 'GITHUB_TOKEN', 'TF_VAR_GITHUB_TOKEN'),
    dopplerToken: first(env, 'DOPPLER_TOKEN', 'TF_VAR_DOPPLER_TOKEN'),
    supabaseToken: first(env, 'SUPABASE_ACCESS_TOKEN', 'TF_VAR_SUPABASE_ACCESS_TOKEN'),
    upstashEmail: first(env, 'UPSTASH_EMAIL', 'TF_VAR_UPSTASH_EMAIL'),
    upstashApiKey: first(env, 'UPSTASH_API_KEY', 'TF_VAR_UPSTASH_API_KEY'),
    vercelToken: first(env, 'VERCEL_API_TOKEN', 'TF_VAR_VERCEL_TOKEN'),
    vercelTeamId: first(env, 'VERCEL_TEAM_ID', 'TF_VAR_VERCEL_TEAM_ID'),
    flyToken: first(env, 'FLY_API_TOKEN', 'TF_VAR_FLY_API_TOKEN'),
    // One personal access token per instance, as ZITADEL_<ENV>_SERVICE_TOKEN.
    //
    // Named after the instance because there are four of them. The estate's
    // ZITADEL_<ENV>_SERVICE_ACCOUNT_KEY_JSON is a different thing -- a JWT
    // profile, which this does not exchange -- so these are created for the
    // purpose, the same way koras-control-plane holds one per environment for
    // its own provisioning.
    //
    // A bare ZITADEL_SERVICE_TOKEN is accepted as a fallback for every
    // environment. That suits a single-instance estate and is wrong for this
    // one; it is a fallback rather than the documented form for that reason.
    zitadelServiceTokens: zitadelTokensFromEnv(env),
    cloudflareApiToken: first(env, 'CLOUDFLARE_API_TOKEN', 'TF_VAR_CLOUDFLARE_API_TOKEN'),
    terraformToken: first(env, 'TF_TOKEN_APP_TERRAFORM_IO', 'TFE_TOKEN'),
  }
}
