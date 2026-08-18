import type { FetchLike, HttpResponse } from './types.js'

/**
 * Read-only HTTP for the provider checks.
 *
 * Every request the doctor makes is a GET, or the one POST that ZITADEL's
 * token endpoint and Fly's GraphQL API require to answer a read. Nothing here
 * can create, modify, or delete a resource.
 */

export interface RequestOptions {
  method?: 'GET' | 'POST'
  headers?: Record<string, string>
  body?: string
  /** Abandon the request rather than hanging the whole doctor run. */
  timeoutMs?: number
}

export const DEFAULT_TIMEOUT_MS = 15_000

export class HttpError extends Error {
  constructor(
    readonly status: number,
    readonly body: string,
  ) {
    super(`HTTP ${status}`)
  }
}

/**
 * Performs a request and returns the body, throwing `HttpError` on a non-2xx.
 *
 * The body is returned as text rather than parsed JSON so that a provider
 * returning HTML (a proxy error page, a captive portal) does not surface as a
 * confusing JSON parse failure.
 */
export async function request(
  fetchImpl: FetchLike,
  url: string,
  options: RequestOptions = {},
): Promise<string> {
  const response: HttpResponse = await withTimeout(
    fetchImpl(url, {
      method: options.method ?? 'GET',
      headers: options.headers,
      body: options.body,
    }),
    options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    url,
  )

  const body = await response.text()
  if (!response.ok) throw new HttpError(response.status, body)
  return body
}

export async function requestJson<T = unknown>(
  fetchImpl: FetchLike,
  url: string,
  options: RequestOptions = {},
): Promise<T> {
  const body = await request(fetchImpl, url, options)
  try {
    return JSON.parse(body) as T
  } catch {
    throw new Error(`${url} did not return JSON.`)
  }
}

function withTimeout<T>(promise: Promise<T>, ms: number, url: string): Promise<T> {
  let timer: NodeJS.Timeout
  const host = safeHost(url)
  return Promise.race([
    promise.finally(() => clearTimeout(timer)),
    new Promise<T>((_, reject) => {
      timer = setTimeout(() => reject(new Error(`${host} did not respond within ${ms}ms.`)), ms)
      // Do not hold the process open on the timer alone.
      timer.unref?.()
    }),
  ])
}

/** Hostname only — a full URL may carry a token in its query string. */
export function safeHost(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return 'the endpoint'
  }
}
