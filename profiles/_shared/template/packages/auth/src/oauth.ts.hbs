/**
 * The authorization-code flow, with the two protections the first cut lacked.
 *
 * `state` used to carry the post-login destination. That is two defects in one
 * parameter. It is the CSRF token for the flow, so a predictable value lets an
 * attacker complete a login into someone else's browser with their own account;
 * and a destination taken from the query string and redirected to afterwards is
 * an open redirect, which is how a phishing link ends up wearing a KORAS
 * domain.
 *
 * State is now random and compared against a cookie the browser cannot read.
 * The destination travels separately and is refused unless it is a path on this
 * site. PKCE is added because the code is exchanged from a route handler over
 * a redirect the browser can see: without a verifier, a code intercepted in
 * transit is enough on its own.
 */

const STATE_COOKIE = 'oauth_state'
const VERIFIER_COOKIE = 'oauth_verifier'
const RETURN_COOKIE = 'oauth_return'

export const OAUTH_COOKIES = {
  state: STATE_COOKIE,
  verifier: VERIFIER_COOKIE,
  returnTo: RETURN_COOKIE,
} as const

export interface AuthorizationStart {
  url: string
  state: string
  codeVerifier: string
  returnTo: string
}

function randomToken(bytes = 32): string {
  const buffer = new Uint8Array(bytes)
  crypto.getRandomValues(buffer)
  return base64Url(buffer)
}

function base64Url(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  return base64Url(new Uint8Array(digest))
}

/**
 * Reduce a caller-supplied destination to something safe to redirect to.
 *
 * Only a path on this site survives. `//evil.test` and `https://evil.test` are
 * both absolute despite the first looking relative, and a backslash is treated
 * as a separator by some browsers -- so the check is what the value *is*, not
 * what it is missing.
 */
export function safeReturnPath(value: string | null | undefined, fallback = '/'): string {
  if (!value) return fallback
  if (!value.startsWith('/')) return fallback
  const BACKSLASH = String.fromCharCode(92)
  if (value.startsWith('//') || value.startsWith('/' + BACKSLASH)) return fallback
  return value
}

/**
 * A token exchange that failed, carrying the status for the server log only.
 */
export class ExchangeError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ExchangeError'
    this.status = status
  }
}


/**
 * Refuse to build an authorize URL out of settings that cannot make one.
 *
 * `ZITADEL_DOMAIN` held a bare hostname where a base URL was meant, so the
 * authorize URL came out as a relative path, NextResponse.redirect rejected
 * it, and the sign-in route answered 500. Both applications, all four
 * environments, and nothing anywhere said which of seventeen settings was
 * wrong -- the browser showed `This page isn't working` and the logs an
 * `Invalid URL` from inside the framework.
 *
 * The value is never included in the message. Which setting is wrong is the
 * useful part; what it currently contains would put configuration into logs
 * and error pages.
 */
function requireSettings(options: {
  zitadelDomain: string
  clientId: string
  redirectUri: string
}): void {
  const missing = (
    [
      ['ZITADEL_DOMAIN', options.zitadelDomain],
      ['ZITADEL_CLIENT_ID', options.clientId],
      ['ZITADEL_ADMIN_REDIRECT_URI', options.redirectUri],
    ] as const
  )
    .filter(([, value]) => value.trim() === '')
    .map(([name]) => name)

  if (missing.length > 0) {
    throw new Error(`Sign-in is not configured: ${missing.join(', ')} is empty.`)
  }

  // An absolute http(s) origin. A hostname alone parses as nothing, and a
  // path-only value silently produces a same-site redirect loop.
  let parsed: URL
  try {
    parsed = new URL(options.zitadelDomain)
  } catch {
    throw new Error(
      'Sign-in is not configured: ZITADEL_DOMAIN must be a base URL including' +
        ' the scheme, for example https://auth.example.com.',
    )
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    throw new Error(
      `Sign-in is not configured: ZITADEL_DOMAIN uses ${parsed.protocol} rather` +
        ' than http or https.',
    )
  }
}

/**
 * What a KORAS sign-in asks for.
 *
 * `openid email profile` is the person; the roles scope is what makes ZITADEL
 * put this project's role claim in the token, which is what every authorisation
 * decision downstream reads.
 */
export const SIGN_IN_SCOPE = 'openid email profile urn:zitadel:iam:org:project:roles'

/**
 * Ask ZITADEL to address the token to a second project as well.
 *
 * A resource server verifies `aud` against its own project and never widens
 * that, so a token minted for one application is refused by another — correctly.
 * This reserved scope is the supported way to say, at sign-in, that the token
 * this application receives is also meant for a named second project.
 *
 * It is how one application may call another's API **as the person signed in**,
 * rather than by holding a machine credential that can act for everybody. The
 * audience is a project identifier, not a secret: it grants nothing on its own,
 * and the token still carries only this caller's identity and roles.
 *
 * An empty or absent project id leaves the scope alone rather than emitting a
 * malformed one, because a scope ZITADEL cannot parse fails the whole sign-in
 * and not just the call that wanted it.
 */
export function withProjectAudience(scope: string, projectId: string | undefined): string {
  const trimmed = (projectId ?? '').trim()
  if (trimmed === '') return scope
  return `${scope} urn:zitadel:iam:org:project:id:${trimmed}:aud`
}

export async function beginAuthorization(options: {
  zitadelDomain: string
  clientId: string
  redirectUri: string
  returnTo?: string | null
  scope?: string
}): Promise<AuthorizationStart> {
  requireSettings(options)

  const state = randomToken()
  const codeVerifier = randomToken(64)
  const params = new URLSearchParams({
    client_id: options.clientId,
    redirect_uri: options.redirectUri,
    response_type: 'code',
    scope: options.scope ?? SIGN_IN_SCOPE,
    state,
    code_challenge: await challengeFor(codeVerifier),
    code_challenge_method: 'S256',
  })

  return {
    url: `${options.zitadelDomain.replace(/\/$/, '')}/oauth/v2/authorize?${params.toString()}`,
    state,
    codeVerifier,
    returnTo: safeReturnPath(options.returnTo),
  }
}

export interface TokenSet {
  idToken: string
  accessToken?: string
  expiresIn?: number
}

/**
 * Exchange the code for tokens.
 *
 * The state comparison happens before this is called and is a constant-time
 * length-and-content check rather than `===` on a secret. The difference is
 * small here because both values are the same length, but a comparison that
 * short-circuits on the first differing byte is the wrong habit to establish in
 * a file about CSRF tokens.
 */
export async function exchangeCode(options: {
  zitadelDomain: string
  clientId: string
  clientSecret?: string
  redirectUri: string
  code: string
  codeVerifier: string
  fetchImpl?: typeof fetch
}): Promise<TokenSet> {
  const doFetch = options.fetchImpl ?? fetch

  // The application is registered with ZITADEL as a confidential client
  // (OIDC_AUTH_METHOD_TYPE_BASIC), so its token endpoint requires HTTP Basic
  // authentication. This sent no secret at all -- a public-client exchange
  // against a confidential client -- so ZITADEL rejected every code and the
  // sign-in died one step from finishing, on the one page whose message is
  // deliberately identical for every cause.
  //
  // ZITADEL_CLIENT_SECRET was already a managed setting, present in Doppler
  // and in every deployed environment. Nothing read it.
  //
  // PKCE stays. The two are not alternatives: the secret authenticates the
  // application, the verifier binds the code to the browser that started the
  // flow, and only the second survives a leaked secret.
  const headers: Record<string, string> = {
    'Content-Type': 'application/x-www-form-urlencoded',
  }
  if (options.clientSecret) {
    // RFC 6749 2.3.1: both halves are form-urlencoded before base64.
    const credential = `${encodeURIComponent(options.clientId)}:${encodeURIComponent(options.clientSecret)}`
    headers.Authorization = `Basic ${btoa(credential)}`
  }

  const response = await doFetch(`${options.zitadelDomain.replace(/\/$/, '')}/oauth/v2/token`, {
    method: 'POST',
    headers,
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: options.clientId,
      redirect_uri: options.redirectUri,
      code: options.code,
      code_verifier: options.codeVerifier,
    }),
  })

  if (!response.ok) {
    // The caller is told nothing: distinguishing an expired code from an
    // unknown one tells whoever is probing which guess was closer.
    //
    // The status is on the error rather than in the response, so a route
    // handler can log it and still answer with the one flat message. This
    // failure was invisible for exactly that reason -- the browser said `The
    // sign-in could not be completed` and so did the server, about a 401 that
    // would have named the problem immediately.
    throw new ExchangeError('The sign-in could not be completed.', response.status)
  }

  const body = (await response.json()) as {
    id_token?: string
    access_token?: string
    expires_in?: number
  }
  if (!body.id_token) {
    throw new ExchangeError('The sign-in could not be completed.', response.status)
  }

  return { idToken: body.id_token, accessToken: body.access_token, expiresIn: body.expires_in }
}

/** Timing-safe equality for values that decide whether a login is honoured. */
export function tokensMatch(a: string | undefined, b: string | undefined): boolean {
  if (!a || !b || a.length !== b.length) return false
  let difference = 0
  for (let index = 0; index < a.length; index += 1) {
    difference |= a.charCodeAt(index) ^ b.charCodeAt(index)
  }
  return difference === 0
}

/**
 * How every cookie this flow sets is written.
 *
 * `httpOnly` so a script cannot read the session even if one is injected;
 * `secure` everywhere TLS exists; `sameSite: 'lax'` because the callback is a
 * top-level navigation from the identity provider -- `strict` would withhold
 * the cookie on exactly that request and the flow would never complete, which
 * is the trap that makes people give up and use `none`.
 */
export function cookieOptions(options: { secure: boolean; maxAge: number }) {
  return {
    httpOnly: true,
    secure: options.secure,
    sameSite: 'lax' as const,
    path: '/',
    maxAge: options.maxAge,
  }
}
