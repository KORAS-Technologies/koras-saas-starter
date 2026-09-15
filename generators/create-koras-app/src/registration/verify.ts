import type { ProductRegistration } from './contract.js'

/**
 * Confirming the registry, from the response alone.
 *
 * Until 2026-09-15 a successful registration proved that the Control Plane had
 * *accepted* the payload and nothing about what it then held: the response
 * carried environment names only, and `GET /products` is restricted to
 * platform staff, which the `registrar` identity is not. A payload stored
 * wrongly and one stored correctly produced identical output -- F7 in
 * `docs/FOLLOW_UPS.md`, which could not be closed by the caller even in
 * principle.
 *
 * The Control Plane now reads the registry back inside the registration's own
 * transaction and returns it as `stored_environments`, in the request's shape.
 * This module compares what was sent with what came back, key for key, and
 * names the keys that differ -- keys only, never values, because a value in a
 * failure message is a value in a CI log.
 *
 * A response without the field is an older Control Plane, and that is reported
 * as *accepted, not confirmed* rather than as a failure. The bootstrap order
 * (R-001) provisions the first product before its Control Plane exists, and a
 * caller that failed on an older response would fail on the next thing too.
 */

/** One entry of `stored_environments`, as the Control Plane's `StoredEnvironment`. */
export interface StoredEnvironment {
  environment: string
  infrastructure: Record<string, unknown>
  services: string[]
}

export type Verification =
  /** Every reference sent is stored as sent. */
  | { confirmed: true }
  /** At least one is not. Paths only -- `dev.infrastructure.fly_apps`, `prod.services`. */
  | { confirmed: false; differences: string[] }

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isStoredEnvironment(value: unknown): value is StoredEnvironment {
  return (
    isRecord(value) &&
    typeof value.environment === 'string' &&
    isRecord(value.infrastructure) &&
    Array.isArray(value.services) &&
    value.services.every((s) => typeof s === 'string')
  )
}

/**
 * The stored references a response carries, or `undefined` when it carries
 * none.
 *
 * `undefined` covers three cases on purpose -- no body, a body that is not
 * JSON, and JSON without a well-formed `stored_environments` -- because all
 * three mean the same thing to the caller: the Control Plane said yes and did
 * not say what it stored. None is a reason to fail a registration that was
 * accepted; all are a reason not to call it confirmed.
 */
export function parseStoredEnvironments(body: string): StoredEnvironment[] | undefined {
  if (body.trim() === '') return undefined

  let parsed: unknown
  try {
    parsed = JSON.parse(body)
  } catch {
    return undefined
  }

  if (!isRecord(parsed)) return undefined
  const stored = parsed.stored_environments
  if (!Array.isArray(stored) || !stored.every(isStoredEnvironment)) return undefined
  return stored
}

/**
 * A value as it is compared: absent and null are the same absence, and an
 * object compares by content with its keys in a fixed order.
 *
 * The request omits a reference it does not have and the response answers
 * `null` for one it does not hold, and those are the same fact. The maps --
 * `vercel_projects`, `fly_apps` -- come back in database order, which is not
 * the order they were sent in.
 */
function canonical(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined
  if (isRecord(value)) {
    const entries = Object.entries(value)
      .filter(([, v]) => v !== undefined && v !== null)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    return JSON.stringify(Object.fromEntries(entries))
  }
  if (Array.isArray(value)) return JSON.stringify([...value].sort())
  return JSON.stringify(value)
}

/**
 * Compare a payload with what the Control Plane says it stored.
 *
 * One direction only: every reference *sent* must be stored as sent. A
 * reference stored and not sent is not a difference, because references are
 * upserted and never pruned -- a value registered last time and omitted this
 * time is meant to survive, and the response lists it so nobody believes it
 * has gone. Services are compared whole, because the Control Plane prunes
 * them and the stored list is meant to equal the sent one.
 */
export function compareRegistration(
  payload: ProductRegistration,
  stored: StoredEnvironment[],
): Verification {
  const held = new Map(stored.map((entry) => [entry.environment, entry]))
  const differences: string[] = []

  for (const [environment, sent] of Object.entries(payload.environments)) {
    const entry = held.get(environment)
    if (entry === undefined) {
      differences.push(`${environment} (not stored)`)
      continue
    }

    const infrastructure = sent.infrastructure as Record<string, unknown>
    for (const key of Object.keys(infrastructure).sort()) {
      const wanted = canonical(infrastructure[key])
      if (wanted === undefined) continue
      if (wanted !== canonical(entry.infrastructure[key])) {
        differences.push(`${environment}.infrastructure.${key}`)
      }
    }

    if (canonical(sent.services) !== canonical(entry.services)) {
      differences.push(`${environment}.services`)
    }
  }

  return differences.length === 0 ? { confirmed: true } : { confirmed: false, differences }
}
