#!/usr/bin/env node
/**
 * Mint the bearer token that registration presents to the Control Plane.
 *
 *   pnpm koras:token                 # mint, verify, print nothing secret
 *   pnpm koras:token --set           # ...and store it as KORAS_CONTROL_PLANE_TOKEN
 *
 * Why this exists. `create-koras-app` reads a finished bearer token from
 * Doppler as `KORAS_CONTROL_PLANE_TOKEN`. The credential behind it is a ZITADEL
 * access token for the `registrar` service account, and ZITADEL will not hand
 * one over for a password -- it wants a signed assertion, exchanged under the
 * JWT-profile grant, carrying the Control Plane's project in its audience.
 *
 * Signing an RS256 assertion is not something anyone should do at a shell
 * prompt, and the walkthrough previously said "sign a short assertion with it"
 * as though it were a step. This is that step.
 *
 * Nothing here prints a token, a key, or an assertion. `--set` writes the token
 * to Doppler through stdin, so it never reaches the terminal, the process table
 * or the shell history.
 *
 * The token lasts twelve hours. That is a property of the token and not of this
 * script, and it is why the generator should eventually hold the key and mint
 * per call rather than reading a stored one -- see F2a in docs/FOLLOW_UPS.md.
 * When that lands, this script becomes a diagnostic rather than a step.
 */

import { createSign } from 'node:crypto'
import { spawnSync } from 'node:child_process'

const DOPPLER_PROJECT = 'koras-platform-bootstrap'
const DOPPLER_CONFIG = 'prod'

const KEY_VAR = 'KORAS_CONTROL_PLANE_KEY_JSON'
const URL_VAR = 'KORAS_CONTROL_PLANE_URL'
const PROJECT_VAR = 'KORAS_CONTROL_PLANE_PROJECT_ID'
const TOKEN_VAR = 'KORAS_CONTROL_PLANE_TOKEN'

const shouldSet = process.argv.includes('--set')

/**
 * Re-run under Doppler rather than asking anyone to type the wrapper.
 *
 * The same thing bootstrap:doctor and teardown do, and for the same reason: a
 * wrapper typed by hand is a wrapper forgotten by hand. An outer one is
 * detected rather than nested.
 */
if (!process.env[KEY_VAR] && !process.env.DOPPLER_PROJECT) {
  console.log(`==> Fetching credentials from ${DOPPLER_PROJECT}/${DOPPLER_CONFIG}`)
  const result = spawnSync(
    'doppler',
    ['run', '--project', DOPPLER_PROJECT, '--config', DOPPLER_CONFIG, '--',
      process.execPath, ...process.argv.slice(1)],
    { stdio: 'inherit' },
  )
  process.exit(result.status ?? 1)
}

function required(name, hint) {
  const value = process.env[name]?.trim()
  if (!value) {
    console.error(`${name} is not set in ${DOPPLER_PROJECT}/${DOPPLER_CONFIG}.`)
    console.error(hint)
    process.exit(2)
  }
  return value
}

const baseUrl = required(URL_VAR,
  'It is the Control Plane API origin, e.g. https://koras-control-plane-api-dev.fly.dev')

// Which environment's ZITADEL minted the registrar, decided by the Control
// Plane the URL names rather than by a separate answer that could disagree
// with it. A token minted in dev is not valid at the prod Control Plane, and
// that mismatch is a 401 that reads exactly like an expired token.
const environment = baseUrl.match(/-api-(dev|test|stg|prod)\./)?.[1]
if (!environment) {
  console.error(`Cannot tell which environment ${baseUrl} is.`)
  console.error('Expected a host like <repository>-api-<dev|test|stg|prod>.fly.dev.')
  console.error(`Set ZITADEL_DOMAIN_OVERRIDE if this Control Plane has a custom hostname.`)
  process.exit(2)
}

const zitadel = (process.env.ZITADEL_DOMAIN_OVERRIDE
  || required(`ZITADEL_${environment.toUpperCase()}_DOMAIN`,
    'It is the ZITADEL instance backing that Control Plane.')).replace(/\/+$/, '')
const instance = zitadel.startsWith('http') ? zitadel : `https://${zitadel}`

const projectId = required(PROJECT_VAR,
  `It is the Control Plane's ZITADEL project id for ${environment}. Read it with:\n` +
  `  doppler secrets get ZITADEL_PROJECT_ID --plain --project koras-control-plane --config ${environment}`)

const key = JSON.parse(required(KEY_VAR,
  "It is the registrar service account's JSON key, downloaded from ZITADEL."))

if (key.type !== 'serviceaccount' || !key.key || !key.userId || !key.keyId) {
  console.error(`${KEY_VAR} is not a ZITADEL service-account key.`)
  console.error('Expected an object with type, keyId, key and userId.')
  process.exit(2)
}

console.log(`==> Control Plane : ${baseUrl}  (${environment})`)
console.log(`    ZITADEL       : ${instance}`)
console.log(`    service user  : ${key.userId}`)

const b64url = (input) =>
  Buffer.from(input).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

const now = Math.floor(Date.now() / 1000)
const signingInput = [
  b64url(JSON.stringify({ alg: 'RS256', typ: 'JWT', kid: key.keyId })),
  // Issuer and subject are the service user; the audience is the instance
  // itself, because this assertion is addressed to ZITADEL and only the token
  // it returns is addressed to the Control Plane.
  b64url(JSON.stringify({
    iss: key.userId, sub: key.userId, aud: instance, iat: now, exp: now + 300,
  })),
].join('.')

const signer = createSign('RSA-SHA256')
signer.update(signingInput)
const assertion = `${signingInput}.${b64url(signer.sign(key.key))}`

// The audience is not implicit. ZITADEL puts a project into the token only when
// this reserved scope asks it to, and the Control Plane accepts a token
// addressed to its own project or client id and nothing else.
const scope = `openid urn:zitadel:iam:org:project:id:${projectId}:aud`

const exchange = await fetch(`${instance}/oauth/v2/token`, {
  method: 'POST',
  headers: { 'content-type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({
    grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
    assertion,
    scope,
  }),
})

if (!exchange.ok) {
  console.error(`ZITADEL refused the exchange (HTTP ${exchange.status}).`)
  console.error(await exchange.text())
  process.exit(1)
}

const { access_token: token, expires_in: expiresIn } = await exchange.json()

// A service account left on ZITADEL's default access token type issues an
// opaque token. The Control Plane verifies against a JWKS key set, so an opaque
// token cannot be verified at all -- the grant succeeds and every registration
// then fails with 401. Caught here, where the cause is still visible.
if (token.split('.').length !== 3) {
  console.error('ZITADEL returned an opaque token, which the Control Plane cannot verify.')
  console.error(`Set the access token type of service user ${key.userId} to JWT:`)
  console.error(`  ${instance}/ui/console/users?type=machine -> the account -> Access Token Type`)
  process.exit(1)
}

console.log(`    token         : JWT, valid for ${Math.round(expiresIn / 3600)} hours`)

// Proved against the real endpoint rather than assumed from the shape of the
// token. An empty body is refused as 422 once the identity is accepted, which
// is the only outcome that distinguishes a good token from a well-formed one.
const probe = await fetch(`${baseUrl.replace(/\/+$/, '')}/api/platform/v1/products`, {
  method: 'POST',
  headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
  body: '{}',
})

if (probe.status === 422) {
  console.log('    accepted      : yes (422 on an empty body, which is the identity passing)')
} else if (probe.status === 401) {
  console.error('The Control Plane rejected the token (401).')
  console.error(`Its audience must contain ${projectId}; check ${PROJECT_VAR} is this`)
  console.error(`environment's Control Plane project, and that the key came from ${instance}.`)
  process.exit(1)
} else if (probe.status === 403) {
  console.error('The Control Plane rejected the identity (403).')
  console.error('Registration admits machines only. The service user must carry no email')
  console.error('claim and must hold no platform role -- granting it platform_admin breaks this.')
  process.exit(1)
} else {
  console.error(`Unexpected response from the Control Plane: HTTP ${probe.status}`)
  console.error((await probe.text()).slice(0, 300))
  process.exit(1)
}

if (!shouldSet) {
  console.log('')
  console.log(`Not stored. Re-run with --set to write it to ${TOKEN_VAR}.`)
  process.exit(0)
}

// Through stdin, so the token reaches neither the terminal, the process table,
// nor the shell history.
const stored = spawnSync(
  'doppler',
  ['secrets', 'set', TOKEN_VAR, '--project', DOPPLER_PROJECT, '--config', DOPPLER_CONFIG,
    '--silent', '--no-interactive'],
  { input: token, stdio: ['pipe', 'inherit', 'inherit'] },
)

if (stored.status !== 0) {
  console.error(`Could not write ${TOKEN_VAR} to ${DOPPLER_PROJECT}/${DOPPLER_CONFIG}.`)
  process.exit(1)
}

console.log(`    stored        : ${TOKEN_VAR} in ${DOPPLER_PROJECT}/${DOPPLER_CONFIG}`)
console.log('')
console.log(`Valid for ${Math.round(expiresIn / 3600)} hours. Provision within that window.`)
