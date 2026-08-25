import type { Deleter, Resource, ResourceKind } from '../guards.js'
import type { FetchLike } from '../../doctor/types.js'
import { HttpError } from '../../doctor/http.js'
import { del } from '../http.js'
import { providerId } from '../inventory.js'

/**
 * The calls that actually delete something.
 *
 * Every other file in this directory tree decides *whether* to delete. This one
 * does it, and it is deliberately the smallest and dullest of them: one request
 * per provider, no logic, no retries, no discovery. Anything clever belongs on
 * the other side of the guards.
 *
 * `fetchImpl` is injected, so the whole set can be exercised against a double
 * that records what it was asked to remove. Every test in this repository does
 * exactly that -- nothing here has been run against a real provider, which is
 * stated rather than implied because the difference matters for this file more
 * than for any other.
 *
 * A 404 is success. Teardown's job is that the resource is gone; one that was
 * already gone satisfies that, and failing on it would make a re-run after a
 * partial teardown impossible.
 */

export interface ProviderCredentials {
  githubToken?: string
  dopplerToken?: string
  supabaseToken?: string
  upstashEmail?: string
  upstashApiKey?: string
  vercelToken?: string
  vercelTeamId?: string
  flyToken?: string
}

/** A 404 means the resource is not there, which is the outcome being asked for. */
async function deleteOrAlreadyGone(
  fetchImpl: FetchLike,
  url: string,
  headers: Record<string, string>,
): Promise<void> {
  try {
    await del(fetchImpl, url, headers)
  } catch (err) {
    if (err instanceof HttpError && err.status === 404) return
    throw err
  }
}

function need(value: string | undefined, name: string, kind: ResourceKind): string {
  if (!value) throw new Error(`${name} is not set, so ${kind} cannot be deleted.`)
  return value
}

/**
 * Builds the deleter for each kind.
 *
 * A kind whose credential is absent is simply not returned, and `apply` reports
 * it as skipped with the reason. That is better than a deleter that throws on
 * every call: the operator learns which credential is missing before anything
 * is attempted rather than once per resource.
 */
export function providerDeleters(
  fetchImpl: FetchLike,
  credentials: ProviderCredentials,
): Partial<Record<ResourceKind, Deleter>> {
  const deleters: Partial<Record<ResourceKind, Deleter>> = {}

  if (credentials.githubToken) {
    deleters['github-repository'] = async (resource: Resource) => {
      // `owner/name`. The guards check the name half; the owner is passed
      // through as the API needs it.
      await deleteOrAlreadyGone(
        fetchImpl,
        `https://api.github.com/repos/${providerId(resource)}`,
        {
          authorization: `Bearer ${need(credentials.githubToken, 'GITHUB_TOKEN', 'github-repository')}`,
          accept: 'application/vnd.github+json',
          'x-github-api-version': '2022-11-28',
        },
      )
    }
  }

  if (credentials.dopplerToken) {
    deleters['doppler-project'] = async (resource: Resource) => {
      // Deleting a project removes its configs with it, which is why teardown
      // models the project rather than each config.
      await deleteOrAlreadyGone(
        fetchImpl,
        `https://api.doppler.com/v3/projects/project?project=${encodeURIComponent(providerId(resource))}`,
        {
          authorization: `Bearer ${need(credentials.dopplerToken, 'DOPPLER_TOKEN', 'doppler-project')}`,
          accept: 'application/json',
        },
      )
    }
  }

  if (credentials.supabaseToken) {
    deleters['supabase-project'] = async (resource: Resource) => {
      await deleteOrAlreadyGone(
        fetchImpl,
        `https://api.supabase.com/v1/projects/${encodeURIComponent(providerId(resource))}`,
        {
          authorization: `Bearer ${need(credentials.supabaseToken, 'SUPABASE_ACCESS_TOKEN', 'supabase-project')}`,
          accept: 'application/json',
        },
      )
    }
  }

  if (credentials.upstashEmail && credentials.upstashApiKey) {
    deleters['upstash-database'] = async (resource: Resource) => {
      // Basic auth, unlike every other provider here. Upstash takes the account
      // email as the user and the API key as the password.
      const pair = `${credentials.upstashEmail}:${credentials.upstashApiKey}`
      await deleteOrAlreadyGone(
        fetchImpl,
        `https://api.upstash.com/v2/redis/database/${encodeURIComponent(providerId(resource))}`,
        {
          authorization: `Basic ${Buffer.from(pair).toString('base64')}`,
          accept: 'application/json',
        },
      )
    }
  }

  if (credentials.vercelToken) {
    deleters['vercel-project'] = async (resource: Resource) => {
      // teamId is required when the project belongs to a team rather than to
      // the token's own account, and omitting it 404s on a project that plainly
      // exists.
      const team = credentials.vercelTeamId
        ? `?teamId=${encodeURIComponent(credentials.vercelTeamId)}`
        : ''
      await deleteOrAlreadyGone(
        fetchImpl,
        `https://api.vercel.com/v9/projects/${encodeURIComponent(providerId(resource))}${team}`,
        {
          authorization: `Bearer ${need(credentials.vercelToken, 'VERCEL_API_TOKEN', 'vercel-project')}`,
          accept: 'application/json',
        },
      )
    }
  }

  if (credentials.flyToken) {
    deleters['fly-app'] = async (resource: Resource) => {
      // Fly removes the app's machines with it. An app with running machines
      // deletes without stopping them first, which is why there is no separate
      // machine step here.
      await deleteOrAlreadyGone(
        fetchImpl,
        `https://api.machines.dev/v1/apps/${encodeURIComponent(providerId(resource))}`,
        {
          authorization: `Bearer ${need(credentials.flyToken, 'FLY_API_TOKEN', 'fly-app')}`,
          accept: 'application/json',
        },
      )
    }
  }

  return deleters
}

/**
 * Kinds with no deleter, and why.
 *
 * ZITADEL is deliberately absent. Deleting one of its projects needs a token
 * minted from a service-account JWT rather than a bearer token from the
 * environment, which is a different authentication flow from every other
 * provider here and is not worth carrying for a teardown path that has never
 * run. A ZITADEL project left behind costs nothing and is visible in the
 * console; this says so rather than leaving its absence to be noticed.
 */
export const UNIMPLEMENTED_KINDS: ReadonlyArray<{ kind: string; reason: string }> = [
  {
    kind: 'zitadel-project',
    reason:
      'needs a service-account JWT exchange rather than a bearer token; delete it from the ZITADEL console',
  },
]
