import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * The pricing section: plans from the platform, prices from the provider.
 *
 * The first step of the flow in docs/BILLING_DESIGN.md, and the one the
 * design assumed existed. These assert the two rules that make it honest --
 * the list of plans is the Control Plane's public catalogue, and no amount is
 * typed anywhere in this repository -- and the plumbing between the card a
 * stranger clicks and the signup form it preselects.
 */

const TEMPLATE = join(__dirname, '..', '..', '..', 'profiles', 'product', 'template')

function read(...segments: string[]): string {
  return readFileSync(join(TEMPLATE, ...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

describe('the section', () => {
  const section = read('packages', 'ui', 'src', 'marketing', 'pricing-section.tsx.hbs')
  const plans = read('packages', 'ui', 'src', 'marketing', 'pricing-plans.tsx.hbs')

  it('is the anchor the navigation points at, and renders nothing when nothing is on sale', () => {
    expect(section).toContain('id="pricing"')
    expect(section).toContain('if (plans.length === 0) return null')
  })

  it("asks the provider for every price and never carries one of its own", () => {
    expect(plans).toContain('paddle.PricePreview(')
    // Per seat, at each plan's least seats: the provider refuses a whole
    // preview when one line is below its price's quantity floor.
    expect(plans).toContain('quantity: plan.min_seats')
    expect(plans).toContain('line.formattedUnitTotals?.total ?? line.formattedTotals.total')
    expect(plans).toContain('setFailed(true)')
    // No currency amount anywhere in the section or the configuration.
    for (const source of [section, plans, read('packages', 'branding', 'src', 'index.ts.hbs')]) {
      expect(source).not.toMatch(/[$€£]\s?\d/)
    }
  })

  it('says the price is at the checkout where it cannot ask', () => {
    expect(plans).toContain('labels.priceAtCheckout')
    expect(plans).toContain("const canPreview = paddleToken !== '' && items.length > 0 && !failed")
  })

  it('carries the plan and the interval into the signup form', () => {
    expect(plans).toContain('/signup?plan=${encodeURIComponent(plan.code)}&interval=${shown}')
  })

  it('gives a sales-led plan a card with no trial and the contact address', () => {
    // The catalogue lists every active plan. One the platform will not sell
    // to a stranger is shown, not hidden -- with no amount, no trial button
    // and the product's own address where the button would be.
    expect(plans).toContain('const startable = canSignUp(plan)')
    expect(plans).toContain('labels.custom')
    expect(plans).toContain('labels.noTrial')
    expect(plans).toContain('testId={`pricing-${plan.code}-contact`}')
    // And the form never offers it: the same rule decides both.
    const actions = read('apps/web/src/app/signup/actions.ts.hbs')
    expect(actions).toContain('(await loadPublicPlans()).filter(canSignUp)')
  })

  it('shares one view of the provider script with the checkout', () => {
    const paddle = read('packages', 'ui', 'src', 'lib', 'paddle.ts')
    expect(paddle).toContain("export const PADDLE_JS = 'https://cdn.paddle.com/paddle/v2/paddle.js'")
    expect(paddle).toMatch(/=== 'production' \? 'production' : 'sandbox'/)
    const checkout = read('apps', 'web', 'src', 'app', 'signup', 'Checkout.tsx.hbs')
    expect(checkout).toContain('PADDLE_JS')
    expect(checkout).toContain('paddleEnvironment(')
    expect(checkout).not.toContain('declare global')
  })
})

describe('the pages', () => {
  for (const [app, page] of [
    ['web', join('apps', 'web', 'src', 'app', 'page.tsx.hbs')],
    ['marketing', join('apps', 'marketing', 'src', 'app', 'page.tsx.hbs')],
  ] as const) {
    it(`${app} renders the section from the platform's catalogue, read on the server`, () => {
      const source = read(page)
      expect(source).toContain('<PricingSection')
      expect(source).toContain('loadPublicPlans()')
      expect(source).toContain('process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN')
    })
    it(`${app} keeps the platform's address on the server`, () => {
      const loader = read('apps', app, 'src', 'lib', 'plans.ts.hbs')
      expect(loader).toContain('process.env.KORAS_CONTROL_PLANE_URL')
      expect(loader).toContain("cache: 'no-store'")
      expect(loader).toContain('parsePublicPlans(')
    })
  }
})

describe('the signup form', () => {
  const page = read('apps', 'web', 'src', 'app', 'signup', 'page.tsx.hbs')
  const form = read('apps', 'web', 'src', 'app', 'signup', 'SignupForm.tsx.hbs')

  it('preselects what the pricing card chose', () => {
    expect(page).toContain('searchParams')
    expect(page).toContain('initialPlan=')
    expect(page).toContain('initialInterval=')
    expect(form).toContain('initialPlan')
    expect(form).toContain("initialInterval === 'year'")
  })
})

describe('the catalogue parser', () => {
  const branding = read('packages', 'branding', 'src', 'index.ts.hbs')

  it('lives in branding, where the tests run, and fills in an older platform as a free trial', () => {
    expect(branding).toContain('export function parsePublicPlans(')
    expect(branding).toContain('price_id_month:')
    expect(branding).toContain('min_seats:')
  })
})

describe('the copy', () => {
  const branding = read('packages', 'branding', 'src', 'index.ts.hbs')

  it('names the section in every language, in the header and the footer', () => {
    for (const label of ['Pricing', 'Preise', 'Precios']) {
      expect(branding).toContain(`{ label: '${label}', href: '/#pricing' }`)
    }
  })

  it('carries the section copy and plan highlights per language', () => {
    for (const key of ['pricingEyebrow', 'pricingTitle', 'pricingDescription', 'pricingNote', 'planHighlights']) {
      expect(branding.split(`${key}:`).length - 1, `${key} is set fewer than four times`).toBeGreaterThanOrEqual(4)
    }
  })

  it('carries every label in all three catalogues', () => {
    const keys = (locale: string) =>
      new Set(
        [...read('packages', 'i18n', 'src', 'messages', `${locale}.ts`).matchAll(/^\s*'([a-zA-Z.]+)':/gm)].map(
          (match) => match[1],
        ),
      )
    const required = [
      'pricing.monthly',
      'pricing.yearly',
      'pricing.billing',
      'pricing.perSeatMonth',
      'pricing.perSeatYear',
      'pricing.choose',
      'pricing.priceAtCheckout',
      'pricing.loading',
      'pricing.seatsRange',
      'pricing.seatsFrom',
      'pricing.singleSeat',
    ]
    for (const locale of ['en', 'de', 'es']) {
      const present = keys(locale)
      for (const key of required) expect(present.has(key), `${locale} lacks ${key}`).toBe(true)
    }
  })
})
