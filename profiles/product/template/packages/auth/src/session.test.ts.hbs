import assert from 'node:assert/strict'
import test, { afterEach } from 'node:test'
import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { SignJWT, exportJWK, generateKeyPair } from 'jose'
import type { NextRequest } from 'next/server'

import { jwksUrl, resolveSession, resolveToken, verifySession } from './index.js'

/**
 * Verifying the session cookie.
 *
 * There were no tests here, and the consequence was a sign-in that completed
 * and then bounced straight back to the login page. The audience was checked
 * against the *project* id, which an OIDC ID token does not carry -- its `aud`
 * is the client id. Every token failed, verifySession returned null, and the
 * middleware treated a valid session as no session at all.
 *
 * From outside, a completed sign-in landing on the login screen is
 * indistinguishable from one that never happened. That is what makes this
 * worth testing rather than reading.
 */

const CLIENT_ID = '386896303902229933'
const PROJECT_ID = '386896303700837805'

const servers: Array<ReturnType<typeof createServer>> = []

afterEach(async () => {
  await Promise.all(
    servers.splice(0).map(
      (server) => new Promise<void>((resolve) => server.close(() => resolve())),
    ),
  )
})

/**
 * A ZITADEL that actually signs things, over a real socket.
 *
 * `createRemoteJWKSet` fetches the key set through Node's HTTP stack rather
 * than `globalThis.fetch`, so stubbing fetch does nothing -- the first version
 * of this harness did exactly that and the tests failed on a DNS lookup for
 * `example.com`. Serving the real thing is also the more honest test: a
 * stubbed verifier would pass whatever it was told to.
 *
 * Each issuer gets its own port. The key set is cached per domain for the
 * lifetime of the process, so a shared one would let the first test's keys
 * verify the second test's tokens.
 */
async function issuer() {
  const { publicKey, privateKey } = await generateKeyPair('RS256')
  const jwk = { ...(await exportJWK(publicKey)), kid: 'test', alg: 'RS256', use: 'sig' }

  const server = createServer((request, response) => {
    if (request.url !== '/oauth/v2/keys') {
      response.writeHead(404).end()
      return
    }
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify({ keys: [jwk] }))
  })
  servers.push(server)
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const { port } = server.address() as AddressInfo
  const domain = `http://127.0.0.1:${port}`

  const sign = (claims: Record<string, unknown>, audience: string | string[]) =>
    new SignJWT(claims)
      .setProtectedHeader({ alg: 'RS256', kid: 'test' })
      .setIssuedAt()
      .setExpirationTime('10m')
      .setAudience(audience)
      // ZITADEL sets `iss` to its own base URL, and verification now requires
      // it. A helper that signed without one would make every test here
      // exercise a token no real provider issues.
      .setIssuer(domain)
      .sign(privateKey)

  /** Signs with the right key but an issuer of the caller's choosing. */
  const signAs = (iss: string, claims: Record<string, unknown>, audience: string | string[]) =>
    new SignJWT(claims)
      .setProtectedHeader({ alg: 'RS256', kid: 'test' })
      .setIssuedAt()
      .setExpirationTime('10m')
      .setAudience(audience)
      .setIssuer(iss)
      .sign(privateKey)

  return { domain, sign, signAs }
}

function requestWith(token?: string): NextRequest {
  return {
    cookies: { get: (name: string) => (name === 'session' && token ? { value: token } : undefined) },
  } as unknown as NextRequest
}

test('a token addressed to the client id is accepted', async () => {
  // The case that was broken. ZITADEL issues ID tokens with aud = client_id.
  const { domain, sign } = await issuer()
  const token = await sign({ sub: 'user-1', amr: ['pwd', 'otp'] }, CLIENT_ID)

  const session = await verifySession(requestWith(token), {
    zitadelDomain: domain,
    clientId: CLIENT_ID,
    projectId: PROJECT_ID,
  })

  assert.ok(session, 'a valid ID token was rejected')
  assert.equal(session.userId, 'user-1')
})

test('a token from another issuer is rejected', async () => {
  // The check this test was written for. The key set already makes a foreign
  // signature fail, so the only way to exercise `iss` on its own is to sign
  // with the *right* key and claim the wrong issuer -- which is exactly the
  // token a second ZITADEL instance behind the same key material would
  // produce, and exactly what OIDC Core 3.1.3.7 step 3 exists to refuse.
  const { domain, signAs } = await issuer()
  const token = await signAs('https://not-this-instance.example', { sub: 'user-1' }, CLIENT_ID)

  const session = await verifySession(requestWith(token), {
    zitadelDomain: domain,
    clientId: CLIENT_ID,
    projectId: PROJECT_ID,
  })

  assert.equal(session, null, 'a token claiming another issuer was accepted')
})

test('a token addressed to the project id is also accepted', async () => {
  // ZITADEL puts the project id in the audience of access tokens.
  const { domain, sign } = await issuer()
  const token = await sign({ sub: 'user-1' }, PROJECT_ID)

  const session = await verifySession(requestWith(token), {
    zitadelDomain: domain,
    clientId: CLIENT_ID,
    projectId: PROJECT_ID,
  })

  assert.ok(session)
})

test("a token addressed to someone else is refused", async () => {
  const { domain, sign } = await issuer()
  const token = await sign({ sub: 'user-1' }, 'a-different-application')

  const session = await verifySession(requestWith(token), {
    zitadelDomain: domain,
    clientId: CLIENT_ID,
    projectId: PROJECT_ID,
  })

  assert.equal(session, null)
})

test('an unconfigured client id refuses everything rather than accepting anything', async () => {
  // The failure mode to avoid while fixing the first one: an empty audience
  // list must not become "accept any audience".
  const { domain, sign } = await issuer()
  const token = await sign({ sub: 'user-1' }, CLIENT_ID)

  const session = await verifySession(requestWith(token), {
    zitadelDomain: domain,
    clientId: '',
    projectId: '',
  })

  assert.equal(session, null)
})

test('organization roles are read from the project roles claim', async () => {
  const { domain, sign } = await issuer()
  const token = await sign(
    {
      sub: 'user-1',
      amr: ['pwd', 'otp'],
      'urn:zitadel:iam:org:project:roles': {
        organization_admin: { org: 'example.com' },
        billing_admin: { org: 'example.com' },
        platform_super_admin: { org: 'example.com' },
      },
    },
    CLIENT_ID,
  )

  const session = await verifySession(requestWith(token), {
    zitadelDomain: domain,
    clientId: CLIENT_ID,
  })

  // Every recognised role, not one resolved role: billing_admin and
  // security_admin are scoped authorities a member may hold alongside others,
  // and collapsing to one would silently drop the rest.
  //
  // platform_super_admin is absent because this profile does not define it. A
  // staff role arriving in a product's token is an unrecognised name here.
  assert.deepEqual(session?.organizationRoles, ['billing_admin', 'organization_admin'])
  assert.equal(session?.usedMfa, true)
})

test('a caller without a second factor is refused, and distinguishably so', async () => {
  // This returned null, which the middleware could only read as "not signed
  // in" -- so it redirected to the login page, which cannot add a second
  // factor to an existing session, so the browser looped forever showing the
  // login screen as though nothing had happened.
  const { domain, sign } = await issuer()
  const token = await sign(
    {
      sub: 'user-1',
      amr: ['pwd'],
      'urn:zitadel:iam:org:project:roles': { organization_admin: { org: 'example.com' } },
    },
    CLIENT_ID,
  )

  const outcome = await resolveSession(requestWith(token), {
    zitadelDomain: domain,
    clientId: CLIENT_ID,
    requireMfa: true,
  })

  assert.equal(outcome.status, 'mfa-required')
  // Not anonymous: the caller is known, and telling them to enrol is only
  // possible because the two are no longer the same answer.
  assert.equal(outcome.status === 'mfa-required' && outcome.session.userId, 'user-1')
})

test('an invalid token is anonymous, not merely unauthorised', async () => {
  // The distinction the loop depended on. These must not collapse again.
  const { domain, sign } = await issuer()
  const token = await sign({ sub: 'user-1' }, 'someone-else')

  const outcome = await resolveSession(requestWith(token), {
    zitadelDomain: domain,
    clientId: CLIENT_ID,
  })

  assert.equal(outcome.status, 'anonymous')
})

test('the compatibility wrapper still refuses an unverified second factor', async () => {
  // verifySession collapses the outcomes deliberately. It must not start
  // admitting a session that skipped MFA where MFA was asked for.
  const { domain, sign } = await issuer()
  const token = await sign(
    {
      sub: 'user-1',
      amr: ['pwd'],
      'urn:zitadel:iam:org:project:roles': { organization_admin: { org: 'example.com' } },
    },
    CLIENT_ID,
  )

  const session = await verifySession(requestWith(token), {
    zitadelDomain: domain,
    clientId: CLIENT_ID,
    requireMfa: true,
  })

  assert.equal(session, null)
})

test('no cookie is not a session', async () => {
  const session = await verifySession(requestWith(undefined), {
    zitadelDomain: 'http://127.0.0.1:1',
    clientId: CLIENT_ID,
  })
  assert.equal(session, null)
})

test('the key set is fetched from the ZITADEL base URL, once', async () => {
  // A 404 fetching the key set and a token that simply does not verify are the
  // same silent redirect from outside, and the first is a wrong setting rather
  // than a wrong token. This pins the URL that gets built, because a live
  // deployment was fetching one that 404s and nothing said which.
  assert.equal(
    jwksUrl('https://auth-dev.example.com'),
    'https://auth-dev.example.com/oauth/v2/keys',
  )
  // A trailing slash must not double up: //oauth/v2/keys is a redirect, and
  // jose does not follow it.
  assert.equal(
    jwksUrl('https://auth-dev.example.com/'),
    'https://auth-dev.example.com/oauth/v2/keys',
  )
})

test('the organization comes from the roles claim', async () => {
  // urn:zitadel:iam:org:id is the obvious claim and ZITADEL does not send it
  // unless the authorization request named an organization -- which a login
  // form cannot. Reading only that claim meant every customer token carried no
  // organization and the portal refused every one of them.
  const { domain, sign } = await issuer()
  const token = await sign(
    {
      sub: 'user-1',
      email: 'owner@acme.test',
      'urn:zitadel:iam:org:project:roles': {
        organization_owner: { '387583042916472982': 'acme.example' },
      },
    },
    CLIENT_ID,
  )

  const outcome = await resolveToken(token, { zitadelDomain: domain, clientId: CLIENT_ID })
  assert.equal(outcome.status, 'ok')
  assert.ok(outcome.status === 'ok')
  assert.equal(outcome.session.organizationId, '387583042916472982')
})

test('a token naming two organizations carries none', async () => {
  // Refused rather than guessed: picking one would scope a session to whichever
  // came first, which is how someone reads another company's data with no error
  // anywhere.
  const { domain, sign } = await issuer()
  const token = await sign(
    {
      sub: 'user-1',
      email: 'owner@acme.test',
      'urn:zitadel:iam:org:project:roles': {
        organization_owner: { 'org-one': 'one.example' },
        member: { 'org-two': 'two.example' },
      },
    },
    CLIENT_ID,
  )

  const outcome = await resolveToken(token, { zitadelDomain: domain, clientId: CLIENT_ID })
  assert.ok(outcome.status === 'ok')
  assert.equal(outcome.session.organizationId, undefined)
})
