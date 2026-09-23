import { redact } from '../redact.js'
import { idempotencyKey } from './keys.js'

/**
 * The payment provider, reached over its REST API with no SDK.
 *
 * No SDK because this makes four kinds of call and an SDK would be a
 * dependency in the factory carrying a provider's whole surface area — every
 * one of which this process would then be authorised to make. Four calls
 * written out is less code than the dependency, and what it can do is visible
 * by reading it.
 *
 * The rules, all of which come from this running against an account that holds
 * real money:
 *
 *  - **It never deletes and never archives.** A price that is superseded keeps
 *    existing, unreferenced. Deletion is the one mistake no retry undoes, and
 *    an orphaned price costs nothing.
 *  - **It never mutates an amount.** A provider price is immutable in amount by
 *    design, so "correcting" one means creating another and repointing the
 *    plan. That is what happens, and it is reported rather than done quietly.
 *  - **It never retries a 4xx.** The provider understood and refused; sending
 *    it again produces the same refusal against an account that now has a
 *    record of two attempts.
 *  - **It never logs a response body unredacted.** A 401 body comes from a
 *    server that was just handed a secret key.
 */

export interface HttpResponseLike {
  ok: boolean
  status: number
  text: () => Promise<string>
}

export type FetchLike = (
  url: string,
  init?: { method?: string; headers?: Record<string, string>; body?: string; signal?: AbortSignal },
) => Promise<HttpResponseLike>

export const PROVIDER_BASE_URL = 'https://api.stripe.com'

/**
 * 30 seconds per call.
 *
 * Shorter than registration's 60 because there is no cold start to cover — the
 * provider is always warm — and because this makes several calls in sequence
 * rather than one, so a budget that is generous per call is punishing overall.
 */
export const DEFAULT_TIMEOUT_MS = 30_000

export interface ProviderPrice {
  id: string
  lookupKey: string | null
  unitAmount: number | null
  currency: string
  interval: string | null
  active: boolean
}

export interface ProviderProduct {
  id: string
  name: string
}

export class ProviderError extends Error {
  readonly status: number | undefined
  readonly retryable: boolean

  constructor(message: string, options: { status?: number; retryable: boolean }) {
    super(message)
    this.name = 'ProviderError'
    this.status = options.status
    this.retryable = options.retryable
  }
}

/**
 * Form encoding with the provider's bracket convention for nested fields.
 *
 * `{ recurring: { interval: 'month' } }` becomes `recurring[interval]=month`.
 * Written out rather than taken from a library because getting it wrong is
 * silent: an unrecognised field is ignored by the provider, so a mis-encoded
 * `recurring` produces a one-off price where a subscription price was meant,
 * and nothing says so until a customer is charged once instead of monthly.
 */
export function encodeForm(payload: Record<string, unknown>, prefix = ''): string {
  const parts: string[] = []

  for (const [key, value] of Object.entries(payload)) {
    if (value === undefined || value === null) continue
    const name = prefix === '' ? key : `${prefix}[${key}]`

    if (typeof value === 'object' && !Array.isArray(value)) {
      const nested = encodeForm(value as Record<string, unknown>, name)
      if (nested !== '') parts.push(nested)
      continue
    }

    parts.push(`${encodeURIComponent(name)}=${encodeURIComponent(String(value))}`)
  }

  return parts.join('&')
}

export interface ProviderClientOptions {
  apiKey: string
  fetchImpl?: FetchLike
  timeoutMs?: number
  baseUrl?: string
  env?: NodeJS.ProcessEnv
}

/**
 * The environment the redactor sees, with this run's provider key in it.
 *
 * The same reasoning as the registration client's: `redact` blanks values of
 * variables whose names look sensitive, which covers this key in production
 * only by the coincidence that `KORAS_BILLING_PROVIDER_KEY` contains "KEY".
 * The client is the one thing that certainly knows the secret it is using, so
 * it says so explicitly rather than depending on a name.
 */
function redactionEnv(env: NodeJS.ProcessEnv, apiKey: string): NodeJS.ProcessEnv {
  return { ...env, KORAS_BILLING_PROVIDER_KEY: apiKey }
}

export class ProviderClient {
  private readonly apiKey: string
  private readonly fetchImpl: FetchLike
  private readonly timeoutMs: number
  private readonly baseUrl: string
  private readonly env: NodeJS.ProcessEnv

  constructor(options: ProviderClientOptions) {
    this.apiKey = options.apiKey
    this.fetchImpl = options.fetchImpl ?? (globalThis.fetch as unknown as FetchLike)
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
    this.baseUrl = options.baseUrl ?? PROVIDER_BASE_URL
    this.env = redactionEnv(options.env ?? process.env, options.apiKey)
  }

  private async call(
    method: 'GET' | 'POST',
    path: string,
    options: { body?: Record<string, unknown>; idempotency?: string } = {},
  ): Promise<{ status: number; body: string }> {
    if (typeof this.fetchImpl !== 'function') {
      throw new ProviderError('No fetch implementation is available in this runtime.', {
        retryable: false,
      })
    }

    const headers: Record<string, string> = {
      authorization: `Bearer ${this.apiKey}`,
      accept: 'application/json',
      // Pins the provider's API shape. Without it the account's own default
      // version applies, which changes under the estate without a deploy --
      // and a response shape that changes silently is how a field this code
      // reads becomes undefined on a day nobody touched it.
      'stripe-version': '2024-06-20',
    }

    if (options.body !== undefined) {
      headers['content-type'] = 'application/x-www-form-urlencoded'
    }

    // Only ever on a write. An idempotency key on a read means nothing and
    // would have the provider cache a lookup this code relies on being fresh.
    if (options.idempotency !== undefined && method === 'POST') {
      headers['idempotency-key'] = options.idempotency
    }

    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), this.timeoutMs)
    timer.unref?.()

    let response: HttpResponseLike
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers,
        body: options.body !== undefined ? encodeForm(options.body) : undefined,
        signal: controller.signal,
      })
    } catch (err) {
      const aborted = controller.signal.aborted
      throw new ProviderError(
        aborted
          ? `The payment provider did not respond within ${this.timeoutMs}ms.`
          : `The payment provider could not be reached: ${redact(err, this.env)}`,
        // A timeout on a write is the case the idempotency key exists for: the
        // call may well have landed, so a retry is safe precisely because it
        // will be recognised as the same attempt rather than a new one.
        { retryable: true },
      )
    } finally {
      clearTimeout(timer)
    }

    let body = ''
    try {
      body = await response.text()
    } catch {
      // A body that cannot be read changes nothing: the status decided the
      // outcome and the message simply says less.
    }

    return { status: response.status, body }
  }

  /** Turns a non-2xx into a refusal or a retryable failure, never a silent pass. */
  private fail(status: number, body: string, what: string): ProviderError {
    const safe = redact(body, this.env).replace(/\s+/g, ' ').trim().slice(0, 400)
    return new ProviderError(`${what} failed with HTTP ${status}: ${safe || '(empty body)'}`, {
      status,
      // 429 is the provider asking for a pause rather than refusing, so it
      // joins 5xx as worth another attempt. Every other 4xx will refuse again.
      retryable: status >= 500 || status === 429,
    })
  }

  private parse(body: string, what: string): Record<string, unknown> {
    try {
      const parsed: unknown = JSON.parse(body)
      if (parsed === null || typeof parsed !== 'object') throw new Error('not an object')
      return parsed as Record<string, unknown>
    } catch {
      throw new ProviderError(`${what} returned a body that is not JSON.`, { retryable: false })
    }
  }

  /**
   * The provider product for one plan, created only if it is not already there.
   *
   * Addressed by a **deterministic id** rather than found by search. The
   * provider's search index is eventually consistent — a product created
   * moments ago may not be returned yet — so a provisioner that searched would
   * create a duplicate on a re-run that happened to be quick, and duplicates
   * are exactly what this step exists to avoid. A GET on a known id has no
   * such window.
   */
  async ensureProduct(input: {
    id: string
    name: string
    taxCode: string
    metadata: Record<string, string>
  }): Promise<{ product: ProviderProduct; created: boolean }> {
    const existing = await this.call('GET', `/v1/products/${encodeURIComponent(input.id)}`)

    if (existing.status === 200) {
      const parsed = this.parse(existing.body, 'Reading the product')
      return {
        product: { id: String(parsed.id), name: String(parsed.name ?? input.name) },
        created: false,
      }
    }

    // Anything but "it is not there" is a real failure. Treating every
    // non-200 as absent would turn a 401 into a create attempt and a 403 into
    // a confusing second error.
    if (existing.status !== 404) {
      throw this.fail(existing.status, existing.body, 'Reading the product')
    }

    const created = await this.call('POST', '/v1/products', {
      body: {
        id: input.id,
        name: input.name,
        // A product without an eligible tax code cannot be sold through
        // Managed Payments at all, so this is sent on creation rather than
        // left to be set by hand afterwards -- which is the step the whole
        // provisioner exists to remove.
        tax_code: input.taxCode,
        metadata: input.metadata,
      },
      idempotency: idempotencyKey('product.create', input.id),
    })

    if (created.status < 200 || created.status >= 300) {
      throw this.fail(created.status, created.body, 'Creating the product')
    }

    const parsed = this.parse(created.body, 'Creating the product')
    return { product: { id: String(parsed.id), name: String(parsed.name ?? input.name) }, created: true }
  }

  /** Every active price carrying this lookup key. At most one, by the provider's rule. */
  async findPriceByLookupKey(lookupKey: string): Promise<ProviderPrice | null> {
    const query = `lookup_keys[0]=${encodeURIComponent(lookupKey)}&active=true&limit=2`
    const response = await this.call('GET', `/v1/prices?${query}`)

    if (response.status !== 200) {
      throw this.fail(response.status, response.body, 'Listing prices')
    }

    const parsed = this.parse(response.body, 'Listing prices')
    const data = Array.isArray(parsed.data) ? parsed.data : []
    if (data.length === 0) return null

    const row = data[0] as Record<string, unknown>
    const recurring = (row.recurring ?? null) as Record<string, unknown> | null

    return {
      id: String(row.id),
      lookupKey: row.lookup_key === null || row.lookup_key === undefined ? null : String(row.lookup_key),
      unitAmount:
        row.unit_amount === null || row.unit_amount === undefined ? null : Number(row.unit_amount),
      currency: String(row.currency ?? ''),
      interval: recurring === null ? null : String(recurring.interval ?? ''),
      active: row.active === true,
    }
  }

  /**
   * Creates a price, taking the lookup key from whatever holds it.
   *
   * `transfer_lookup_key` is what makes a corrected amount work at all. A
   * lookup key is unique among active prices, so creating the replacement
   * without it is refused; with it, the key moves and the superseded price
   * stays active but unnamed — still there to look at, referenced by nothing.
   */
  async createPrice(input: {
    productId: string
    lookupKey: string
    unitAmount: number
    currency: string
    interval: 'month' | 'year'
    transferLookupKey: boolean
    metadata: Record<string, string>
  }): Promise<ProviderPrice> {
    const response = await this.call('POST', '/v1/prices', {
      body: {
        product: input.productId,
        unit_amount: input.unitAmount,
        currency: input.currency,
        recurring: { interval: input.interval },
        lookup_key: input.lookupKey,
        transfer_lookup_key: input.transferLookupKey ? 'true' : undefined,
        metadata: input.metadata,
      },
      // The amount is part of the subject: the same plan at a corrected amount
      // is a different operation and must not replay the first attempt, which
      // would hand back the old price and report success.
      idempotency: idempotencyKey(
        'price.create',
        input.lookupKey,
        input.unitAmount,
        input.currency,
        input.interval,
      ),
    })

    if (response.status < 200 || response.status >= 300) {
      throw this.fail(response.status, response.body, 'Creating the price')
    }

    const parsed = this.parse(response.body, 'Creating the price')
    const recurring = (parsed.recurring ?? null) as Record<string, unknown> | null

    return {
      id: String(parsed.id),
      lookupKey: parsed.lookup_key === undefined ? null : String(parsed.lookup_key),
      unitAmount: parsed.unit_amount === undefined ? null : Number(parsed.unit_amount),
      currency: String(parsed.currency ?? input.currency),
      interval: recurring === null ? input.interval : String(recurring.interval ?? input.interval),
      active: parsed.active !== false,
    }
  }
}
