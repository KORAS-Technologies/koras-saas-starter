import { stripTrailingSlashes } from '../url.js'
import { isKeyProblem, parseServiceAccountKey, type ServiceAccountKey } from './token.js'

/**
 * Where the Control Plane is, and what authorises this call.
 *
 * Both come from Doppler, injected into the environment by the same re-exec
 * that supplies the provisioning credentials — so registration needs no
 * separate secret plumbing and no second place to rotate a credential. The base
 * URL is not itself a secret, so it also accepts a flag; the credential does
 * not, and never will. A token on the command line is a token in the shell
 * history, in the process table, and in whatever CI log echoes the command.
 *
 * Two credentials are accepted, and the difference between them is F2a.
 *
 * `KORAS_CONTROL_PLANE_KEY_JSON` is the `registrar` service account's key. It
 * does not expire, and a token is minted from it per call. This is the shape
 * the rest of the estate already uses — the ZITADEL Terraform provider holds
 * `ZITADEL_DEV_SERVICE_ACCOUNT_KEY_JSON` and exchanges it when it runs — and it
 * is preferred here for that reason.
 *
 * `KORAS_CONTROL_PLANE_TOKEN` is a finished bearer string. It still works, and
 * it lasts twelve hours: the exchange returns a lifetime of 43,199 seconds,
 * measured on 2026-08-28. Stored as standing configuration it fails a day
 * later, as a misconfiguration rather than a skip — the right failure, arriving
 * daily. It stays supported because an estate holding one and no key must not
 * stop working the moment this lands.
 */

/** Doppler secret carrying the Control Plane's base URL, e.g. https://control-plane.koras.io */
export const BASE_URL_VAR = 'KORAS_CONTROL_PLANE_URL'

/** Doppler secret carrying a finished bearer token. Twelve hours; prefer the key. */
export const TOKEN_VAR = 'KORAS_CONTROL_PLANE_TOKEN'

/** Doppler secret carrying the `registrar` service-account key, minted from per call. */
export const KEY_VAR = 'KORAS_CONTROL_PLANE_KEY_JSON'

/** The Control Plane's own ZITADEL project id, which the minted token must be addressed to. */
export const PROJECT_ID_VAR = 'KORAS_CONTROL_PLANE_PROJECT_ID'

/** Escape hatch for a Control Plane whose hostname does not encode its environment. */
export const INSTANCE_OVERRIDE_VAR = 'ZITADEL_DOMAIN_OVERRIDE'

/** What the client posts with: a resolved bearer, whatever produced it. */
export interface RegistrationConfig {
  baseUrl: string
  token: string
  endpoint: string
}

/** Where the bearer comes from, before anything has been minted. */
export type CredentialSource =
  | { kind: 'token'; token: string }
  | { kind: 'key'; key: ServiceAccountKey; instance: string; projectId: string }

/** The resolved configuration, with the credential still unspent. */
export interface RegistrationSource {
  baseUrl: string
  credential: CredentialSource
  endpoint: string
}

export type ConfigProblem =
  /** No Control Plane is configured. The documented bootstrap order — not an error. */
  | { kind: 'no-base-url' }
  /** A Control Plane was named but nothing authorises the call. A misconfiguration. */
  | { kind: 'no-token'; detail: string }
  /** The base URL is unusable, or would put a bearer token on the wire in clear. */
  | { kind: 'bad-base-url'; detail: string }
  /** A key was supplied but cannot be used as one. Never falls back to the token. */
  | { kind: 'bad-key'; detail: string }

export type ConfigResolution =
  | { ok: true; config: RegistrationSource }
  | { ok: false; problem: ConfigProblem }

function value(env: NodeJS.ProcessEnv, name: string): string | undefined {
  const raw = env[name]
  return raw !== undefined && raw.trim() !== '' ? raw.trim() : undefined
}

/** The four environments an estate has, as they appear in a Fly hostname. */
const ENVIRONMENTS = ['dev', 'test', 'stg', 'prod'] as const

/**
 * A bare hostname is not a base URL.
 *
 * `ZITADEL_<ENV>_DOMAIN` holds a hostname with no scheme in this estate, and
 * assuming otherwise is not hypothetical: the first ZITADEL delete of the
 * 2026-08-30 teardown went out as http, was answered with a 301, and would have
 * been read as success had the response not been checked. Here the same
 * omission produces an assertion whose audience does not match the issuer,
 * which ZITADEL refuses.
 */
function normaliseInstance(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, '')
  return trimmed.startsWith('http://') || trimmed.startsWith('https://')
    ? trimmed
    : `https://${trimmed}`
}

/**
 * Which ZITADEL instance minted the registrar, decided by the Control Plane the
 * URL names rather than by a separate answer that could disagree with it.
 *
 * A token minted in dev is not valid at the prod Control Plane, and that
 * mismatch is a 401 indistinguishable from an expired one. Deriving the
 * instance removes the only way for the two to disagree. The same rule, and the
 * same regex, as `scripts/mint-control-plane-token.mjs`.
 */
export function deriveInstance(
  baseUrl: string,
  env: NodeJS.ProcessEnv,
): { ok: true; instance: string } | { ok: false; detail: string } {
  const override = value(env, INSTANCE_OVERRIDE_VAR)
  if (override) return { ok: true, instance: normaliseInstance(override) }

  const match = new RegExp(`-api-(${ENVIRONMENTS.join('|')})\\.`).exec(baseUrl)
  if (!match) {
    return {
      ok: false,
      detail:
        `Cannot tell which environment ${baseUrl} is, so the ZITADEL instance that issued ` +
        `the ${KEY_VAR} key cannot be derived. Expected a host like ` +
        `<repository>-api-<dev|test|stg|prod>.fly.dev, or set ${INSTANCE_OVERRIDE_VAR}.`,
    }
  }

  const domainVar = `ZITADEL_${match[1].toUpperCase()}_DOMAIN`
  const domain = value(env, domainVar)
  if (!domain) {
    return {
      ok: false,
      detail:
        `${baseUrl} is the ${match[1]} Control Plane, but ${domainVar} is not set. ` +
        'It names the ZITADEL instance holding the registrar service account.',
    }
  }

  return { ok: true, instance: normaliseInstance(domain) }
}

/**
 * Whether a plaintext origin is one that cannot leave the machine.
 *
 * `--control-plane-url http://localhost:8000` is how the lab and the
 * integration tests reach a Control Plane running locally, and refusing it
 * would mean the only testable configuration is a real deployment. Every other
 * host must be https, because the bearer token travels in the request headers.
 */
function isLoopback(hostname: string): boolean {
  return (
    hostname === 'localhost' ||
    hostname === '127.0.0.1' ||
    hostname === '[::1]' ||
    hostname === '::1'
  )
}

/**
 * The credential, preferring the key.
 *
 * A malformed key is a refusal rather than a fallback to whatever token is also
 * lying about. Falling back would mean an operator who stored a key correctly,
 * then damaged it, silently going on using an expiring token they thought they
 * had replaced — and finding out twelve hours later, from a different error.
 */
function resolveCredential(
  env: NodeJS.ProcessEnv,
  baseUrl: string,
  host: string,
): { ok: true; credential: CredentialSource } | { ok: false; problem: ConfigProblem } {
  const rawKey = value(env, KEY_VAR)

  if (rawKey) {
    const key = parseServiceAccountKey(rawKey)
    if (isKeyProblem(key)) {
      return { ok: false, problem: { kind: 'bad-key', detail: `${KEY_VAR} ${key.detail}` } }
    }

    const projectId = value(env, PROJECT_ID_VAR)
    if (!projectId) {
      return {
        ok: false,
        problem: {
          kind: 'bad-key',
          detail:
            `${KEY_VAR} is set but ${PROJECT_ID_VAR} is not. A minted token has to name the ` +
            "Control Plane's ZITADEL project in its audience, or the Control Plane answers 401.",
        },
      }
    }

    const instance = deriveInstance(baseUrl, env)
    if (!instance.ok) {
      return { ok: false, problem: { kind: 'bad-key', detail: instance.detail } }
    }

    return {
      ok: true,
      credential: { kind: 'key', key, instance: instance.instance, projectId },
    }
  }

  const token = value(env, TOKEN_VAR)
  if (token) return { ok: true, credential: { kind: 'token', token } }

  return {
    ok: false,
    problem: {
      kind: 'no-token',
      detail:
        `${host} is configured as the Control Plane, but neither ${KEY_VAR} nor ${TOKEN_VAR} ` +
        `is set. Store the registrar service-account key as ${KEY_VAR} alongside the ` +
        'provisioning credentials; a token is minted from it per call.',
    },
  }
}

export function resolveRegistrationConfig(options: {
  endpoint: string
  urlOverride?: string
  env?: NodeJS.ProcessEnv
}): ConfigResolution {
  const env = options.env ?? process.env
  const rawUrl = options.urlOverride?.trim() || value(env, BASE_URL_VAR)

  if (!rawUrl) return { ok: false, problem: { kind: 'no-base-url' } }

  let parsed: URL
  try {
    parsed = new URL(rawUrl)
  } catch {
    return { ok: false, problem: { kind: 'bad-base-url', detail: `${rawUrl} is not a URL.` } }
  }

  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    return {
      ok: false,
      problem: { kind: 'bad-base-url', detail: `${parsed.protocol}// is not a supported scheme.` },
    }
  }

  if (parsed.protocol === 'http:' && !isLoopback(parsed.hostname)) {
    return {
      ok: false,
      problem: {
        kind: 'bad-base-url',
        detail:
          `${parsed.host} was given over http. Registration sends a bearer token, ` +
          'so anything but a loopback address must be https.',
      },
    }
  }

  // A base URL may not carry credentials. `https://user:pass@host` would put
  // them in the request and in `baseUrl`, which is printed — and it is the
  // same mistake as a token on the command line, arriving by a different door.
  if (parsed.username !== '' || parsed.password !== '') {
    return {
      ok: false,
      problem: {
        kind: 'bad-base-url',
        detail:
          `${parsed.host} was given with credentials embedded in the URL. ` +
          `Supply the credential as ${KEY_VAR} instead.`,
      },
    }
  }

  // Trailing slashes are removed so joining with an endpoint that begins with
  // one cannot produce a double slash — which some routers 404 and others
  // redirect, and a redirect is where an Authorization header gets dropped.
  const baseUrl = stripTrailingSlashes(parsed.toString())

  const credential = resolveCredential(env, baseUrl, parsed.host)
  if (!credential.ok) return { ok: false, problem: credential.problem }

  return {
    ok: true,
    config: {
      baseUrl,
      credential: credential.credential,
      endpoint: options.endpoint,
    },
  }
}

/** The full URL registration posts to. */
export function registrationUrl(config: { baseUrl: string; endpoint: string }): string {
  const path = config.endpoint.startsWith('/') ? config.endpoint : `/${config.endpoint}`
  return `${config.baseUrl}${path}`
}
