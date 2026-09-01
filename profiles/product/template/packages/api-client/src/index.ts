/**
 * The typed client for this product's own API.
 *
 * One place that knows how a call to `services/api` is made: where the base URL
 * comes from, how the caller's credentials are attached, how long to wait, and
 * what a failure looks like. The alternative — a `fetch` in whichever component
 * needed the data — is how five call sites end up with four opinions about
 * timeouts and none about errors.
 *
 * Deliberately free of React, of `next/*` and of the branding package. It is
 * called from server components and from server actions, and a client that
 * imported a framework could only be used from one of them.
 *
 * It also carries no types from `@<slug>/branding`, which is why this file
 * needs no template rendering: the API's response shape is the API's, and the
 * browser tier's parsers are what turn it into brand tokens. Keeping the two
 * separate is what lets the parser reject a value the API happily returned.
 */

/** How long any call may take before it is abandoned. */
const DEFAULT_TIMEOUT_MS = 5_000

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/**
 * A customer's own tenant, as the API returns it.
 *
 * `branding` and `features` are deliberately `unknown`. They are customer-
 * controlled `jsonb`, so typing them as anything more specific here would be a
 * claim this client cannot support — and the callers already pass both through
 * validating parsers before either reaches a stylesheet or a navigation gate.
 */
export interface TenantSettings {
  name: string
  slug: string
  branding: unknown
  features: unknown
}

export interface RequestOptions {
  /** Origin of this product's API. */
  baseUrl: string
  /**
   * The caller's own provider token.
   *
   * Not the session cookie this application signed: the API verifies against
   * ZITADEL and deliberately does not trust the browser tier to have done so.
   * And not a service credential — a call made on behalf of a person should be
   * attributed to that person.
   */
  token: string
  timeoutMs?: number
  /** Injectable for tests. Defaults to the global. */
  fetchImpl?: typeof fetch
}

async function request<T>(path: string, options: RequestOptions): Promise<T> {
  const base = options.baseUrl.replace(/\/$/, '')
  if (!base) throw new ApiError('no API base URL is configured', 0)

  // An abort rather than a bare await. A page rendering on the server has no
  // user to cancel it, so a hung API call is a hung page render — and the
  // symptom is a timeout somewhere upstream that names the wrong thing.
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? DEFAULT_TIMEOUT_MS)

  try {
    const response = await (options.fetchImpl ?? fetch)(`${base}${path}`, {
      headers: {
        Authorization: `Bearer ${options.token}`,
        Accept: 'application/json',
      },
      // Never cached at this layer. The response is per-tenant and per-caller,
      // and a shared cache keyed on a URL that carries neither is how one
      // customer is served another's settings. A caller that wants caching
      // should ask for it where it knows the key.
      cache: 'no-store',
      signal: controller.signal,
    })

    if (!response.ok) {
      throw new ApiError(`${path} answered ${response.status}`, response.status)
    }
    return (await response.json()) as T
  } finally {
    clearTimeout(timer)
  }
}

/**
 * This caller's own tenant settings.
 *
 * Takes no tenant identifier, and there is nowhere to put one: the API resolves
 * the tenant from the token and scopes the read with row-level security. A
 * client that could name a tenant would be a client somebody could point at
 * another one.
 */
export function fetchTenantSettings(options: RequestOptions): Promise<TenantSettings> {
  return request<TenantSettings>('/api/v1/tenant/settings', options)
}
