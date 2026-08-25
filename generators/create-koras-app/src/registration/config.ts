import { stripTrailingSlashes } from '../url.js'

/**
 * Where the Control Plane is, and what authorises this call.
 *
 * Both come from Doppler, injected into the environment by the same re-exec
 * that supplies the provisioning credentials — so registration needs no
 * separate secret plumbing and no second place to rotate a token. The base URL
 * is not itself a secret, so it also accepts a flag; the token does not, and
 * never will. A token on the command line is a token in the shell history, in
 * the process table, and in whatever CI log echoes the command.
 */

/** Doppler secret carrying the Control Plane's base URL, e.g. https://control-plane.koras.io */
export const BASE_URL_VAR = 'KORAS_CONTROL_PLANE_URL'

/** Doppler secret carrying the bearer token the Control Plane issues to the factory. */
export const TOKEN_VAR = 'KORAS_CONTROL_PLANE_TOKEN'

export interface RegistrationConfig {
  baseUrl: string
  token: string
  endpoint: string
}

export type ConfigProblem =
  /** No Control Plane is configured. The documented bootstrap order — not an error. */
  | { kind: 'no-base-url' }
  /** A Control Plane was named but nothing authorises the call. A misconfiguration. */
  | { kind: 'no-token'; detail: string }
  /** The base URL is unusable, or would put a bearer token on the wire in clear. */
  | { kind: 'bad-base-url'; detail: string }

export type ConfigResolution =
  | { ok: true; config: RegistrationConfig }
  | { ok: false; problem: ConfigProblem }

function value(env: NodeJS.ProcessEnv, name: string): string | undefined {
  const raw = env[name]
  return raw !== undefined && raw.trim() !== '' ? raw.trim() : undefined
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
          `Supply the token as ${TOKEN_VAR} instead.`,
      },
    }
  }

  const token = value(env, TOKEN_VAR)
  if (!token) {
    return {
      ok: false,
      problem: {
        kind: 'no-token',
        detail:
          `${parsed.host} is configured as the Control Plane, but ${TOKEN_VAR} is not set. ` +
          'Store it in Doppler alongside the provisioning credentials.',
      },
    }
  }

  // Trailing slashes are removed so joining with an endpoint that begins with
  // one cannot produce a double slash — which some routers 404 and others
  // redirect, and a redirect is where an Authorization header gets dropped.
  return {
    ok: true,
    config: {
      baseUrl: stripTrailingSlashes(parsed.toString()),
      token,
      endpoint: options.endpoint,
    },
  }
}

/** The full URL registration posts to. */
export function registrationUrl(config: RegistrationConfig): string {
  const path = config.endpoint.startsWith('/') ? config.endpoint : `/${config.endpoint}`
  return `${config.baseUrl}${path}`
}
