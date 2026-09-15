import { randomUUID } from 'node:crypto'
import { redact } from '../redact.js'
import { registrationUrl, type RegistrationConfig } from './config.js'
import type { ProductRegistration } from './contract.js'
import { parseStoredEnvironments, type StoredEnvironment } from './verify.js'

/**
 * POST the registration payload to the Control Plane.
 *
 * This runs after `terraform apply` has already created real infrastructure,
 * which sets every rule here:
 *
 *  - It never throws. A registration failure is reported to the operator and
 *    retried later; unwinding a provisioned estate because a registry was
 *    unreachable is the failure mode R-001 exists to prevent.
 *  - It never retries a rejected payload. A 4xx means the Control Plane
 *    understood the request and refused it, and sending it again produces the
 *    same refusal. Only a timeout or a transport failure is worth retrying,
 *    and that retry is the operator's `--register-only`, not a silent loop.
 *  - It never logs the payload, the token, or an unredacted response body.
 *    The payload is non-secret by construction, but a response body comes from
 *    a server that has just been handed a bearer token, and a 401 that quotes
 *    it back is exactly how that token reaches a CI log.
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

/**
 * How long registration waits for the Control Plane.
 *
 * 60 seconds, and the number is measured rather than chosen. The first real
 * registration this estate ever performed -- `koras-e2e-shop`, 2026-08-30 --
 * took **14,749ms** against the previous budget of 15,000. It failed twice by
 * roughly 250 milliseconds, and reported a timeout, which reads as an
 * unreachable Control Plane rather than a slow one.
 *
 * What made that hard to see: every earlier check probed with an empty body and
 * came back in 203-621ms. A `422` is refused at validation before the request
 * touches the database, so the fast answer proved the identity and nothing
 * about the cost. A real payload writes a product row, four environments, their
 * references and their services.
 *
 * The Control Plane also runs on Fly and stops when idle -- measured at 4.6s to
 * cold-start, then ~0.5s warm -- and registration is the last step of a long
 * provisioning run, so it is usually the first request after an idle period.
 * The budget has to cover a cold boot plus the write.
 *
 * Generous on purpose. This runs after `terraform apply` has created real
 * infrastructure, so the cost of waiting too long is a slow command, and the
 * cost of not waiting long enough is an operator told their estate did not
 * register when it very nearly did.
 */
export const DEFAULT_TIMEOUT_MS = 60_000

export type RegistrationOutcome =
  /**
   * The Control Plane accepted the product. `stored` is what it says the
   * registry now holds, read back from its tables -- absent when the response
   * did not carry it, which is a Control Plane older than 2026-09-15.
   */
  | { status: 'registered'; correlationId: string; stored?: StoredEnvironment[] }
  /** It understood the request and refused it. Retrying unchanged will not help. */
  | { status: 'rejected'; httpStatus: number; detail: string; correlationId: string }
  /** It could not be reached, or did not answer in time. Worth retrying. */
  | { status: 'unreachable'; detail: string; correlationId: string }

export interface RegisterOptions {
  fetchImpl?: FetchLike
  timeoutMs?: number
  /** Injected so a test can assert the header without matching a random value. */
  correlationId?: string
  env?: NodeJS.ProcessEnv
}

/** Hostname only. A full URL may carry credentials in userinfo or a query string. */
function safeHost(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return 'the Control Plane'
  }
}

/**
 * The environment the redactor sees, with this call's own token in it.
 *
 * `redact` blanks the values of environment variables whose names look
 * sensitive. That covers the token in production, where it arrives as
 * KORAS_CONTROL_PLANE_TOKEN — but only by coincidence of naming, and only when
 * the caller passes the environment that happens to hold it. A caller that
 * passes a narrower env, or a future config that sources the token elsewhere,
 * would leave the value unprotected.
 *
 * So the token in hand is added explicitly. The client is the one thing that
 * certainly knows the secret it is using; making the redactor's guarantee
 * depend on a variable name instead was the weakest link in it.
 */
function redactionEnv(env: NodeJS.ProcessEnv, token: string): NodeJS.ProcessEnv {
  return { ...env, KORAS_CONTROL_PLANE_TOKEN: token }
}

/**
 * Trims a response body to something loggable.
 *
 * Redacted first, then truncated — the other order would let a secret sitting
 * past the cutoff escape by never reaching the redactor.
 */
function summarise(body: string, env: NodeJS.ProcessEnv): string {
  const safe = redact(body, env).replace(/\s+/g, ' ').trim()
  if (safe === '') return '(empty response body)'
  return safe.length > 400 ? `${safe.slice(0, 400)}…` : safe
}

export async function registerProduct(
  config: RegistrationConfig,
  payload: ProductRegistration,
  options: RegisterOptions = {},
): Promise<RegistrationOutcome> {
  const env = redactionEnv(options.env ?? process.env, config.token)
  const fetchImpl = options.fetchImpl ?? (globalThis.fetch as unknown as FetchLike)
  const correlationId = options.correlationId ?? randomUUID()
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const url = registrationUrl(config)
  const host = safeHost(url)

  if (typeof fetchImpl !== 'function') {
    return {
      status: 'unreachable',
      detail: 'No fetch implementation is available in this runtime.',
      correlationId,
    }
  }

  // AbortController rather than a raced timer: this cancels the request itself,
  // so a Control Plane that accepts the connection and then stalls does not
  // leave a socket open for the rest of the process's life.
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  timer.unref?.()

  let response: HttpResponseLike
  try {
    response = await fetchImpl(url, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        accept: 'application/json',
        authorization: `Bearer ${config.token}`,
        // Lets an operator find this exact attempt in the Control Plane's logs
        // without correlating on timestamps.
        'x-koras-correlation-id': correlationId,
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    })
  } catch (err) {
    const aborted = controller.signal.aborted
    return {
      status: 'unreachable',
      detail: aborted
        ? `${host} did not respond within ${timeoutMs}ms.`
        : `${host} could not be reached: ${redact(err, env)}`,
      correlationId,
    }
  } finally {
    clearTimeout(timer)
  }

  if (response.ok) {
    // The body is read for one field, `stored_environments`, and never logged: a 201 body is the
    // registry's own contents, non-secret by construction, but the rule about
    // response bodies is simpler to keep if it has no exceptions.
    let stored: StoredEnvironment[] | undefined
    try {
      stored = parseStoredEnvironments(await response.text())
    } catch {
      // An unreadable body on a 201 changes nothing about the acceptance; it
      // only means the registry was not confirmed, which the caller reports.
      stored = undefined
    }
    return { status: 'registered', correlationId, stored }
  }

  let body = ''
  try {
    body = await response.text()
  } catch {
    // A body that cannot be read changes nothing: the status already decided
    // the outcome, and the summary simply says less.
  }

  // 5xx is the Control Plane failing, not the payload being wrong — the same
  // request may well succeed once it recovers, so it is reported as reachable
  // -but-broken rather than as a refusal to stop retrying.
  if (response.status >= 500) {
    return {
      status: 'unreachable',
      detail: `${host} returned HTTP ${response.status}: ${summarise(body, env)}`,
      correlationId,
    }
  }

  return {
    status: 'rejected',
    httpStatus: response.status,
    detail: summarise(body, env),
    correlationId,
  }
}
