import assert from 'node:assert/strict'
import test from 'node:test'

import { beginAuthorization, exchangeCode, safeReturnPath, tokensMatch } from './oauth.js'

/**
 * The flow used to carry the post-login destination in `state`, which is two
 * defects in one parameter: a predictable CSRF token, and an open redirect.
 * These tests attack both.
 */

test('a destination outside this site is refused', () => {
  const backslash = String.fromCharCode(92)
  for (const hostile of [
    'https://evil.example.com',
    '//evil.example.com',
    `/${backslash}evil.example.com`,
    'javascript:alert(1)',
    'http://evil.example.com/path',
  ]) {
    assert.equal(safeReturnPath(hostile), '/', `${hostile} was accepted as a destination`)
  }
})

test('a path on this site survives', () => {
  assert.equal(safeReturnPath('/organizations/42'), '/organizations/42')
  assert.equal(safeReturnPath('/'), '/')
})

test('nothing at all falls back rather than throwing', () => {
  assert.equal(safeReturnPath(undefined), '/')
  assert.equal(safeReturnPath(null), '/')
  assert.equal(safeReturnPath(''), '/')
})

test('every authorization gets a fresh state and verifier', async () => {
  const options = {
    zitadelDomain: 'https://id.example.com',
    clientId: 'client-1',
    redirectUri: 'https://admin.example.com/api/auth/callback',
  }
  const first = await beginAuthorization(options)
  const second = await beginAuthorization(options)

  // A state reused across sign-ins is a state an attacker can predict from one
  // they have already seen.
  assert.notEqual(first.state, second.state)
  assert.notEqual(first.codeVerifier, second.codeVerifier)
  assert.ok(first.state.length >= 32)
})

test('the authorize url carries PKCE and never carries the destination', async () => {
  const start = await beginAuthorization({
    zitadelDomain: 'https://id.example.com',
    clientId: 'client-1',
    redirectUri: 'https://admin.example.com/api/auth/callback',
    returnTo: '/organizations/42',
  })

  const url = new URL(start.url)
  assert.equal(url.searchParams.get('code_challenge_method'), 'S256')
  assert.ok((url.searchParams.get('code_challenge') ?? '').length > 0)
  assert.equal(url.searchParams.get('state'), start.state)
  // The destination travels in a cookie. In the URL it would be attacker-visible
  // and attacker-editable, which is exactly how it became an open redirect.
  assert.ok(!start.url.includes('/organizations/42'))
  assert.equal(start.returnTo, '/organizations/42')
})

test('the challenge is a hash of the verifier, not the verifier', async () => {
  const start = await beginAuthorization({
    zitadelDomain: 'https://id.example.com',
    clientId: 'client-1',
    redirectUri: 'https://admin.example.com/api/auth/callback',
  })
  const challenge = new URL(start.url).searchParams.get('code_challenge')
  assert.notEqual(challenge, start.codeVerifier)
})

test('state comparison rejects a near miss and a length mismatch', () => {
  assert.equal(tokensMatch('abcdef', 'abcdef'), true)
  assert.equal(tokensMatch('abcdef', 'abcdeg'), false)
  assert.equal(tokensMatch('abcdef', 'abcde'), false)
  assert.equal(tokensMatch(undefined, undefined), false, 'two absent values must not match')
  assert.equal(tokensMatch('', ''), false, 'two empty values must not match')
})

test('a failed exchange does not repeat what the provider said', async () => {
  const fetchImpl = (async () =>
    new Response('{"error":"invalid_grant","error_description":"code expired 3s ago"}', {
      status: 400,
    })) as unknown as typeof fetch

  await assert.rejects(
    exchangeCode({
      zitadelDomain: 'https://id.example.com',
      clientId: 'client-1',
      redirectUri: 'https://admin.example.com/api/auth/callback',
      code: 'bad',
      codeVerifier: 'verifier',
      fetchImpl,
    }),
    (error: Error) => {
      // Whether the code was expired or simply unknown tells whoever is probing
      // which of their guesses was closer.
      assert.ok(!error.message.includes('expired'))
      assert.ok(!error.message.includes('invalid_grant'))
      return true
    },
  )
})

test('the verifier is sent on the exchange', async () => {
  let sent = ''
  const fetchImpl = (async (_url: string, init: RequestInit) => {
    sent = String(init.body)
    return new Response('{"id_token":"header.payload.signature"}', { status: 200 })
  }) as unknown as typeof fetch

  const tokens = await exchangeCode({
    zitadelDomain: 'https://id.example.com',
    clientId: 'client-1',
    redirectUri: 'https://admin.example.com/api/auth/callback',
    code: 'good',
    codeVerifier: 'the-verifier',
    fetchImpl,
  })

  assert.ok(sent.includes('code_verifier=the-verifier'))
  assert.equal(tokens.idToken, 'header.payload.signature')
})

/**
 * Settings that cannot produce an authorize URL.
 *
 * This is the failure that took the sign-in route down in every environment:
 * ZITADEL_DOMAIN held `auth-dev.example.com` where a base URL was meant, so
 * the authorize URL came out relative, NextResponse.redirect refused it, and
 * the browser got an unexplained 500. Seventeen settings were configured and
 * nothing said which one was wrong.
 */

test('a hostname without a scheme is refused, and says so', async () => {
  await assert.rejects(
    beginAuthorization({
      zitadelDomain: 'auth-dev.example.com',
      clientId: 'client-1',
      redirectUri: 'https://admin.example.com/api/auth/callback',
    }),
    (error: Error) => {
      assert.match(error.message, /ZITADEL_DOMAIN/)
      assert.match(error.message, /scheme/)
      return true
    },
  )
})

test('an empty setting is named rather than silently used', async () => {
  for (const [field, name] of [
    ['zitadelDomain', 'ZITADEL_DOMAIN'],
    ['clientId', 'ZITADEL_CLIENT_ID'],
    ['redirectUri', 'ZITADEL_ADMIN_REDIRECT_URI'],
  ] as const) {
    const options = {
      zitadelDomain: 'https://id.example.com',
      clientId: 'client-1',
      redirectUri: 'https://admin.example.com/api/auth/callback',
      [field]: '',
    }
    await assert.rejects(beginAuthorization(options), (error: Error) => {
      assert.match(error.message, new RegExp(name))
      return true
    })
  }
})

test('the message never carries the value', async () => {
  // A configuration error that prints configuration into a browser error page
  // is a worse bug than the one it is reporting.
  const secretish = 'https://tenant-abc123.zitadel.cloud'
  await assert.rejects(
    beginAuthorization({
      zitadelDomain: secretish,
      clientId: '',
      redirectUri: 'https://admin.example.com/api/auth/callback',
    }),
    (error: Error) => {
      assert.ok(!error.message.includes(secretish), 'the value appeared in the message')
      return true
    },
  )
})

test('a well-formed base URL still works', async () => {
  const start = await beginAuthorization({
    zitadelDomain: 'https://id.example.com/',
    clientId: 'client-1',
    redirectUri: 'https://admin.example.com/api/auth/callback',
  })
  assert.ok(start.url.startsWith('https://id.example.com/oauth/v2/authorize?'))
})

/**
 * The token exchange authenticates the application.
 *
 * ZITADEL registers these as confidential clients
 * (OIDC_AUTH_METHOD_TYPE_BASIC), so the token endpoint requires HTTP Basic
 * authentication. The exchange sent no secret, ZITADEL rejected every code,
 * and the sign-in failed on its last step behind a message that is
 * deliberately identical for every cause.
 */

function capturingFetch(status = 200) {
  const calls: Array<{ headers: Record<string, string>; body: string }> = []
  const impl = (async (_url: string, init: RequestInit) => {
    calls.push({
      headers: init.headers as Record<string, string>,
      body: String(init.body),
    })
    return {
      ok: status < 400,
      status,
      json: async () => ({ id_token: 'id', access_token: 'at', expires_in: 3600 }),
    }
  }) as unknown as typeof fetch
  return { impl, calls }
}

const EXCHANGE = {
  zitadelDomain: 'https://id.example.com',
  clientId: 'client-1',
  redirectUri: 'https://admin.example.com/api/auth/callback',
  code: 'the-code',
  codeVerifier: 'the-verifier',
}

test('a client secret is sent as HTTP Basic', async () => {
  const { impl, calls } = capturingFetch()
  await exchangeCode({ ...EXCHANGE, clientSecret: 's3cret', fetchImpl: impl })

  const header = calls[0].headers.Authorization
  assert.ok(header?.startsWith('Basic '), 'no Basic credential was sent')
  // RFC 6749 2.3.1: both halves form-urlencoded, then base64.
  const decoded = Buffer.from(header.slice('Basic '.length), 'base64').toString()
  assert.equal(decoded, 'client-1:s3cret')
})

test('the secret never travels in the form body', async () => {
  // The body is logged by proxies far more often than a header is.
  const { impl, calls } = capturingFetch()
  await exchangeCode({ ...EXCHANGE, clientSecret: 's3cret', fetchImpl: impl })
  assert.ok(!calls[0].body.includes('s3cret'), 'the secret appeared in the body')
})

test('a secret with reserved characters survives encoding', async () => {
  const { impl, calls } = capturingFetch()
  await exchangeCode({ ...EXCHANGE, clientSecret: 'a:b c/d', fetchImpl: impl })
  const decoded = Buffer.from(
    calls[0].headers.Authorization.slice('Basic '.length),
    'base64',
  ).toString()
  // A raw colon inside the secret would split the credential in the wrong place.
  assert.equal(decoded, 'client-1:a%3Ab%20c%2Fd')
})

test('no secret means no Authorization header', async () => {
  // A public client is still a valid configuration; sending an empty
  // credential would break it.
  const { impl, calls } = capturingFetch()
  await exchangeCode({ ...EXCHANGE, fetchImpl: impl })
  assert.equal(calls[0].headers.Authorization, undefined)
})

test('a rejected exchange carries the status for the log, not the caller', async () => {
  const { impl } = capturingFetch(401)
  await assert.rejects(
    exchangeCode({ ...EXCHANGE, clientSecret: 's3cret', fetchImpl: impl }),
    (error: Error & { status?: number }) => {
      assert.equal(error.status, 401)
      // What reaches the browser stays uninformative.
      assert.equal(error.message, 'The sign-in could not be completed.')
      return true
    },
  )
})
