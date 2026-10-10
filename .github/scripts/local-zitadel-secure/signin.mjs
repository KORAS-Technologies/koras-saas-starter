// T-I1 / T-I12 / T-I13: a sign-in from a clean browser through login v2.
//
//   node signin.mjs <expect: success|failure>
//
// Reads ISSUER, LOGIN_BASE, CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, LOGIN_NAME
// and PASSWORD from the environment. A fresh browser context starts an OIDC
// authorization-code flow against the product's own application, must land on
// the login container's own port, signs in, and -- on success -- exchanges the
// code at the token endpoint and checks the ID token names the admin with a
// role. The application itself is not running in this job; the callback is
// intercepted at the browser, which is exactly where the application would
// receive it. Nothing secret is printed.
import { chromium } from 'playwright'

const expectation = process.argv[2]
const env = (name) => {
  const value = process.env[name]
  if (!value) throw new Error(`${name} is not set`)
  return value
}
const issuer = env('ISSUER')
const loginBase = env('LOGIN_BASE')
const clientId = env('CLIENT_ID')
const clientSecret = env('CLIENT_SECRET')
const redirectUri = env('REDIRECT_URI')

const browser = await chromium.launch()
const context = await browser.newContext()
const page = await context.newPage()
let callback = null
await page.route(`${redirectUri}**`, async (route) => {
  callback = route.request().url()
  await route.fulfill({ status: 200, contentType: 'text/plain', body: 'callback intercepted' })
})

const authorize = new URL(`${issuer}/oauth/v2/authorize`)
authorize.search = new URLSearchParams({
  client_id: clientId,
  redirect_uri: redirectUri,
  response_type: 'code',
  scope: 'openid profile email urn:zitadel:iam:org:project:roles',
  state: 'phase-4-3a',
}).toString()

const fail = async (message) => {
  console.error(`FAIL: ${message}`)
  console.error(`  at ${page.url()}`)
  await page.screenshot({ path: `signin-${expectation}.png`, fullPage: true }).catch(() => {})
  await browser.close()
  process.exit(1)
}

try {
  await page.goto(authorize.toString(), { waitUntil: 'domcontentloaded' })
  await page.waitForURL((url) => url.href.startsWith(loginBase), { timeout: 30_000 })
} catch {
  await fail(`the authorization request did not reach the login at ${loginBase}`)
}

const username = page.locator('input[name="loginName"], input[autocomplete="username"], input[type="text"]').first()
await username.waitFor({ timeout: 30_000 }).catch(() => fail('no login-name field rendered (instance not resolved?)'))
await username.fill(env('LOGIN_NAME'))
await page.locator('button[type="submit"]').first().click()

const password = page.locator('input[type="password"]').first()
await password.waitFor({ timeout: 30_000 }).catch(() => fail('no password field after the login name'))
await password.fill(env('PASSWORD'))
await page.locator('button[type="submit"]').first().click()

// Login v2 may offer optional steps (a second factor, a passkey) before
// continuing. None is required by the default policy; skip any that appear.
const deadline = Date.now() + (expectation === 'success' ? 45_000 : 10_000)
while (!callback && Date.now() < deadline) {
  const skip = page.getByRole('button', { name: /skip|later|not now/i }).first()
  if (await skip.isVisible().catch(() => false)) await skip.click().catch(() => {})
  await page.waitForTimeout(500)
}

if (expectation === 'failure') {
  if (callback) await fail('signed in with a password that must be refused')
  console.log('ok: the password was refused and no authorization code was issued')
  await browser.close()
  process.exit(0)
}

if (!callback) await fail('no authorization code reached the callback')
const code = new URL(callback).searchParams.get('code')
if (!code) await fail('the callback carried no code')

const token = await fetch(`${issuer}/oauth/v2/token`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/x-www-form-urlencoded',
    Authorization: `Basic ${Buffer.from(`${encodeURIComponent(clientId)}:${encodeURIComponent(clientSecret)}`).toString('base64')}`,
  },
  body: new URLSearchParams({ grant_type: 'authorization_code', code, redirect_uri: redirectUri }),
})
const body = await token.json()
if (token.status !== 200 || !body.id_token) await fail(`the code exchange answered ${token.status}`)
const claims = JSON.parse(Buffer.from(body.id_token.split('.')[1], 'base64url').toString('utf8'))
if (claims.iss !== issuer) await fail(`the ID token's issuer is ${claims.iss}`)
const roles = Object.keys(claims['urn:zitadel:iam:org:project:roles'] ?? {})
if (roles.length === 0) await fail('the ID token carries no project role')
console.log(`ok: signed in through ${loginBase}; ID token for ${claims.preferred_username} with roles ${roles.join(', ')}`)
await browser.close()
