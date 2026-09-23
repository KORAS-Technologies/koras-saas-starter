import { randomUUID } from 'node:crypto'
import { redact } from '../redact.js'

/**
 * The Control Plane half: reading the plan catalogue back, and writing prices
 * onto it.
 *
 * **`PUT /plans` is an upsert that overwrites the whole row.** Its statement
 * sets `name`, `self_serve`, `min_seats` and `max_seats` from what is sent, on
 * conflict as well as on insert. So a caller that sent only the price fields
 * would reset a plan's name to whatever it guessed, clear its seat bounds, and
 * silently take a plan off self-serve sale.
 *
 * That is why this reads first and merges second. The step owns four fields —
 * two price ids and two amounts, plus the currency — and round-trips every
 * other one exactly as the Control Plane reported it. Anything it did not read
 * it does not write.
 *
 * It also means a plan that does not exist is a **refusal, not a create**. The
 * endpoint would happily create one, and a mistyped plan code would then become
 * a real plan in the catalogue, priced, granting nothing, indistinguishable
 * from a tier somebody meant to add.
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

/** Matches registration's budget, and for the same reason: this Control Plane cold-starts. */
export const DEFAULT_TIMEOUT_MS = 60_000

/** A plan as the Control Plane holds it. Only the fields this step reads or preserves. */
export interface PlanRecord {
  code: string
  name: string
  self_serve: boolean
  price_id_month: string | null
  price_id_year: string | null
  expected_amount_month: number | null
  expected_amount_year: number | null
  expected_currency: string | null
  min_seats: number
  max_seats: number | null
}

export class ControlPlaneError extends Error {
  readonly status: number | undefined
  readonly retryable: boolean

  constructor(message: string, options: { status?: number; retryable: boolean }) {
    super(message)
    this.name = 'ControlPlaneError'
    this.status = options.status
    this.retryable = options.retryable
  }
}

export interface PlansClientOptions {
  baseUrl: string
  token: string
  fetchImpl?: FetchLike
  timeoutMs?: number
  correlationId?: string
  env?: NodeJS.ProcessEnv
}

function redactionEnv(env: NodeJS.ProcessEnv, token: string): NodeJS.ProcessEnv {
  return { ...env, KORAS_CONTROL_PLANE_TOKEN: token }
}

function summarise(body: string, env: NodeJS.ProcessEnv): string {
  const safe = redact(body, env).replace(/\s+/g, ' ').trim()
  if (safe === '') return '(empty response body)'
  return safe.length > 400 ? `${safe.slice(0, 400)}…` : safe
}

function safeHost(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return 'the Control Plane'
  }
}

/** Reads one field that may legitimately be absent on an older Control Plane. */
function optionalNumber(row: Record<string, unknown>, field: string): number | null {
  const value = row[field]
  return value === null || value === undefined ? null : Number(value)
}

function optionalString(row: Record<string, unknown>, field: string): string | null {
  const value = row[field]
  return value === null || value === undefined ? null : String(value)
}

export class PlansClient {
  private readonly baseUrl: string
  private readonly token: string
  private readonly fetchImpl: FetchLike
  private readonly timeoutMs: number
  private readonly correlationId: string
  private readonly env: NodeJS.ProcessEnv

  constructor(options: PlansClientOptions) {
    this.baseUrl = options.baseUrl
    this.token = options.token
    this.fetchImpl = options.fetchImpl ?? (globalThis.fetch as unknown as FetchLike)
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
    this.correlationId = options.correlationId ?? randomUUID()
    this.env = redactionEnv(options.env ?? process.env, options.token)
  }

  private async call(
    method: 'GET' | 'PUT',
    path: string,
    body?: unknown,
  ): Promise<{ status: number; body: string }> {
    if (typeof this.fetchImpl !== 'function') {
      throw new ControlPlaneError('No fetch implementation is available in this runtime.', {
        retryable: false,
      })
    }

    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), this.timeoutMs)
    timer.unref?.()

    const host = safeHost(this.baseUrl)
    let response: HttpResponseLike

    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers: {
          accept: 'application/json',
          authorization: `Bearer ${this.token}`,
          'x-koras-correlation-id': this.correlationId,
          ...(body !== undefined ? { 'content-type': 'application/json' } : {}),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      })
    } catch (err) {
      const aborted = controller.signal.aborted
      throw new ControlPlaneError(
        aborted
          ? `${host} did not respond within ${this.timeoutMs}ms.`
          : `${host} could not be reached: ${redact(err, this.env)}`,
        { retryable: true },
      )
    } finally {
      clearTimeout(timer)
    }

    let text = ''
    try {
      text = await response.text()
    } catch {
      // The status already decided the outcome.
    }

    return { status: response.status, body: text }
  }

  /** The correlation id every call in this run carries, so a log can be searched for it. */
  get correlation(): string {
    return this.correlationId
  }

  async listPlans(productCode: string): Promise<PlanRecord[]> {
    const path = `/api/platform/v1/plans?product_code=${encodeURIComponent(productCode)}`
    const response = await this.call('GET', path)

    if (response.status !== 200) {
      throw new ControlPlaneError(
        `Reading the plan catalogue failed with HTTP ${response.status}: ` +
          summarise(response.body, this.env) +
          (response.status === 403
            ? '\n  A 403 here usually means the service account has no platform billing role. ' +
              'Writing prices onto plans needs one; the registrar account deliberately has none.'
            : ''),
        { status: response.status, retryable: response.status >= 500 },
      )
    }

    let parsed: unknown
    try {
      parsed = JSON.parse(response.body)
    } catch {
      throw new ControlPlaneError('The plan catalogue came back as something that is not JSON.', {
        retryable: false,
      })
    }

    if (!Array.isArray(parsed)) {
      throw new ControlPlaneError('The plan catalogue came back as something that is not a list.', {
        retryable: false,
      })
    }

    return parsed.map((entry) => {
      const row = entry as Record<string, unknown>
      return {
        code: String(row.code ?? ''),
        name: String(row.name ?? ''),
        self_serve: row.self_serve === true,
        price_id_month: optionalString(row, 'price_id_month'),
        price_id_year: optionalString(row, 'price_id_year'),
        expected_amount_month: optionalNumber(row, 'expected_amount_month'),
        expected_amount_year: optionalNumber(row, 'expected_amount_year'),
        expected_currency: optionalString(row, 'expected_currency'),
        min_seats: row.min_seats === null || row.min_seats === undefined ? 1 : Number(row.min_seats),
        max_seats: optionalNumber(row, 'max_seats'),
      }
    })
  }

  /**
   * Writes one plan back, whole.
   *
   * `plan` must be the record read from `listPlans` with only this step's own
   * fields changed. The caller builds it that way; this signature takes the
   * complete row rather than a patch so that the overwrite is visible at the
   * call site instead of being a property of the endpoint that has to be
   * remembered.
   */
  async upsertPlan(productCode: string, plan: PlanRecord): Promise<void> {
    const response = await this.call('PUT', '/api/platform/v1/plans', {
      product_code: productCode,
      code: plan.code,
      name: plan.name,
      self_serve: plan.self_serve,
      price_id_month: plan.price_id_month,
      price_id_year: plan.price_id_year,
      expected_amount_month: plan.expected_amount_month,
      expected_amount_year: plan.expected_amount_year,
      expected_currency: plan.expected_currency,
      min_seats: plan.min_seats,
      max_seats: plan.max_seats,
    })

    if (response.status < 200 || response.status >= 300) {
      throw new ControlPlaneError(
        `Writing plan ${plan.code} failed with HTTP ${response.status}: ` +
          summarise(response.body, this.env),
        { status: response.status, retryable: response.status >= 500 },
      )
    }
  }
}
