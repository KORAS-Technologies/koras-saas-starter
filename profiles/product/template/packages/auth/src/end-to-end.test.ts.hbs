import assert from 'node:assert/strict'
import test, { afterEach } from 'node:test'
import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { SignJWT, exportJWK, generateKeyPair } from 'jose'
import type { NextRequest } from 'next/server'

import { mintSession, readSession, resolveToken } from './index.js'

/**
 * Sign-in end to end, the way the callback actually composes it.
 *
 * Both halves were tested and the join between them was not, which is exactly
 * where the Control Plane's signed-in super admin arrived carrying no role at
 * all and its middleware answered that the application was for staff only.
 *
 * The token here is shaped the way ZITADEL shapes one: roles as an object
 * keyed by role name, each mapping org id to domain.
 */

const CLIENT_ID = '386896303902229933'
const SECRET = 'a'.repeat(48)

const servers: Array<ReturnType<typeof createServer>> = []
afterEach(async () => {
  await Promise.all(
    servers.splice(0).map((s) => new Promise<void>((r) => s.close(() => r()))),
  )
})

async function zitadel() {
  const { publicKey, privateKey } = await generateKeyPair('RS256')
  const jwk = { ...(await exportJWK(publicKey)), kid: 'k', alg: 'RS256', use: 'sig' }
  const server = createServer((req, res) => {
    if (req.url !== '/oauth/v2/keys') return void res.writeHead(404).end()
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ keys: [jwk] }))
  })
  servers.push(server)
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r))
  const domain = `http://127.0.0.1:${(server.address() as AddressInfo).port}`

  const idToken = (claims: Record<string, unknown>) =>
    new SignJWT(claims)
      .setProtectedHeader({ alg: 'RS256', kid: 'k' })
      .setIssuedAt()
      .setExpirationTime('10m')
      .setAudience(CLIENT_ID)
      .setIssuer(domain)
      .sign(privateKey)

  return { domain, idToken }
}

const requestWith = (token: string) =>
  ({ cookies: { get: () => ({ value: token }) } }) as unknown as NextRequest

test('a staff role survives the whole sign-in', async () => {
  const { domain, idToken } = await zitadel()
  const token = await idToken({
    sub: '386573749426182494',
    email: 'member@example.com',
    name: 'A Person',
    amr: ['pwd', 'otp'],
    'urn:zitadel:iam:org:project:roles': {
      organization_owner: { '386573749425658206': 'example.com' },
      billing_admin: { '386573749425658206': 'example.com' },
    },
  })

  // Exactly what the callback does.
  const outcome = await resolveToken(token, {
    zitadelDomain: domain,
    clientId: CLIENT_ID,
    requireMfa: false,
  })
  assert.equal(outcome.status, 'ok')
  assert.ok(outcome.status === 'ok')
  assert.deepEqual(
    outcome.session.organizationRoles,
    ['billing_admin', 'organization_owner'],
    'the provider token carried no roles',
  )

  const cookie = await mintSession(outcome.session, SECRET, Math.floor(Date.now() / 1000) + 3600)

  // Exactly what the middleware does.
  const read = await readSession(requestWith(cookie), { secret: SECRET })
  assert.equal(read.status, 'ok')
  assert.ok(read.status === 'ok')
  assert.deepEqual(
    read.session.organizationRoles,
    ['billing_admin', 'organization_owner'],
    'the roles were lost between minting and reading',
  )
  assert.equal(read.session.email, 'member@example.com')
  assert.equal(read.session.usedMfa, true)
})

test('a token with no roles claim yields no roles, and says so plainly', async () => {
  // The state a misconfigured provider produces. The refusal is correct; what
  // was missing was any way to tell it apart from a broken application.
  const { domain, idToken } = await zitadel()
  const token = await idToken({ sub: 'user-1', amr: ['pwd', 'otp'] })

  const outcome = await resolveToken(token, { zitadelDomain: domain, clientId: CLIENT_ID })
  assert.equal(outcome.status, 'ok')
  assert.ok(outcome.status === 'ok')
  assert.deepEqual(outcome.session.organizationRoles, [])
})
