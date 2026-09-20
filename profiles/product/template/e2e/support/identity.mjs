/**
 * A local identity provider, so the API can verify a real token.
 *
 * The API verifies an access token the way it does in production: it fetches
 * `/.well-known/openid-configuration`, follows `jwks_uri`, and checks an RS256
 * signature, the audience, the issuer and the expiry against the keys it finds
 * there. **Nothing in the API is bypassed and nothing is stubbed inside it.**
 * What is local is the provider, not the verification.
 *
 * That is the same position `session.ts` already takes about the browser
 * cookie: the suite signs one with the application's own minting function and
 * the middleware verifies it, so a test signs in the way a person does and is
 * refused the same way. A bypass in the API would be a bypass that exists in
 * shipped code, and the day somebody sets the flag in an environment that
 * matters it is not a test fixture any more.
 *
 * ## The key is generated, never committed
 *
 * A keypair is made at startup and the private half is written to
 * `.e2e/identity.json`, which is ignored. A committed private key — even one
 * labelled a test key — is a secret scanner's finding forever and an invitation
 * to reuse. Generating costs milliseconds once per run.
 *
 * ## What this is not
 *
 * Not ZITADEL. It serves two documents and signs tokens; it has no users, no
 * sessions, no consent and no login page. The product's own sign-in page is
 * checked by the browser suite against the real provider's contract, and this
 * server would answer nothing it asked.
 */

import { generateKeyPairSync, createPublicKey } from 'node:crypto'
import { createServer } from 'node:http'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'

const PORT = Number(process.env.E2E_IDENTITY_PORT ?? 3212)

/**
 * The issuer, and it must be **the same string** the API is pointed at.
 *
 * `verify_token` pins the issuer, so a token minted as `http://localhost:3212`
 * and verified against `http://127.0.0.1:3212` is rejected — correctly, and
 * with the same 401 a forged token gets, which is a confusing half hour if the
 * two are allowed to drift. Playwright passes one value to this server and to
 * the API, and this default matches the one in `playwright.config.ts`.
 */
const ISSUER = process.env.E2E_IDENTITY_URL ?? `http://127.0.0.1:${PORT}`
const KEY_ID = 'e2e-signing-key'

/** Where the private half is left for the suite to mint with. */
export const KEY_FILE = resolve(process.cwd(), '.e2e', 'identity.json')

const { publicKey, privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })

const jwk = publicKey.export({ format: 'jwk' })
const publicJwk = { ...jwk, kid: KEY_ID, use: 'sig', alg: 'RS256' }
const privateJwk = { ...privateKey.export({ format: 'jwk' }), kid: KEY_ID, alg: 'RS256' }

mkdirSync(dirname(KEY_FILE), { recursive: true })
writeFileSync(
  KEY_FILE,
  JSON.stringify({ issuer: ISSUER, keyId: KEY_ID, privateJwk, publicJwk }, null, 2),
)

const DISCOVERY = {
  issuer: ISSUER,
  jwks_uri: `${ISSUER}/oauth/v2/keys`,
  // Present because a discovery document without them is not one, and absent
  // from anything this serves: no flow runs here.
  authorization_endpoint: `${ISSUER}/oauth/v2/authorize`,
  token_endpoint: `${ISSUER}/oauth/v2/token`,
  response_types_supported: ['code'],
  subject_types_supported: ['public'],
  id_token_signing_alg_values_supported: ['RS256'],
}

const server = createServer((request, response) => {
  const url = new URL(request.url ?? '/', ISSUER)
  const body =
    url.pathname === '/.well-known/openid-configuration'
      ? DISCOVERY
      : url.pathname === '/oauth/v2/keys'
        ? { keys: [publicJwk] }
        : null

  if (body === null) {
    response.writeHead(404, { 'content-type': 'application/json' })
    response.end(JSON.stringify({ error: 'not_found', path: url.pathname }))
    return
  }
  response.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' })
  response.end(JSON.stringify(body))
})

server.listen(PORT, () => {
  // Playwright waits for the discovery document rather than for this line, but
  // a run that fails to start should say which port it wanted.
  console.log(`e2e identity provider on ${ISSUER}`)
})

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => server.close(() => process.exit(0)))
}
