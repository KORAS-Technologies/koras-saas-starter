import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, writeFileSync, mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { generateKeyPairSync } from 'node:crypto'

import { runBillingProvision, mergePlan, sameRow } from '../src/billing/index.js'
import {
  addonLookupKey,
  idempotencyKey,
  priceLookupKey,
  EXTRA_USER_SEGMENT,
  LookupKeyError,
} from '../src/billing/keys.js'
import {
  parseBillingCatalogue,
  declaredButInert,
  BILLING_CATALOGUE_PATH,
} from '../src/billing/catalogue.js'
import { checkKeyEnvironment, resolveBillingConfig } from '../src/billing/config.js'
import { encodeForm } from '../src/billing/stripe.js'
import { redact } from '../src/redact.js'
import type { PlanRecord } from '../src/billing/plans.js'

/**
 * Catalogue provisioning, exercised rather than read.
 *
 * The repository has four recorded occasions on which a green suite sat over
 * work that had never run once, every one of them an assertion that asked what
 * a contract *said* instead of what the code *did*. This step writes to an
 * account holding real money, so the standard here is that every test drives
 * `runBillingProvision` against a fake estate and asserts the HTTP calls it
 * actually made — including, in the case that matters most, that it made none.
 */

const INSTANCE = 'https://auth-dev.example.com'
const CONTROL_PLANE = 'https://acme-api-dev.fly.dev'

const MINTED_JWT = 'eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJzZXJ2aWNlIn0.c2lnbmF0dXJl'

// Deliberately not named after the shell variable the walkthrough uses for a
// staff token. The identifier test keeps that name exempt as a tripwire -- it
// appearing anywhere in the code would mean somebody had started storing one --
// and a test fixture is a false positive on it. The tripwire is worth more than
// the name, so this one moved, including in this comment.
/** Stands in for the `id_token` of a signed-in console session. */
const CONSOLE_ID_TOKEN = 'eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJzdGFmZiJ9.c3RhZmY'

const { privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })

const SERVICE_ACCOUNT_KEY = JSON.stringify({
  type: 'serviceaccount',
  keyId: 'key-1',
  userId: 'user-1',
  key: privateKey.export({ type: 'pkcs1', format: 'pem' }).toString(),
})

interface Call {
  method: string
  url: string
  body?: string
  headers: Record<string, string>
}

interface StripePrice {
  id: string
  lookup_key: string | null
  unit_amount: number
  currency: string
  recurring: { interval: string }
  active: boolean
}

/**
 * A fake estate: an identity provider, a payment provider and a Control Plane.
 *
 * It keeps state, so running the provisioner twice against one instance is the
 * real question — does the second run find what the first created — rather
 * than a re-run against a blank slate, which would prove nothing.
 */
class Estate {
  readonly calls: Call[] = []
  products = new Map<string, { id: string; name: string; tax_code: string }>()
  prices: StripePrice[] = []
  plans: PlanRecord[] = []
  /** Recorded catalogue versions, keyed by plan and version. */
  catalogue = new Map<string, Record<string, unknown>>()
  private priceCounter = 0

  /** Overridable so a test can make one endpoint fail without faking the rest. */
  stripeStatusOverride: { path: string; status: number; body: string } | null = null

  /** What the platform's product listing answers. 200 unless a test says otherwise. */
  productsStatus = 200

  get writes(): Call[] {
    return this.calls.filter((call) => call.method === 'POST' || call.method === 'PUT')
  }

  /** Writes that change the estate, excluding the token exchange, which is a read. */
  get mutatingWrites(): Call[] {
    return this.writes.filter((call) => !call.url.includes('/oauth/v2/token'))
  }

  fetch = async (
    url: string,
    init?: { method?: string; headers?: Record<string, string>; body?: string },
  ) => {
    const method = init?.method ?? 'GET'
    this.calls.push({ method, url, body: init?.body, headers: init?.headers ?? {} })

    const respond = (status: number, body: unknown) => ({
      ok: status >= 200 && status < 300,
      status,
      text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
    })

    if (url.startsWith(`${INSTANCE}/oauth/v2/token`)) {
      // JWT-shaped on purpose: the mint refuses an opaque token, because the
      // Control Plane cannot verify one. A fake that returned an opaque string
      // would fail every test here for a reason unrelated to what they check.
      return respond(200, { access_token: MINTED_JWT, expires_in: 43_199 })
    }

    if (this.stripeStatusOverride && url.includes(this.stripeStatusOverride.path)) {
      return respond(this.stripeStatusOverride.status, this.stripeStatusOverride.body)
    }

    // ── payment provider ────────────────────────────────────────────────────

    const productGet = /api\.stripe\.com\/v1\/products\/([^?]+)$/.exec(url)
    if (productGet && method === 'GET') {
      const id = decodeURIComponent(productGet[1])
      const found = this.products.get(id)
      return found
        ? respond(200, found)
        : respond(404, { error: { message: 'No such product', code: 'resource_missing' } })
    }

    if (url.endsWith('/v1/products') && method === 'POST') {
      const form = new URLSearchParams(init?.body ?? '')
      const id = form.get('id') ?? `prod_${this.products.size}`
      const record = {
        id,
        name: form.get('name') ?? '',
        tax_code: form.get('tax_code') ?? '',
      }
      this.products.set(id, record)
      return respond(200, record)
    }

    if (url.includes('/v1/prices?') && method === 'GET') {
      const query = new URLSearchParams(url.split('?')[1])
      const wanted = query.get('lookup_keys[0]')
      const matches = this.prices.filter((price) => price.active && price.lookup_key === wanted)
      return respond(200, { data: matches })
    }

    if (url.endsWith('/v1/prices') && method === 'POST') {
      const form = new URLSearchParams(init?.body ?? '')
      const lookupKey = form.get('lookup_key')

      if (form.get('transfer_lookup_key') === 'true') {
        // The provider's own behaviour: the key moves, and the old price stays
        // exactly as it was apart from losing the key.
        for (const price of this.prices) {
          if (price.lookup_key === lookupKey) price.lookup_key = null
        }
      } else if (this.prices.some((p) => p.active && p.lookup_key === lookupKey)) {
        return respond(400, { error: { message: 'lookup_key already in use' } })
      }

      const created: StripePrice = {
        id: `price_${++this.priceCounter}`,
        lookup_key: lookupKey,
        unit_amount: Number(form.get('unit_amount')),
        currency: form.get('currency') ?? 'usd',
        recurring: { interval: form.get('recurring[interval]') ?? 'month' },
        active: true,
      }
      this.prices.push(created)
      return respond(200, created)
    }

    // ── Control Plane ───────────────────────────────────────────────────────

    if (url.endsWith('/api/platform/v1/products') && method === 'GET') {
      if (this.productsStatus !== 200) return respond(this.productsStatus, { detail: 'Forbidden' })
      return respond(200, [{ id: 'prod-uuid-1', code: 'acme', name: 'Acme' }])
    }

    if (url.includes('/api/platform/v1/plans') && method === 'GET') {
      return respond(200, this.plans)
    }

    const catalogueGet = /\/products\/([^/]+)\/plans\/([^/]+)\/catalogue$/.exec(url)
    if (catalogueGet && method === 'GET') {
      const planCode = decodeURIComponent(catalogueGet[2])
      const found = [...this.catalogue.entries()].find(([key]) => key.startsWith(`${planCode}@`))
      // 404 is the documented answer for terms never recorded, and is not a
      // failure: unrecorded is not the same as free.
      return found ? respond(200, found[1]) : respond(404, { detail: 'not recorded' })
    }

    if (url.endsWith('/api/platform/v1/plan-catalogue') && method === 'PUT') {
      const body = JSON.parse(init?.body ?? '{}') as Record<string, unknown>
      const key = `${String(body.plan_code)}@${String(body.plan_version)}`
      this.catalogue.set(key, body)
      return respond(200, { id: 'cat-1', plan_version: String(body.plan_version) })
    }

    if (url.endsWith('/api/platform/v1/plans') && method === 'PUT') {
      const body = JSON.parse(init?.body ?? '{}') as PlanRecord & { product_code: string }
      const index = this.plans.findIndex((plan) => plan.code === body.code)
      const { product_code: _ignored, ...row } = body
      if (index === -1) this.plans.push(row as PlanRecord)
      else this.plans[index] = row as PlanRecord
      return respond(200, { id: 'plan-id', code: body.code })
    }

    return respond(404, { error: { message: `unrouted: ${method} ${url}` } })
  }
}

function environmentFor(providerKey = 'sk_test_abcdef123456'): NodeJS.ProcessEnv {
  return {
    KORAS_CONTROL_PLANE_URL: CONTROL_PLANE,
    KORAS_CONTROL_PLANE_PROJECT_ID: 'project-1',
    // A staff bearer, which is the only credential the Control Plane accepts
    // for this: a platform role needs a second factor and a machine identity
    // has none, so a service account is refused at verification.
    KORAS_CONTROL_PLANE_BILLING_TOKEN: CONSOLE_ID_TOKEN,
    KORAS_BILLING_PROVIDER_KEY: providerKey,
    ZITADEL_DEV_DOMAIN: INSTANCE,
  }
}

function plan(code: string, overrides: Partial<PlanRecord> = {}): PlanRecord {
  return {
    code,
    name: code[0].toUpperCase() + code.slice(1),
    self_serve: true,
    price_id_month: null,
    price_id_year: null,
    expected_amount_month: null,
    expected_amount_year: null,
    expected_currency: null,
    min_seats: 1,
    max_seats: null,
    included_users: null,
    product_name: 'Acme',
    ...overrides,
  }
}

let projectRoot: string

function writeCatalogue(body: string): void {
  mkdirSync(join(projectRoot, '.koras'), { recursive: true })
  writeFileSync(join(projectRoot, BILLING_CATALOGUE_PATH), body, 'utf8')
}

const TWO_PLANS = `
version: 1
currency: usd
tax_code: txcd_10103001
plans:
  starter:
    name: Starter
    monthly_price_cents: 900
    annual_price_cents: 9000
    included_users: 3
  pro:
    name: Professional
    monthly_price_cents: 2900
    annual_price_cents: null
    included_users: 10
`

beforeEach(() => {
  projectRoot = mkdtempSync(join(tmpdir(), 'koras-billing-'))
})

async function run(estate: Estate, env = environmentFor()) {
  return runBillingProvision({
    projectRoot,
    productCode: 'acme',
    registersAsProduct: true,
    dryRun: false,
    env,
    fetchImpl: estate.fetch,
  })
}

describe('the commercial catalogue, provisioned', () => {
  it('creates a price per declared interval and writes the references onto the plans', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter'), plan('pro'), plan('business', { self_serve: false })]
    writeCatalogue(TWO_PLANS)

    const report = await run(estate)

    expect(report.kind).toBe('provisioned')
    if (report.kind !== 'provisioned') return

    // Three prices, not four: `pro.yearly` is null, which is a statement that
    // the plan is not sold yearly rather than an omission.
    expect(estate.prices).toHaveLength(3)
    expect(estate.prices.map((price) => price.lookup_key).sort()).toEqual([
      'acme_pro_monthly_usd',
      'acme_starter_monthly_usd',
      'acme_starter_yearly_usd',
    ])

    const starter = estate.plans.find((p) => p.code === 'starter')!
    expect(starter.price_id_month).toMatch(/^price_/)
    expect(starter.price_id_year).toMatch(/^price_/)
    // The intent is written alongside the reference. Without it the platform's
    // reconciliation check reads the plan as unchecked rather than clean.
    expect(starter.expected_amount_month).toBe(900)
    expect(starter.expected_amount_year).toBe(9000)
    expect(starter.expected_currency).toBe('usd')

    const pro = estate.plans.find((p) => p.code === 'pro')!
    expect(pro.price_id_month).toMatch(/^price_/)
    expect(pro.price_id_year).toBeNull()
    expect(pro.expected_amount_year).toBeNull()

    // A plan the catalogue never mentions is not touched at all.
    const business = estate.plans.find((p) => p.code === 'business')!
    expect(business).toEqual(plan('business', { self_serve: false }))
  })

  it('a second run against the same estate creates nothing and writes nothing', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter'), plan('pro')]
    writeCatalogue(TWO_PLANS)

    await run(estate)
    const pricesAfterFirst = estate.prices.length
    const planRowsAfterFirst = JSON.stringify(estate.plans)

    estate.calls.length = 0
    const second = await run(estate)

    expect(second.kind).toBe('provisioned')
    if (second.kind !== 'provisioned') return

    // The property the whole design exists for. An operator who cannot tell
    // whether the first run finished will run it again, so a second run has to
    // be free -- and "free" means zero writes, not "writes that happen to be
    // harmless".
    expect(second.noop).toBe(true)
    expect(estate.mutatingWrites).toEqual([])
    expect(estate.prices).toHaveLength(pricesAfterFirst)
    expect(JSON.stringify(estate.plans)).toBe(planRowsAfterFirst)
    expect(second.plans.every((p) => p.unchanged)).toBe(true)
    expect(second.plans.flatMap((p) => [p.month?.kind, p.year?.kind]).filter(Boolean)).toEqual(
      Array(3).fill('reused'),
    )
  })

  it('never resets a plan field it does not own', async () => {
    const estate = new Estate()
    // A plan somebody has administered: renamed, taken off self-serve sale and
    // given seat bounds. `PUT /plans` overwrites the whole row, so a caller
    // that sent only price fields would silently undo all three.
    estate.plans = [
      plan('starter', {
        name: 'Starter (legacy pricing)',
        self_serve: false,
        min_seats: 3,
        max_seats: 25,
      }),
    ]
    writeCatalogue(`
version: 1
currency: usd
plans:
  starter:
    monthly_price_cents: 900
`)

    await run(estate)

    const written = estate.plans.find((p) => p.code === 'starter')!
    expect(written.name).toBe('Starter (legacy pricing)')
    expect(written.self_serve).toBe(false)
    expect(written.min_seats).toBe(3)
    expect(written.max_seats).toBe(25)
    expect(written.price_id_month).toMatch(/^price_/)
  })

  it('supersedes a changed amount with a new price and leaves the old one alone', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter')]
    writeCatalogue(`
version: 1
currency: usd
plans:
  starter:
    monthly_price_cents: 900
`)
    await run(estate)

    const original = estate.prices[0]
    estate.calls.length = 0

    writeCatalogue(`
version: 1
currency: usd
plans:
  starter:
    monthly_price_cents: 1900
`)
    const report = await run(estate)

    expect(report.kind).toBe('provisioned')
    if (report.kind !== 'provisioned') return

    const outcome = report.plans[0].month
    expect(outcome?.kind).toBe('superseded')

    // A provider price is immutable in amount, so the correction is a second
    // price. The first must still be there: nothing in this path may delete or
    // archive, because deletion is the one mistake no retry undoes.
    expect(estate.prices).toHaveLength(2)
    const kept = estate.prices.find((price) => price.id === original.id)!
    expect(kept.active).toBe(true)
    expect(kept.unit_amount).toBe(900)
    // It lost the lookup key to the replacement, so nothing addresses it.
    expect(kept.lookup_key).toBeNull()

    // And no call anywhere tried to delete or deactivate it.
    expect(estate.calls.some((call) => call.method === 'DELETE')).toBe(false)
    expect(estate.calls.some((call) => (call.body ?? '').includes('active=false'))).toBe(false)

    expect(estate.plans[0].price_id_month).not.toBe(original.id)
    expect(estate.plans[0].expected_amount_month).toBe(1900)
  })

  it('refuses a plan code the Control Plane does not hold, and creates nothing', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter'), plan('pro')]
    writeCatalogue(`
version: 1
currency: usd
plans:
  startr:
    monthly_price_cents: 900
  professional:
    monthly_price_cents: 2900
`)

    const report = await run(estate)

    expect(report.kind).toBe('failed')
    if (report.kind !== 'failed') return
    expect(report.retryable).toBe(false)
    // Both, in one run. Finding the second typo only after correcting the first
    // is three runs against a real payment account.
    expect(report.detail).toContain('startr')
    expect(report.detail).toContain('professional')

    // The endpoint would happily create a plan. Nothing was created anywhere.
    expect(estate.mutatingWrites).toEqual([])
    expect(estate.prices).toEqual([])
    expect(estate.plans.map((p) => p.code)).toEqual(['starter', 'pro'])
  })

  it('names the role when the Control Plane answers 403', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter')]
    writeCatalogue(TWO_PLANS)
    estate.stripeStatusOverride = {
      path: '/api/platform/v1/plans',
      status: 403,
      body: '{"detail":"Forbidden"}',
    }

    const report = await run(estate)

    expect(report.kind).toBe('failed')
    if (report.kind !== 'failed') return
    // The single likeliest failure on a first run, and the one whose obvious
    // fix -- granting the registrar a role -- breaks registration instead.
    expect(report.detail).toContain('platform billing role')
  })
})

describe('the environment guard', () => {
  it('refuses a live provider key against anything but production', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter')]
    writeCatalogue(TWO_PLANS)

    const report = await run(estate, environmentFor('sk_live_realmoney1234'))

    expect(report.kind).toBe('failed')
    if (report.kind !== 'failed') return
    expect(report.detail).toContain('live key')
    // Refused before any call is made, not after the first one succeeds.
    expect(estate.calls).toEqual([])
  })

  it('refuses a restricted live key too', () => {
    expect(checkKeyEnvironment('rk_live_scoped', 'dev').ok).toBe(false)
  })

  it('refuses a test key against production', () => {
    const outcome = checkKeyEnvironment('sk_test_abc', 'prod')
    expect(outcome.ok).toBe(false)
    if (outcome.ok) return
    expect(outcome.detail).toContain('cannot take a payment')
  })

  it('allows the pairs that match', () => {
    expect(checkKeyEnvironment('sk_test_abc', 'dev').ok).toBe(true)
    expect(checkKeyEnvironment('sk_test_abc', 'stg').ok).toBe(true)
    expect(checkKeyEnvironment('sk_live_abc', 'prod').ok).toBe(true)
  })

  it('refuses a key whose mode it cannot read', () => {
    // A key it cannot classify is a key it cannot check, and this is the one
    // thing standing between a rehearsal and the real account.
    expect(checkKeyEnvironment('some-other-token', 'dev').ok).toBe(false)
    expect(checkKeyEnvironment('some-other-token', 'prod').ok).toBe(false)
  })

  it('will not guess the environment from a Control Plane URL that does not encode one', () => {
    const env = { ...environmentFor(), KORAS_CONTROL_PLANE_URL: 'https://control.example.com' }
    const resolution = resolveBillingConfig({ env })
    expect(resolution.ok).toBe(false)
    if (resolution.ok) return
    expect(resolution.problem.detail).toContain('Cannot tell which environment')
  })

  it('names the staff token when no credential is set, and says why it is a person', () => {
    const env = { ...environmentFor() }
    delete env.KORAS_CONTROL_PLANE_BILLING_TOKEN
    const resolution = resolveBillingConfig({ env })
    expect(resolution.ok).toBe(false)
    if (resolution.ok) return
    expect(resolution.problem.kind).toBe('no-billing-key')
    expect(resolution.problem.detail).toContain('id_token')
  })

  it('refuses a service-account key with the reason, rather than letting it 401', () => {
    // A machine granted the billing role is refused at verification, and the
    // refusal reads exactly like an expired token or a wrong audience.
    // Somebody would spend an afternoon on that, so it is named here instead.
    const env = { ...environmentFor() }
    delete env.KORAS_CONTROL_PLANE_BILLING_TOKEN
    env.KORAS_CONTROL_PLANE_BILLING_KEY_JSON = SERVICE_ACCOUNT_KEY
    const resolution = resolveBillingConfig({ env })
    expect(resolution.ok).toBe(false)
    if (resolution.ok) return
    expect(resolution.problem.detail).toContain('second factor')
  })

  it('prefers the staff token when both are set', () => {
    const env = { ...environmentFor() }
    env.KORAS_CONTROL_PLANE_BILLING_KEY_JSON = SERVICE_ACCOUNT_KEY
    const resolution = resolveBillingConfig({ env })
    expect(resolution.ok).toBe(true)
    if (!resolution.ok) return
    expect(resolution.config.credential.kind).toBe('token')
  })

  it('reports the environment mismatch before a missing service-account key', () => {
    // Ordering matters: the lesser problem reported first sends an operator to
    // fix it and meet the real refusal on the next run.
    const env = { ...environmentFor('sk_live_x1234567') }
    delete env.KORAS_CONTROL_PLANE_BILLING_TOKEN
    const resolution = resolveBillingConfig({ env })
    expect(resolution.ok).toBe(false)
    if (resolution.ok) return
    expect(resolution.problem.kind).toBe('environment-mismatch')
  })
})

describe('lookup and idempotency keys', () => {
  it('mints the exact shape the Control Plane contract specifies', () => {
    // Pinned as literal strings rather than recomputed. The platform owns this
    // contract and implements it in Python; this is a second implementation of
    // one rule, so a test that reproduced the rule would drift in the same
    // direction as the code and agree with itself forever.
    expect(
      priceLookupKey({ productCode: 'acme', planCode: 'pro', interval: 'month', currency: 'usd' }),
    ).toBe('acme_pro_monthly_usd')
    expect(
      priceLookupKey({ productCode: 'acme', planCode: 'starter', interval: 'year', currency: 'usd' }),
    ).toBe('acme_starter_yearly_usd')
    // A hyphenated product keeps its own name, and the four parts stay
    // unambiguous to anything that splits on an underscore.
    expect(
      priceLookupKey({
        productCode: 'koras-e2e-shop',
        planCode: 'business',
        interval: 'month',
        currency: 'usd',
      }),
    ).toBe('koras-e2e-shop_business_monthly_usd')
  })

  it('gives the add-on the same four parts with the plan segment replaced', () => {
    expect(
      addonLookupKey({
        productCode: 'acme',
        addonCode: EXTRA_USER_SEGMENT,
        interval: 'month',
        currency: 'usd',
      }),
    ).toBe('acme_extra-user_monthly_usd')
  })

  it('refuses a segment carrying the separator', () => {
    // An underscore inside a segment makes the key ambiguous to everything
    // that reads it by splitting, including a person. This is why the add-on
    // is one hyphenated word rather than two underscored ones.
    expect(() =>
      priceLookupKey({
        productCode: 'acme',
        planCode: 'extra_user',
        interval: 'month',
        currency: 'usd',
      }),
    ).toThrow(LookupKeyError)
  })

  it("gives one plan's two intervals different keys", () => {
    const month = priceLookupKey({
      productCode: 'acme',
      planCode: 'pro',
      interval: 'month',
      currency: 'usd',
    })
    const year = priceLookupKey({
      productCode: 'acme',
      planCode: 'pro',
      interval: 'year',
      currency: 'usd',
    })
    expect(month).not.toBe(year)
  })

  it('makes the same plan at a different amount a different idempotency key', () => {
    // If the amount were not part of the subject, a corrected price would
    // replay the first attempt: the provider would hand back the old price and
    // the run would report success.
    const first = idempotencyKey('price.create', 'acme.pro.month.usd', 900, 'usd', 'month')
    const second = idempotencyKey('price.create', 'acme.pro.month.usd', 1900, 'usd', 'month')
    expect(first).not.toBe(second)
  })

  it('is stable for the same operation on the same subject', () => {
    expect(idempotencyKey('price.create', 'acme.pro.month.usd', 900)).toBe(
      idempotencyKey('price.create', 'acme.pro.month.usd', 900),
    )
  })

  it('sends an idempotency key on writes and never on reads', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter')]
    writeCatalogue(`
version: 1
currency: usd
plans:
  starter:
    monthly_price_cents: 900
`)
    await run(estate)

    const priceWrite = estate.calls.find(
      (call) => call.method === 'POST' && call.url.endsWith('/v1/prices'),
    )!
    expect(priceWrite.headers['idempotency-key']).toBeTruthy()

    const priceRead = estate.calls.find(
      (call) => call.method === 'GET' && call.url.includes('/v1/prices?'),
    )!
    // A key on a read would have the provider cache a lookup this code relies
    // on being fresh.
    expect(priceRead.headers['idempotency-key']).toBeUndefined()
  })
})

describe('the provider request body', () => {
  it('encodes a recurring interval the way the provider reads it', () => {
    // An unrecognised field is ignored rather than refused, so a mis-encoded
    // `recurring` produces a one-off price where a subscription was meant --
    // and nothing says so until a customer is charged exactly once.
    expect(encodeForm({ recurring: { interval: 'month' } })).toBe('recurring%5Binterval%5D=month')
  })

  it('omits a field that is undefined rather than sending the word', () => {
    expect(encodeForm({ a: 1, b: undefined, c: null })).toBe('a=1')
  })

  it('sends the tax code when it creates a product', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter')]
    writeCatalogue(`
version: 1
currency: usd
tax_code: txcd_10103001
plans:
  starter:
    monthly_price_cents: 900
`)
    await run(estate)

    // A product without an eligible tax code cannot be sold through Managed
    // Payments at all, and setting it by hand afterwards is the step this
    // whole command exists to remove.
    const created = [...estate.products.values()][0]
    expect(created.tax_code).toBe('txcd_10103001')
  })

  it('addresses the product by a deterministic id rather than searching for one', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter')]
    writeCatalogue(`
version: 1
currency: usd
plans:
  starter:
    monthly_price_cents: 900
`)
    await run(estate)

    // The provider's search index is eventually consistent, so a provisioner
    // that searched would duplicate on a quick re-run.
    expect(estate.calls.some((call) => call.url.includes('/v1/products/search'))).toBe(false)
    expect([...estate.products.keys()]).toEqual(['koras_acme_starter'])
  })
})

describe('the catalogue file', () => {
  it('refuses a generated catalogue that has not been filled in', () => {
    const outcome = parseBillingCatalogue({ version: 1, currency: 'usd', plans: {} }, 'x.yaml')
    expect(outcome.ok).toBe(false)
    if (outcome.ok) return
    expect(outcome.problem.detail).toContain('declares no plans')
  })

  it('tells an unfilled catalogue apart from one that says nothing is sold', () => {
    const outcome = parseBillingCatalogue(
      { version: 1, currency: 'usd', plans: { free: { monthly_price_cents: null } } },
      'x.yaml',
    )
    expect(outcome.ok).toBe(false)
    if (outcome.ok) return
    expect(outcome.problem.detail).toContain('free')
    expect(outcome.problem.detail).not.toContain('declares no plans')
  })

  it('refuses a fractional amount', () => {
    const outcome = parseBillingCatalogue(
      { version: 1, currency: 'usd', plans: { pro: { monthly_price_cents: 9.99 } } },
      'x.yaml',
    )
    expect(outcome.ok).toBe(false)
    if (outcome.ok) return
    expect(outcome.problem.detail).toContain('minor units')
  })

  it('refuses zero, which is what an unset variable interpolates to', () => {
    const outcome = parseBillingCatalogue(
      { version: 1, currency: 'usd', plans: { pro: { monthly_price_cents: 0 } } },
      'x.yaml',
    )
    expect(outcome.ok).toBe(false)
  })

  it('refuses an unknown key rather than ignoring it', () => {
    // A `month:` where `monthly:` was meant would otherwise be dropped
    // silently, and the plan would be provisioned with no price at all.
    const outcome = parseBillingCatalogue(
      { version: 1, currency: 'usd', plans: { pro: { monthly_price: 900 } } },
      'x.yaml',
    )
    expect(outcome.ok).toBe(false)
  })

  it('refuses a currency that is not ISO 4217', () => {
    expect(
      parseBillingCatalogue(
        { version: 1, currency: 'dollars', plans: { pro: { monthly_price_cents: 900 } } },
        'x.yaml',
      ).ok,
    ).toBe(false)
  })

  it('sorts plans so two runs of one catalogue read identically', () => {
    const outcome = parseBillingCatalogue(
      {
        version: 1,
        currency: 'usd',
        plans: {
          pro: { monthly_price_cents: 2900 },
          business: { monthly_price_cents: 9900 },
          starter: { monthly_price_cents: 900 },
        },
      },
      'x.yaml',
    )
    expect(outcome.ok).toBe(true)
    if (!outcome.ok) return
    expect(outcome.catalogue.plans.map((p) => p.code)).toEqual(['business', 'pro', 'starter'])
  })
})

describe('merging a plan row', () => {
  it('changes only the five fields this step owns', () => {
    const existing = plan('pro', { name: 'Pro', self_serve: false, min_seats: 2, max_seats: 9 })
    const merged = mergePlan(existing, {
      currency: 'usd',
      month: { kind: 'created', priceId: 'price_9', amount: 2900 },
    })

    const { price_id_month, expected_amount_month, expected_currency, ...restMerged } = merged
    const {
      price_id_month: _a,
      expected_amount_month: _b,
      expected_currency: _c,
      ...restExisting
    } = existing

    expect(restMerged).toEqual(restExisting)
    expect(price_id_month).toBe('price_9')
    expect(expected_amount_month).toBe(2900)
    expect(expected_currency).toBe('usd')
  })

  it('reports a row as unchanged only when every owned field already matches', () => {
    const existing = plan('pro', {
      price_id_month: 'price_9',
      expected_amount_month: 2900,
      expected_currency: 'usd',
    })
    const same = mergePlan(existing, {
      currency: 'usd',
      month: { kind: 'reused', priceId: 'price_9', amount: 2900 },
    })
    expect(sameRow(existing, same)).toBe(true)

    const different = mergePlan(existing, {
      currency: 'usd',
      month: { kind: 'created', priceId: 'price_10', amount: 2900 },
    })
    expect(sameRow(existing, different)).toBe(false)
  })
})

describe('secrets', () => {
  it('redacts a provider key quoted back in an error body', () => {
    // The pattern layer, not the value layer: this has to hold even when the
    // caller passes an environment that does not contain the key.
    const body = '{"error":{"message":"Invalid API Key provided: sk_test_abcdef1234567890"}}'
    expect(redact(body, {})).not.toContain('sk_test_abcdef1234567890')
  })

  it('redacts a live key and a webhook secret the same way', () => {
    expect(redact('key sk_live_51ABCdefGHI', {})).not.toContain('sk_live_51ABCdefGHI')
    expect(redact('whsec_1234567890abcdef', {})).not.toContain('whsec_1234567890abcdef')
  })

  it('never puts the provider key in a report', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter'), plan('pro')]
    writeCatalogue(TWO_PLANS)
    estate.stripeStatusOverride = {
      path: '/v1/prices',
      status: 401,
      body: '{"error":{"message":"Invalid API Key provided: sk_test_abcdef123456"}}',
    }

    const report = await run(estate)

    expect(report.kind).toBe('failed')
    if (report.kind !== 'failed') return
    expect(report.detail).not.toContain('sk_test_abcdef123456')
    expect(report.detail).toContain('401')
  })
})

describe('what it refuses to do at all', () => {
  it('provisions nothing for a profile that does not register as a product', async () => {
    const estate = new Estate()
    writeCatalogue(TWO_PLANS)

    const report = await runBillingProvision({
      projectRoot,
      productCode: 'koras-control-plane',
      registersAsProduct: false,
      dryRun: false,
      env: environmentFor(),
      fetchImpl: estate.fetch,
    })

    expect(report.kind).toBe('skipped')
    expect(estate.calls).toEqual([])
  })

  it('skips rather than fails when no Control Plane is configured', async () => {
    const estate = new Estate()
    writeCatalogue(TWO_PLANS)
    const env = { ...environmentFor() }
    delete env.KORAS_CONTROL_PLANE_URL

    const report = await runBillingProvision({
      projectRoot,
      productCode: 'acme',
      registersAsProduct: true,
      dryRun: false,
      env,
      fetchImpl: estate.fetch,
    })

    // R-001: a product may be provisioned before any Control Plane is live.
    // Failing here would make the documented bootstrap order impossible.
    expect(report.kind).toBe('skipped')
    if (report.kind !== 'skipped') return
    expect(report.reason).toBe('not-configured')
  })

  it('skips when the project has no catalogue file', async () => {
    const estate = new Estate()
    const report = await run(estate)
    expect(report.kind).toBe('skipped')
    if (report.kind !== 'skipped') return
    expect(report.reason).toBe('no-catalogue')
    expect(estate.calls).toEqual([])
  })

  it('sends nothing on a dry run, and still applies the environment guard', async () => {
    const estate = new Estate()
    writeCatalogue(TWO_PLANS)

    const planned = await runBillingProvision({
      projectRoot,
      productCode: 'acme',
      registersAsProduct: true,
      dryRun: true,
      env: environmentFor(),
      fetchImpl: estate.fetch,
    })
    expect(planned.kind).toBe('planned')
    expect(estate.calls).toEqual([])

    // A rehearsal that reported a plan it would refuse to carry out is the one
    // thing a rehearsal must not do.
    const refused = await runBillingProvision({
      projectRoot,
      productCode: 'acme',
      registersAsProduct: true,
      dryRun: true,
      env: environmentFor('sk_live_realmoney1234'),
      fetchImpl: estate.fetch,
    })
    expect(refused.kind).toBe('failed')
  })
})

afterEach(() => {
  rmSync(projectRoot, { recursive: true, force: true })
})

describe('the catalogue file the generator writes', () => {
  it('is emitted for a product and not for the Control Plane', async () => {
    const { renderTemplate } = await import('../src/generation/engine.js')
    const { buildContext } = await import('../src/generation/context.js')
    const { loadProfile } = await import('../src/profiles/index.js')
    const { resolveSelections } = await import('../src/profiles/index.js')

    const render = (profile: 'product' | 'control-plane') => {
      const { manifest, defaults } = loadProfile(profile)
      return renderTemplate(
        buildContext({
          projectName: 'Acme',
          projectSlug: 'acme',
          profile,
          manifest,
          defaults,
          selections: resolveSelections(manifest, defaults),
          outputDir: '.',
          dryRun: true,
          provision: false,
        }),
      ).map((file) => file.outputPath)
    }

    expect(render('product')).toContain(BILLING_CATALOGUE_PATH)
    // The Control Plane is the authority over other products' catalogues, not
    // a product with one of its own. A file here inviting somebody to price
    // the platform would look entirely normal until they did.
    expect(render('control-plane')).not.toContain(BILLING_CATALOGUE_PATH)
  })

  it('ships the platform standard, and it is usable exactly as generated', async () => {
    const yamlModule = await import('js-yaml')
    const { renderBillingCatalogue } = await import('../src/generation/billing-catalogue.js')
    const { buildContext } = await import('../src/generation/context.js')
    const { loadProfile, resolveSelections } = await import('../src/profiles/index.js')

    const { manifest, defaults } = loadProfile('product')
    const rendered = renderBillingCatalogue(
      buildContext({
        projectName: 'Acme',
        projectSlug: 'acme',
        profile: 'product',
        manifest,
        defaults,
        selections: resolveSelections(manifest, defaults),
        outputDir: '.',
        dryRun: true,
        provision: false,
      }),
    )

    // It has to parse -- a generated file that is not valid YAML would fail at
    // the least helpful moment -- and it has to be *accepted*, which is the
    // reversal: the first version shipped empty and was refused on purpose.
    const document = yamlModule.default.load(rendered)
    const outcome = parseBillingCatalogue(document, 'generated')
    expect(outcome.ok).toBe(true)
    if (!outcome.ok) return

    // The standard, in minor units. Asserted as numbers rather than by reading
    // the text, because the failure worth catching is a factor of a hundred and
    // a substring match would pass on either.
    const byCode = new Map(outcome.catalogue.plans.map((plan) => [plan.code, plan]))
    expect(byCode.get('starter')).toMatchObject({
      monthly: 9_900,
      yearly: 99_000,
      includedUsers: 3,
    })
    expect(byCode.get('pro')).toMatchObject({
      name: 'Professional',
      monthly: 19_900,
      yearly: 199_000,
      includedUsers: 10,
    })
    expect(byCode.get('business')).toMatchObject({
      monthly: 49_900,
      yearly: 499_000,
      includedUsers: 25,
    })

    // The Professional tier's *code* is `pro`. This is the one place that
    // decision is visible, and a later reader who has seen the standard and not
    // the decision is exactly who would "correct" it.
    expect(byCode.has('professional')).toBe(false)

    // Enterprise is on the catalogue with no price: an amount invented here
    // would be a number a salesperson has to contradict.
    expect(outcome.catalogue.custom.map((plan) => plan.code)).toEqual(['enterprise'])

    expect(outcome.catalogue.additionalUser).toEqual({ monthly: 2_500, yearly: 25_000 })

    // And it carries no credential, by the same rule that keeps one out of
    // every other file the generator writes.
    expect(rendered).not.toMatch(/sk_(live|test)_/)
  })

  it('states, in the generated file, which declared fields nothing acts on', async () => {
    const yamlModule = await import('js-yaml')
    const { renderBillingCatalogue } = await import('../src/generation/billing-catalogue.js')
    const { declaredButInert } = await import('../src/billing/catalogue.js')
    const { buildContext } = await import('../src/generation/context.js')
    const { loadProfile, resolveSelections } = await import('../src/profiles/index.js')

    const { manifest, defaults } = loadProfile('product')
    const rendered = renderBillingCatalogue(
      buildContext({
        projectName: 'Acme',
        projectSlug: 'acme',
        profile: 'product',
        manifest,
        defaults,
        selections: resolveSelections(manifest, defaults),
        outputDir: '.',
        dryRun: true,
        provision: false,
      }),
    )
    const outcome = parseBillingCatalogue(yamlModule.default.load(rendered), 'generated')
    expect(outcome.ok).toBe(true)
    if (!outcome.ok) return

    // The generated standard declares included users, limits and an extra-seat
    // price, none of which anything acts on yet. This repository has twice
    // shipped a declaration that looked live and was inert; what makes this
    // acceptable rather than a third time is that every run says so.
    const inert = declaredButInert(outcome.catalogue).join(' / ')
    expect(inert).toContain('limits')
    expect(inert).toContain('additional_user')

    // `included_users` must NOT be listed. It was, until the flat-fee
    // correction and the catalogue sync shipped; it is written onto the plan
    // and enforced now. A stale entry here is the same defect as a missing
    // one arriving from the other side -- it tells somebody a control does
    // nothing when it does.
    expect(inert).not.toContain('included_users')
  })
})

describe('the schema Phase 1 introduced', () => {
  const base = { version: 1 as const, currency: 'usd' }

  it('refuses an amount key that is not in minor units by name', () => {
    // `monthly_price: 99` is the factor-of-a-hundred error arriving as a
    // misspelling. Accepting it would price the plan at 99 cents; ignoring it
    // would price the plan at nothing. Refusing is the only safe answer.
    //
    // **The valid plan beside it is the whole test.** Alone, a misspelt plan
    // is refused whether or not the schema is strict -- it ends up with no
    // price, and a catalogue with no priced plan is refused for that reason
    // instead. So the version without `starter` here passed with strictness
    // removed, which is an assertion asking what the schema says rather than
    // what it does. With a priced plan present, only strictness can refuse.
    const outcome = parseBillingCatalogue(
      {
        ...base,
        plans: {
          starter: { monthly_price_cents: 9900 },
          pro: { monthly_price: 99 },
        },
      },
      'x.yaml',
    )
    expect(outcome.ok).toBe(false)
    if (outcome.ok) return
    expect(outcome.problem.detail).toContain('pro')
    // The refusal must name the key, not the catalogue being empty.
    expect(outcome.problem.detail).not.toContain('names no priced plan')
  })

  it('refuses an unknown key on a plan that is otherwise valid', () => {
    // The same protection, for a key that is not an amount at all. A plan
    // carrying `included_seats` where `included_users` was meant would
    // otherwise be provisioned correctly and include nothing.
    const outcome = parseBillingCatalogue(
      {
        ...base,
        plans: {
          starter: { monthly_price_cents: 9900 },
          pro: { monthly_price_cents: 19900, included_seats: 10 },
        },
      },
      'x.yaml',
    )
    expect(outcome.ok).toBe(false)
  })

  it('accepts a negotiated tier and creates no price for it', () => {
    const outcome = parseBillingCatalogue(
      {
        ...base,
        plans: {
          starter: { monthly_price_cents: 9900, included_users: 3 },
          enterprise: { custom: true },
        },
      },
      'x.yaml',
    )
    expect(outcome.ok).toBe(true)
    if (!outcome.ok) return
    expect(outcome.catalogue.plans.map((p) => p.code)).toEqual(['starter'])
    expect(outcome.catalogue.custom.map((p) => p.code)).toEqual(['enterprise'])
  })

  it('refuses a negotiated tier that also names a price', () => {
    // Both at once is a contradiction: it is either sold at a number or it is
    // negotiated. Silently preferring one would make the file mean something
    // other than it says -- and which one it preferred would depend on the
    // order of a union, which is not where a commercial decision should live.
    //
    // A priced plan sits beside it for the same reason as the test above:
    // alone, this is refused as a catalogue with no priced plan whether the
    // schema is strict or not.
    const outcome = parseBillingCatalogue(
      {
        ...base,
        plans: {
          starter: { monthly_price_cents: 9900 },
          enterprise: { custom: true, monthly_price_cents: 99900 },
        },
      },
      'x.yaml',
    )
    expect(outcome.ok).toBe(false)
    if (outcome.ok) return
    expect(outcome.problem.detail).not.toContain('names no priced plan')
  })

  it('says so when every tier is negotiated, rather than reporting an empty file', () => {
    const outcome = parseBillingCatalogue(
      { ...base, plans: { enterprise: { custom: true } } },
      'x.yaml',
    )
    expect(outcome.ok).toBe(false)
    if (outcome.ok) return
    expect(outcome.problem.detail).toContain('negotiated')
    expect(outcome.problem.detail).not.toContain('declares no plans')
  })

  it('refuses an included user count of zero', () => {
    // A plan including nobody cannot be used, and zero is what an unset
    // variable interpolates to.
    expect(
      parseBillingCatalogue(
        { ...base, plans: { pro: { monthly_price_cents: 9900, included_users: 0 } } },
        'x.yaml',
      ).ok,
    ).toBe(false)
  })

  it('takes limits as an open map, so a product-specific ceiling needs no schema change', () => {
    const outcome = parseBillingCatalogue(
      {
        ...base,
        plans: {
          pro: {
            monthly_price_cents: 19900,
            limits: { 'storage.files': 50, 'workflows.runs': 10_000, 'api.calls': 250_000 },
          },
        },
      },
      'x.yaml',
    )
    expect(outcome.ok).toBe(true)
    if (!outcome.ok) return
    expect(outcome.catalogue.plans[0].limits).toEqual({
      'storage.files': 50,
      'workflows.runs': 10_000,
      'api.calls': 250_000,
    })
  })

  it('reads the standard extra seat, and treats an absent one as absent', () => {
    const withSeat = parseBillingCatalogue(
      {
        ...base,
        additional_user: { monthly_price_cents: 2500, annual_price_cents: 25000 },
        plans: { starter: { monthly_price_cents: 9900 } },
      },
      'x.yaml',
    )
    expect(withSeat.ok).toBe(true)
    if (!withSeat.ok) return
    expect(withSeat.catalogue.additionalUser).toEqual({ monthly: 2500, yearly: 25000 })

    const without = parseBillingCatalogue(
      { ...base, plans: { starter: { monthly_price_cents: 9900 } } },
      'x.yaml',
    )
    expect(without.ok).toBe(true)
    if (!without.ok) return
    expect(without.catalogue.additionalUser).toBeNull()
  })

  it('reports nothing inert for a catalogue that declares only prices', () => {
    // The counterpart to the generated-file test: the inert list must be
    // driven by what is declared, not printed unconditionally. A warning that
    // always appears is one nobody reads.
    const outcome = parseBillingCatalogue(
      { ...base, plans: { starter: { monthly_price_cents: 9900 } } },
      'x.yaml',
    )
    expect(outcome.ok).toBe(true)
    if (!outcome.ok) return
    expect(declaredButInert(outcome.catalogue)).toEqual([])
  })

  it('defaults the versions rather than requiring them', () => {
    const outcome = parseBillingCatalogue(
      { ...base, plans: { starter: { monthly_price_cents: 9900 } } },
      'x.yaml',
    )
    expect(outcome.ok).toBe(true)
    if (!outcome.ok) return
    expect(outcome.catalogue.catalogueVersion).toBe(1)
    expect(outcome.catalogue.plans[0].planVersion).toBe(1)
  })
})

describe('what Phase 3 provisions', () => {
  const WITH_EXTRA_SEAT = `
version: 1
catalogue_version: 4
currency: usd
additional_user:
  monthly_price_cents: 2500
  annual_price_cents: 25000
plans:
  starter:
    name: Starter
    plan_version: 2
    monthly_price_cents: 9900
    annual_price_cents: 99000
    included_users: 3
`

  it('creates the extra-seat prices, under their own provider product', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter')]
    writeCatalogue(WITH_EXTRA_SEAT)

    const report = await run(estate)

    expect(report.kind).toBe('provisioned')
    if (report.kind !== 'provisioned') return

    expect(estate.prices.map((p) => p.lookup_key).sort()).toEqual([
      'acme_extra-user_monthly_usd',
      'acme_extra-user_yearly_usd',
      'acme_starter_monthly_usd',
      'acme_starter_yearly_usd',
    ])

    // Its own provider product, not hung off a plan's. A seat is not a tier,
    // and an invoice line naming "Acme Starter" for an extra user would be
    // wrong in the one place a customer reads.
    expect([...estate.products.keys()].sort()).toEqual(['koras_acme_extra_user', 'koras_acme_starter'])
    expect(estate.products.get('koras_acme_extra_user')!.name).toBe(
      'Acme Additional Internal User',
    )

    expect(report.extraUser?.month).toMatchObject({ kind: 'created', amount: 2500 })
    expect(report.extraUser?.year).toMatchObject({ kind: 'created', amount: 25000 })
  })

  it('writes nothing to the Control Plane for the extra seat', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter')]
    writeCatalogue(WITH_EXTRA_SEAT)

    await run(estate)

    // There is no column to hold an add-on price, and inventing one here
    // would be the factory deciding another repository's schema. The plan row
    // must carry only the plan's own prices.
    const written = estate.plans.find((p) => p.code === 'starter')!
    expect(Object.keys(written).filter((k) => k.includes('extra'))).toEqual([])
    expect(written.price_id_month).toMatch(/^price_/)
  })

  it('syncs what the plan includes to the Control Plane', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter', { included_users: null })]
    writeCatalogue(WITH_EXTRA_SEAT)

    await run(estate)

    expect(estate.plans.find((p) => p.code === 'starter')!.included_users).toBe(3)
  })

  it('leaves the platform default alone when the catalogue states nothing', async () => {
    const estate = new Estate()
    // The platform seeded three. A catalogue that says nothing about the
    // included count is not a catalogue saying zero, and overruling a seeded
    // default with silence is how a product loses seats it was sold.
    estate.plans = [plan('starter', { included_users: 3 })]
    writeCatalogue(`
version: 1
currency: usd
plans:
  starter:
    monthly_price_cents: 9900
`)

    await run(estate)

    expect(estate.plans.find((p) => p.code === 'starter')!.included_users).toBe(3)
  })

  it('labels every provider object with the standard metadata', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter')]
    writeCatalogue(WITH_EXTRA_SEAT)

    await run(estate)

    const priceWrite = estate.calls.find(
      (call) => call.method === 'POST' && call.url.endsWith('/v1/prices'),
    )!
    const form = new URLSearchParams(priceWrite.body ?? '')

    expect(form.get('metadata[platform]')).toBe('koras')
    expect(form.get('metadata[application]')).toBe('acme')
    expect(form.get('metadata[environment]')).toBe('dev')
    expect(form.get('metadata[plan_code]')).toBe('starter')
    expect(form.get('metadata[plan_version]')).toBe('2')
    expect(form.get('metadata[catalog_version]')).toBe('4')
    expect(form.get('metadata[billing_interval]')).toBe('month')
    // Read from the platform rather than remembered from a registration this
    // command did not perform.
    expect(form.get('metadata[product_registration_id]')).toBe('prod-uuid-1')
  })

  it('provisions correct prices when the product id cannot be read', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter')]
    writeCatalogue(WITH_EXTRA_SEAT)
    // The listing is restricted to staff and could fail for reasons that have
    // nothing to do with pricing. Metadata is a label, never an authorization
    // source, so one label fewer beats refusing to price the product.
    estate.productsStatus = 403

    const report = await run(estate)

    expect(report.kind).toBe('provisioned')
    const priceWrite = estate.calls.find(
      (call) => call.method === 'POST' && call.url.endsWith('/v1/prices'),
    )!
    const form = new URLSearchParams(priceWrite.body ?? '')
    expect(form.get('metadata[product_registration_id]')).toBeNull()
    expect(form.get('metadata[platform]')).toBe('koras')
  })

  it('a second run creates no extra-seat price either', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter')]
    writeCatalogue(WITH_EXTRA_SEAT)

    await run(estate)
    const after = estate.prices.length
    estate.calls.length = 0

    const second = await run(estate)

    expect(second.kind).toBe('provisioned')
    if (second.kind !== 'provisioned') return
    expect(second.noop).toBe(true)
    expect(estate.mutatingWrites).toEqual([])
    expect(estate.prices).toHaveLength(after)
    expect(second.extraUser?.month?.kind).toBe('reused')
  })
})

describe('what Phase 4 records', () => {
  const CATALOGUE = `
version: 1
catalogue_version: 7
currency: usd
additional_user:
  monthly_price_cents: 2500
  annual_price_cents: 25000
plans:
  starter:
    name: Starter
    plan_version: 3
    monthly_price_cents: 9900
    annual_price_cents: 99000
    included_users: 3
    limits:
      storage.files: 10
      workflows.runs: 500
`

  it('records the terms, with the references of prices that now exist', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter')]
    writeCatalogue(CATALOGUE)

    const report = await run(estate)
    expect(report.kind).toBe('provisioned')
    if (report.kind !== 'provisioned') return
    expect(report.catalogueRecorded).toBe(1)

    const recorded = estate.catalogue.get('starter@3')!
    expect(recorded.plan_version).toBe(3)
    expect(recorded.catalogue_version).toBe(7)
    expect(recorded.amount_month).toBe(9900)
    expect(recorded.amount_year).toBe(99000)
    expect(recorded.included_users).toBe(3)
    expect(recorded.currency).toBe('usd')
    expect(recorded.limits).toEqual({ 'storage.files': 10, 'workflows.runs': 500 })

    // The references are the prices that were just created, not placeholders.
    expect(recorded.price_id_month).toMatch(/^price_/)
    expect(recorded.extra_user_price_id_month).toMatch(/^price_/)
    expect(recorded.extra_user_amount_month).toBe(2500)
  })

  it('records it only after every price it names exists', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter')]
    writeCatalogue(CATALOGUE)

    await run(estate)

    // The ordering is the property, not a detail. A version naming a price
    // that failed to be created is a record of terms nobody can be charged
    // on, so the catalogue write must come after the last price write.
    const lastPrice = estate.calls.findLastIndex(
      (call) => call.method === 'POST' && call.url.endsWith('/v1/prices'),
    )
    const firstCatalogue = estate.calls.findIndex((call) =>
      call.url.endsWith('/api/platform/v1/plan-catalogue'),
    )
    expect(lastPrice).toBeGreaterThan(-1)
    expect(firstCatalogue).toBeGreaterThan(lastPrice)
  })

  it('records nothing for a negotiated tier', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter'), plan('enterprise', { self_serve: false })]
    writeCatalogue(`
version: 1
currency: usd
plans:
  starter:
    monthly_price_cents: 9900
  enterprise:
    custom: true
`)

    await run(estate)

    // Its terms are whatever was negotiated, which this command does not know
    // and must not invent. A recorded version of zeroes would be the platform
    // stating terms nobody agreed.
    expect([...estate.catalogue.keys()]).toEqual(['starter@1'])
  })

  it('reports the prices as done when only the record fails', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter')]
    writeCatalogue(CATALOGUE)
    estate.stripeStatusOverride = {
      path: '/api/platform/v1/plan-catalogue',
      status: 500,
      body: '{"detail":"boom"}',
    }

    const report = await run(estate)

    expect(report.kind).toBe('failed')
    if (report.kind !== 'failed') return
    // The failure is partial in a way that reads as total. Saying which half
    // succeeded is the difference between a safe retry and somebody going to
    // look for prices that are already there.
    expect(report.detail).toContain('prices exist')
    expect(report.retryable).toBe(true)
    expect(estate.prices.length).toBeGreaterThan(0)
  })
})

describe('a refusal points somewhere', () => {
  it('reads a 401 as an expired staff token first', async () => {
    const estate = new Estate()
    estate.plans = [plan('starter')]
    writeCatalogue(TWO_PLANS)
    estate.stripeStatusOverride = {
      path: '/api/platform/v1/plans',
      status: 401,
      body: '{"detail":"Unauthorized"}',
    }

    const report = await run(estate)

    expect(report.kind).toBe('failed')
    if (report.kind !== 'failed') return
    // The credential is a person's token that lasts hours, so expiry is the
    // common case. A 401 and a 403 read identically from outside -- "it said
    // no" -- and send somebody to entirely different places.
    expect(report.detail).toContain('expired')
    expect(report.detail).toContain('second factor')
  })
})
