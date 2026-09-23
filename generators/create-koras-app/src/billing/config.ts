import type { ServiceAccountKey } from '../registration/token.js'
import { INSTANCE_OVERRIDE_VAR } from '../registration/config.js'
import { stripTrailingSlashes } from '../url.js'

/**
 * What authorises catalogue provisioning, and which estate it is aimed at.
 *
 * Two credentials are needed and neither is the one registration uses.
 *
 * **The provider key** is the factory's, not a product's. The rule that no
 * product ever holds a provider credential is about *product repositories*:
 * this key lives in the factory's own Doppler, is read by an operator running
 * the factory, and never reaches a generated project, a template, or a
 * registration payload. A generated repository that held one would be able to
 * change what its own customers are charged.
 *
 * **The Control Plane key** is a *second* service account, and it has to be.
 * `registrar` deliberately carries no platform role, because a platform role
 * reclassifies its token as staff and the registration endpoint admits
 * machines only — granting `registrar` the role needed to write a plan would
 * break the registration it exists for. Writing prices onto plans needs
 * `PlatformBillingDep`, which is a platform role. So: a separate account, and
 * the separation is the point rather than an inconvenience.
 */

/** Doppler secret carrying the payment provider's secret key. */
export const PROVIDER_KEY_VAR = 'KORAS_BILLING_PROVIDER_KEY'

/**
 * A finished bearer token for a member of staff holding the billing role.
 *
 * **The only credential that works today**, and the reason is a platform rule
 * rather than a gap: a platform role requires a second factor, and a service
 * account has no interactive authentication to reference — so a machine
 * granted the billing role is refused at verification, every time. The
 * Control Plane's own verifier says as much: machine identities are how
 * products and internal jobs call the platform API, and they are never granted
 * platform roles.
 *
 * So this is a person's token, obtained the way the walkthrough's staff token
 * is: the `id_token` cookie of a signed-in console session. **It expires**, in
 * hours rather than days, which is why the estate's other credentials are keys
 * that mint per call. That is a real cost and it is accepted deliberately for
 * now — the alternative is weakening the second-factor rule for every member
 * of staff to solve one command's problem.
 */
export const BILLING_TOKEN_VAR = 'KORAS_CONTROL_PLANE_BILLING_TOKEN'

/**
 * A service-account key for the same job, which **cannot work yet**.
 *
 * Kept because it is where this is going: the fix is a machine door on the
 * catalogue endpoints with an allowlist naming which machine may price a
 * catalogue, so that the second-factor rule stays intact for people and
 * machines stay out of platform roles. Until that exists a key here produces a
 * 401 that looks like a misconfiguration, so it is refused with the reason
 * instead.
 */
export const BILLING_KEY_VAR = 'KORAS_CONTROL_PLANE_BILLING_KEY_JSON'

/**
 * Escape hatch for a Control Plane whose hostname does not encode its
 * environment — a locally-run one, most often.
 *
 * Deliberately separate from `ZITADEL_DOMAIN_OVERRIDE`. That one says which
 * instance signs a token; this one says which estate is about to be charged
 * for, and conflating them would mean pointing at a local identity provider
 * also silently declared the target to be production.
 */
export const ENVIRONMENT_OVERRIDE_VAR = 'KORAS_BILLING_ENVIRONMENT'

/** The four environments an estate has, as they appear in a Fly hostname. */
export const ENVIRONMENTS = ['dev', 'test', 'stg', 'prod'] as const
export type Environment = (typeof ENVIRONMENTS)[number]

/**
 * A live provider key, recognised on sight.
 *
 * Stripe's restricted keys (`rk_live_`) are included: a restricted key scoped
 * to write prices is every bit as live as an unrestricted one, and the whole
 * point of this check is that it does not depend on the key being the powerful
 * kind.
 */
function isLiveKey(key: string): boolean {
  return key.startsWith('sk_live_') || key.startsWith('rk_live_')
}

function isTestKey(key: string): boolean {
  return key.startsWith('sk_test_') || key.startsWith('rk_test_')
}

export interface BillingConfig {
  baseUrl: string
  environment: Environment
  providerKey: string
  credential:
    | { kind: 'key'; key: ServiceAccountKey; instance: string; projectId: string }
    | { kind: 'token'; token: string }
}

export type BillingConfigProblem =
  /** No Control Plane is configured. The documented bootstrap order — not an error. */
  | { kind: 'no-base-url' }
  /** Nothing authorises the provider half. */
  | { kind: 'no-provider-key'; detail: string }
  /** Nothing authorises the Control Plane half. */
  | { kind: 'no-billing-key'; detail: string }
  /** The target estate and the key's mode disagree. Always a refusal. */
  | { kind: 'environment-mismatch'; detail: string }
  /** Something is malformed. */
  | { kind: 'bad-config'; detail: string }

export type BillingConfigResolution =
  | { ok: true; config: BillingConfig }
  | { ok: false; problem: BillingConfigProblem }

function value(env: NodeJS.ProcessEnv, name: string): string | undefined {
  const raw = env[name]
  return raw !== undefined && raw.trim() !== '' ? raw.trim() : undefined
}

function isEnvironment(candidate: string): candidate is Environment {
  return (ENVIRONMENTS as readonly string[]).includes(candidate)
}

/**
 * Which estate a Control Plane URL names.
 *
 * The same rule and the same shape as the ZITADEL instance derivation beside
 * it, and derived rather than answered separately for the same reason: an
 * environment supplied independently of the URL is an environment that can
 * disagree with it, and the disagreement here is charging a real customer
 * against a catalogue somebody thought was a test.
 */
export function deriveEnvironment(
  baseUrl: string,
  env: NodeJS.ProcessEnv,
): { ok: true; environment: Environment } | { ok: false; detail: string } {
  const override = value(env, ENVIRONMENT_OVERRIDE_VAR)
  if (override) {
    if (!isEnvironment(override)) {
      return {
        ok: false,
        detail:
          `${ENVIRONMENT_OVERRIDE_VAR} is set to "${override}", which is not one of ` +
          `${ENVIRONMENTS.join(', ')}.`,
      }
    }
    return { ok: true, environment: override }
  }

  const match = new RegExp(`-api-(${ENVIRONMENTS.join('|')})\\.`).exec(baseUrl)
  if (!match || !isEnvironment(match[1])) {
    return {
      ok: false,
      detail:
        `Cannot tell which environment ${baseUrl} is, so it cannot be decided whether a live ` +
        `provider key is allowed to be used against it. Expected a host like ` +
        `<repository>-api-<dev|test|stg|prod>.fly.dev, or set ${ENVIRONMENT_OVERRIDE_VAR}.`,
    }
  }

  return { ok: true, environment: match[1] }
}

/**
 * Whether this key may be used against this estate.
 *
 * Both directions are refused, and the second is not symmetric politeness.
 *
 * A **live key outside production** creates real, chargeable prices in the real
 * account while an operator believes they are rehearsing. Nothing later in the
 * run would notice: the calls succeed, the ids look the same, and the
 * catalogue ends up correct in the wrong account.
 *
 * A **test key in production** produces a catalogue that looks provisioned and
 * cannot take a payment. The failure surfaces at the first customer's checkout,
 * which is the worst possible place to find it, and the price ids written onto
 * the production plans would have to be replaced rather than corrected.
 *
 * An unrecognised prefix is refused rather than allowed. A key whose mode
 * cannot be read is a key whose mode cannot be checked, and this is the one
 * check standing between a rehearsal and a real account.
 */
export function checkKeyEnvironment(
  providerKey: string,
  environment: Environment,
): { ok: true } | { ok: false; detail: string } {
  const live = isLiveKey(providerKey)
  const test = isTestKey(providerKey)

  if (!live && !test) {
    return {
      ok: false,
      detail:
        `${PROVIDER_KEY_VAR} does not begin with a recognised live or test prefix, so which ` +
        'account it belongs to cannot be determined. Refused: this check is what keeps a ' +
        'rehearsal out of the real account, and a key it cannot read is a key it cannot check.',
    }
  }

  if (live && environment !== 'prod') {
    return {
      ok: false,
      detail:
        `${PROVIDER_KEY_VAR} is a live key and the target is ${environment}. Creating prices ` +
        'in the real account from a non-production run is refused. Use the test key for ' +
        `${environment}, or point at the production Control Plane if this was meant to be live.`,
    }
  }

  if (test && environment === 'prod') {
    return {
      ok: false,
      detail:
        `${PROVIDER_KEY_VAR} is a test key and the target is prod. The plans would be written ` +
        'with price ids that cannot take a payment, and the first customer to reach a checkout ' +
        'is where that would be discovered.',
    }
  }

  return { ok: true }
}

function isLoopback(hostname: string): boolean {
  return (
    hostname === 'localhost' ||
    hostname === '127.0.0.1' ||
    hostname === '[::1]' ||
    hostname === '::1'
  )
}

export function resolveBillingConfig(options: {
  urlOverride?: string
  env?: NodeJS.ProcessEnv
}): BillingConfigResolution {
  const env = options.env ?? process.env
  const rawUrl = options.urlOverride?.trim() || value(env, 'KORAS_CONTROL_PLANE_URL')

  if (!rawUrl) return { ok: false, problem: { kind: 'no-base-url' } }

  let parsed: URL
  try {
    parsed = new URL(rawUrl)
  } catch {
    return { ok: false, problem: { kind: 'bad-config', detail: `${rawUrl} is not a URL.` } }
  }

  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    return {
      ok: false,
      problem: { kind: 'bad-config', detail: `${parsed.protocol}// is not a supported scheme.` },
    }
  }

  if (parsed.protocol === 'http:' && !isLoopback(parsed.hostname)) {
    return {
      ok: false,
      problem: {
        kind: 'bad-config',
        detail:
          `${parsed.host} was given over http. This step sends a bearer token, so anything ` +
          'but a loopback address must be https.',
      },
    }
  }

  if (parsed.username !== '' || parsed.password !== '') {
    return {
      ok: false,
      problem: {
        kind: 'bad-config',
        detail: `${parsed.host} was given with credentials embedded in the URL.`,
      },
    }
  }

  const baseUrl = stripTrailingSlashes(parsed.toString())

  const environment = deriveEnvironment(baseUrl, env)
  if (!environment.ok) {
    return { ok: false, problem: { kind: 'bad-config', detail: environment.detail } }
  }

  const providerKey = value(env, PROVIDER_KEY_VAR)
  if (!providerKey) {
    return {
      ok: false,
      problem: {
        kind: 'no-provider-key',
        detail:
          `${PROVIDER_KEY_VAR} is not set. It carries the payment provider's secret key and ` +
          "belongs in the factory's own Doppler, beside the provisioning credentials — never " +
          'in a generated project.',
      },
    }
  }

  // Ordered before the Control Plane credential deliberately. This is the check
  // that decides whether a real account is about to be written to; reporting a
  // missing service-account key first would send an operator to fix the lesser
  // problem and meet this one on the next run.
  const allowed = checkKeyEnvironment(providerKey, environment.environment)
  if (!allowed.ok) {
    return { ok: false, problem: { kind: 'environment-mismatch', detail: allowed.detail } }
  }

  // The staff token wins, because it is the one that works. Registration
  // prefers a key over a token for the opposite reason -- a key mints per call
  // and never goes stale -- and the difference is not inconsistency: there, a
  // machine identity is what the endpoint wants; here, a machine identity is
  // what the endpoint refuses.
  const token = value(env, BILLING_TOKEN_VAR)
  if (token) {
    return {
      ok: true,
      config: {
        baseUrl,
        environment: environment.environment,
        providerKey,
        credential: { kind: 'token', token },
      },
    }
  }

  const rawKey = value(env, BILLING_KEY_VAR)
  if (rawKey) {
    // Refused with the reason rather than sent. A service account holding the
    // billing role is answered with a 401 that reads exactly like an expired
    // token or a wrong audience, and somebody would spend an afternoon on it.
    return {
      ok: false,
      problem: {
        kind: 'bad-config',
        detail:
          `${BILLING_KEY_VAR} is set, and a service account cannot hold a platform role. ` +
          'A platform role requires a second factor and a machine identity has no ' +
          'interactive authentication to reference, so the Control Plane refuses the token ' +
          `at verification. Use ${BILLING_TOKEN_VAR} with a staff token until the ` +
          'catalogue endpoints admit a named machine.',
      },
    }
  }

  return {
    ok: false,
    problem: {
      kind: 'no-billing-key',
      detail:
        `${BILLING_TOKEN_VAR} is not set. Writing a price onto a plan needs the platform ` +
        'billing role, which only a person can hold: take the `id_token` cookie from a ' +
        'signed-in Control Plane console session, as the walkthrough does for a staff ' +
        'token. It expires in hours, so it is set for the run rather than stored.',
    },
  }
}

export { INSTANCE_OVERRIDE_VAR }
