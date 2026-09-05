import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * A signup that takes a card, in the product template.
 *
 * Phase 3 of docs/BILLING_DESIGN.md. Between a proved address and a
 * provisioned workspace there is now a checkout, opened by the payment
 * provider's script in the browser with a public token, and the run starts
 * when the provider's webhook reaches the Control Plane rather than when the
 * page says so. These assert the decisions in that which are easy to undo by
 * accident: where the script comes from, what the policy admits, what the
 * form posts, what the page polls, and that no server-side key ever appears
 * in this template.
 */

const TEMPLATE = join(__dirname, '..', '..', '..', 'profiles', 'product', 'template')
const SIGNUP = join(TEMPLATE, 'apps', 'web', 'src', 'app', 'signup')

function read(...segments: string[]): string {
  return readFileSync(join(TEMPLATE, ...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

function signup(...segments: string[]): string {
  return readFileSync(join(SIGNUP, ...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

describe('the form', () => {
  const form = signup('SignupForm.tsx.hbs')
  const actions = signup('actions.ts.hbs')

  it('posts the interval and the seat count the Control Plane stores', () => {
    expect(actions).toContain('billing_interval: billingInterval')
    expect(actions).toContain('seats,')
    expect(form).toContain('name="billingInterval"')
    expect(form).toContain('name="seats"')
  })

  it('asks about billing only when the plan is sold both ways', () => {
    // Two prices: a choice. One: submitted silently. None: a free trial that
    // is not asked about at all.
    expect(form).toContain('soldMonthly && soldYearly')
    expect(form).toMatch(/type="hidden" name="billingInterval"/)
  })

  it('checks seats against the bounds the catalogue supplied', () => {
    expect(actions).toContain("field: 'seats'")
    expect(actions).toContain('min_seats')
    expect(actions).toContain('max_seats')
  })

  it('fills in a catalogue from before the billing work as a free trial', () => {
    expect(actions).toContain('price_id_month: plan.price_id_month ?? null')
    expect(actions).toContain('min_seats: plan.min_seats ?? 1')
  })
})

describe('the verify page', () => {
  const verify = signup('verify', 'page.tsx.hbs')
  const actions = signup('actions.ts.hbs')

  it('has a fourth outcome, and hands it to the checkout', () => {
    expect(actions).toContain("status: 'awaiting-payment'")
    expect(verify).toContain("outcome.status === 'awaiting-payment'")
    expect(verify).toContain('<Checkout')
    expect(verify).toContain('data-testid="verify-checkout"')
  })

  it('keeps the three outcomes it had, with their wording untouched', () => {
    for (const marker of ['verify-rate-limited', 'verify-failed', 'verify-ok']) {
      expect(verify).toContain(`data-testid="${marker}"`)
    }
    expect(verify).toContain('outcome.jobId')
    expect(verify).toContain('outcome.organizationSlug')
  })
})

describe('the checkout', () => {
  const checkout = signup('Checkout.tsx.hbs')
  const waiting = signup('ProvisioningStatus.tsx.hbs')
  const actions = signup('actions.ts.hbs')

  it("loads the provider's script from the provider, not from this repository", () => {
    expect(checkout).toContain("'https://cdn.paddle.com/paddle/v2/paddle.js'")
    expect(checkout).toContain("from 'next/script'")
  })

  it('opens the checkout with the public token and nothing else', () => {
    expect(checkout).toContain('process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN')
    // No server-side key of any provider, anywhere in the template.
    expect(checkout).not.toMatch(/PADDLE_(API_KEY|WEBHOOK_SECRET)|pdl_(sdbx|live)_apikey/)
  })

  it('defaults to the sandbox, so a token with no environment cannot charge a card', () => {
    expect(checkout).toMatch(/=== 'production' \? 'production' : 'sandbox'/)
  })

  it('carries the ids the webhook finds its way back with', () => {
    for (const key of ['registration_id', 'organization_id', 'product_code', 'plan_code']) {
      expect(checkout).toContain(`${key}:`)
    }
  })

  it("trusts the webhook, not the browser: a completed checkout starts a wait, not a workspace", () => {
    expect(checkout).toContain("event.name === 'checkout.completed'")
    expect(checkout).toContain('<ProvisioningStatus')
    expect(checkout).toContain('registrationId={checkout.registrationId}')
    expect(checkout).not.toContain('successUrl')
  })

  it('polls by registration until the run exists, and treats the wait as pending', () => {
    expect(waiting).toContain('registrationId')
    expect(waiting).toContain('signupStatus(jobId, registrationId)')
    expect(actions).toContain('registration_id=${encodeURIComponent(registrationId)}')
  })

  it('says plainly what a closed checkout means', () => {
    expect(checkout).toContain("event.name === 'checkout.closed'")
    expect(checkout).toContain('data-testid="checkout-reopen"')
  })

  it('answers a Control Plane that asks for a card the product cannot take', () => {
    expect(checkout).toContain("t('checkout.notConfigured.title')")
  })
})

describe('the policy', () => {
  const middleware = read('apps', 'web', 'src', 'middleware.ts.hbs')

  it("admits the provider's hosts exactly when a token is configured", () => {
    expect(middleware).toContain("const PADDLE_HOSTS = 'https://*.paddle.com'")
    expect(middleware).toContain('Boolean(process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN)')
    // The overlay is a frame, and frame-src is the directive that decides
    // what may be drawn over the page. Nobody, unless the product takes a card.
    expect(middleware).toMatch(/frame-src \$\{takesCards \? PADDLE_HOSTS : "'none'"\}/)
  })

  it('keeps every visitor-facing page unframable', () => {
    expect(middleware).toContain("frame-ancestors 'none'")
  })
})

describe('the settings', () => {
  const manifest = read('local', 'config', 'secrets.manifest.hbs')
  const example = read('local', 'config', '.env.local.example.hbs')

  it('declares both as optional, because a product may take no card', () => {
    expect(manifest).toContain('NEXT_PUBLIC_PADDLE_CLIENT_TOKEN optional')
    expect(manifest).toContain('NEXT_PUBLIC_PADDLE_ENVIRONMENT optional')
    expect(example).toContain('NEXT_PUBLIC_PADDLE_CLIENT_TOKEN=')
    expect(example).toContain('NEXT_PUBLIC_PADDLE_ENVIRONMENT=sandbox')
  })

  it('never declares a server-side provider key for a product', () => {
    expect(manifest).not.toMatch(/^PADDLE_(API_KEY|WEBHOOK_SECRET)/m)
  })
})

describe('the catalogues', () => {
  const keys = (locale: string) =>
    new Set(
      [...read('packages', 'i18n', 'src', 'messages', `${locale}.ts`).matchAll(/^\s*'([a-zA-Z.]+)':/gm)].map(
        (match) => match[1],
      ),
    )

  it('carry every checkout key in all three languages', () => {
    const en = keys('en')
    const required = [
      'signup.form.interval',
      'signup.form.interval.month',
      'signup.form.interval.year',
      'signup.form.seats',
      'signup.form.seatsHint',
      'signup.form.seatsHintMin',
      'signup.form.noteCard',
      'signup.error.seats',
      'signup.error.seatsMin',
      'signup.error.interval',
      'checkout.title',
      'checkout.description',
      'checkout.opening',
      'checkout.waiting',
      'checkout.open',
      'checkout.trialNote',
      'checkout.closed.title',
      'checkout.closed.description',
      'checkout.failed.title',
      'checkout.failed.description',
      'checkout.failed.reload',
      'checkout.notConfigured.title',
      'checkout.notConfigured.description',
    ]
    for (const key of required) expect(en.has(key), `en lacks ${key}`).toBe(true)
    for (const locale of ['de', 'es']) {
      const other = keys(locale)
      for (const key of required) expect(other.has(key), `${locale} lacks ${key}`).toBe(true)
    }
  })
})
