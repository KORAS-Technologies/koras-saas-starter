import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * A signup that takes a card, in the product template.
 *
 * Phase 3 of docs/BILLING_DESIGN.md. Between a proved address and a
 * provisioned workspace there is now a checkout -- a page the payment
 * provider hosts, minted by the Control Plane and reached by a URL the
 * product is handed -- and the run starts when the provider's webhook
 * reaches the Control Plane rather than when the page says so. These assert
 * the decisions in that which are easy to undo by accident: that no provider
 * script or token is in the product, what the policy admits, what the form
 * posts, where the checkout comes back to, what the page polls, and that no
 * provider key of any kind ever appears in this template.
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
    // The rule moved into `parsePublicPlans` in packages/branding when the
    // pricing section became a second reader of the catalogue.
    const branding = read('packages', 'branding', 'src', 'index.ts.hbs')
    // Narrowed to what the form may offer: the catalogue also lists the
    // sales-led tiers for the pricing page, and the platform refuses those.
    expect(actions).toContain('(await loadPublicPlans()).filter(canSignUp)')
    expect(branding).toContain('export function parsePublicPlans(')
    expect(branding).toContain('min_seats: typeof plan.min_seats === ')
  })
})

describe('the verify page', () => {
  const verify = signup('verify', 'page.tsx.hbs')
  const actions = signup('actions.ts.hbs')

  it('has a fourth outcome, and hands it to the checkout', () => {
    expect(actions).toContain("status: 'awaiting-payment'")
    expect(actions).toContain('url: body.checkout.url')
    expect(verify).toContain("outcome.status === 'awaiting-payment'")
    expect(verify).toContain('<Checkout')
    expect(verify).toContain('data-testid="verify-checkout"')
  })

  it('is where the hosted checkout comes back to, by registration id and one word', () => {
    // `done` starts the same wait as the free-trial path, by registration;
    // `cancelled` offers the checkout again. Neither is trusted as a fact
    // about money: the webhook is what ends the wait.
    expect(verify).toContain('registration?: string; checkout?: string')
    expect(verify).toContain('if (!token && registration)')
    expect(verify).toContain("checkout === 'cancelled'")
    expect(verify).toContain('<CheckoutClosed registrationId={registration}')
    expect(verify).toContain('data-testid="verify-checkout-closed"')
    expect(verify).toContain('<ProvisioningStatus registrationId={registration}')
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

  it('loads no provider script and holds no provider token, public or otherwise', () => {
    expect(checkout).not.toMatch(/next\/script|paddle|stripe\.js|NEXT_PUBLIC_/i)
    expect(() => read('packages', 'ui', 'src', 'lib', 'paddle.ts')).toThrow()
    // No key of any provider, anywhere in the template's signup surface.
    expect(checkout + actions).not.toMatch(/(PADDLE|STRIPE)_(API_KEY|SECRET_KEY|WEBHOOK_SECRET)|sk_(test|live)_/)
  })

  it('sends the browser to the URL the Control Plane minted, and leaves a button behind', () => {
    expect(checkout).toContain('window.location.assign(checkout.url)')
    expect(checkout).toContain('href={checkout.url}')
    expect(checkout).toContain('testId="checkout-open"')
  })

  it("trusts the webhook, not the browser: coming back from the checkout starts a wait, not a workspace", () => {
    const verify = signup('verify', 'page.tsx.hbs')
    expect(verify).toContain('<ProvisioningStatus registrationId={registration}')
    expect(checkout).not.toContain('ready')
    expect(checkout).not.toContain('/dashboard')
  })

  it('polls by registration until the run exists, and treats the wait as pending', () => {
    expect(waiting).toContain('registrationId')
    expect(waiting).toContain('signupStatus(jobId, registrationId)')
    expect(actions).toContain('registration_id=${encodeURIComponent(registrationId)}')
  })

  it('says plainly what a closed checkout means, and asks for it again by registration id', () => {
    const closed = signup('CheckoutClosed.tsx.hbs')
    expect(closed).toContain("t('checkout.closed.title')")
    expect(closed).toContain('data-testid="checkout-reopen"')
    expect(closed).toContain('reopenCheckout(registrationId)')
    expect(actions).toContain('/api/signup/v1/registrations/checkout')
    expect(actions).toContain('registration_id: registrationId')
  })
})

describe('the policy', () => {
  const middleware = read('apps', 'web', 'src', 'middleware.ts.hbs')

  it('names no provider host, because the checkout is a page the browser leaves for', () => {
    expect(middleware).not.toMatch(/paddle|stripe/i)
    // frame-src is the directive that decides what may be drawn over the
    // page. Nobody: the card is typed on the provider's own origin.
    expect(middleware).toContain(`"frame-src 'none'"`)
  })

  it('keeps every visitor-facing page unframable', () => {
    expect(middleware).toContain("frame-ancestors 'none'")
  })
})

describe('the settings', () => {
  const manifest = read('local', 'config', 'secrets.manifest.hbs')
  const example = read('local', 'config', '.env.local.example.hbs')

  it('declares no provider setting at all, and says why', () => {
    expect(manifest).toContain('No payment provider setting, and none is missing.')
    expect(manifest).not.toMatch(/PADDLE|STRIPE/)
    expect(example).not.toMatch(/PADDLE|STRIPE/)
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
      'checkout.open',
      'checkout.trialNote',
      'checkout.closed.title',
      'checkout.closed.description',
      'checkout.failed.title',
      'checkout.failed.description',
    ]
    for (const key of required) expect(en.has(key), `en lacks ${key}`).toBe(true)
    for (const locale of ['de', 'es']) {
      const other = keys(locale)
      for (const key of required) expect(other.has(key), `${locale} lacks ${key}`).toBe(true)
    }
  })
})
