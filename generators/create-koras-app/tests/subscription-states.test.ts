import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * The shell says what the subscription is doing, and decides nothing from it.
 *
 * Phase 4 of docs/BILLING_DESIGN.md, the product's half. A trial counting
 * down and a failed charge are a line above the page; an ended trial and a
 * cancelled subscription close the product. These assert the decisions that
 * are easy to lose: that the state comes from the platform's answer and not
 * from anything local, that the closed states replace the page rather than
 * annotate it, that only an administrator is shown the way to the portal, and
 * that all three languages carry the words.
 */

const TEMPLATE = join(__dirname, '..', '..', '..', 'profiles', 'product', 'template')

function read(...segments: string[]): string {
  return readFileSync(join(TEMPLATE, ...segments), 'utf8').split(String.fromCharCode(13)).join('')
}

describe('the entitlement set', () => {
  const branding = read('packages', 'branding', 'src', 'index.ts.hbs')

  it('carries the subscription state the platform answers, and null for one that does not', () => {
    expect(branding).toContain('export interface SubscriptionState')
    expect(branding).toContain('subscription?: SubscriptionState | null')
    // Read by the platform's field names, which is the only thing the parser is.
    expect(branding).toContain("typeof record.status === 'string'")
    expect(branding).toContain("typeof record.trial_ends_at === 'string'")
    expect(branding).toContain("typeof record.current_period_end === 'string'")
  })

  it('leaves the unresolved constant without a state', () => {
    expect(branding).toMatch(/NO_ENTITLEMENTS: EntitlementSet = \{[\s\S]*?subscription: null,\n\}/)
  })
})

describe('the notice', () => {
  const notice = read('packages', 'ui', 'src', 'shell', 'subscription-notice.tsx.hbs')

  it('closes the product for exactly the two states that end it', () => {
    expect(notice).toMatch(
      /subscription\?\.status === 'suspended' \|\| subscription\?\.status === 'cancelled'/,
    )
  })

  it('annotates a trial and a failed charge, and says nothing for an active one', () => {
    expect(notice).toContain("subscription.status === 'trialing'")
    expect(notice).toContain("subscription.status === 'past_due'")
    expect(notice).toContain('testId="subscription-trial"')
    expect(notice).toContain('testId="subscription-past-due"')
    expect(notice).toContain('data-testid="subscription-closed"')
    // The fall-through: nothing rendered.
    expect(notice).toMatch(/\n {2}return null\n\}/)
  })

  it('offers the portal only to somebody who was given the link', () => {
    expect(notice).toContain('manageUrl?: string')
    expect(notice).toContain("t('subscription.closed.descriptionMember'")
  })

  it('reads the days from the wall clock it is given, so a test can move it', () => {
    expect(notice).toContain('now = Date.now()')
    expect(notice).toContain('function daysUntil(')
  })
})

describe('the layout', () => {
  const layout = read('apps', 'web', 'src', 'app', 'dashboard', 'layout.tsx.hbs')

  it('takes the state from the resolved entitlements and nowhere else', () => {
    expect(layout).toContain('const subscription = access.entitlements.subscription ?? null')
  })

  it('replaces the page for a closed subscription and annotates it otherwise', () => {
    expect(layout).toContain('subscriptionBlocks(subscription)')
    expect(layout).toContain('<SubscriptionClosed')
    expect(layout).toContain('<SubscriptionNotice')
  })

  it("links to the portal's billing page, only where the account link already exists", () => {
    // `accountUrl` is already undefined for anybody but a product administrator;
    // the billing link derives from it rather than deciding again.
    expect(layout).toMatch(/const manageUrl = accountUrl \? `\$\{accountUrl\.replace\(.*\)\}\/billing` : undefined/)
  })

  it('keeps inline object literals out of the template', () => {
    // `{{projectSlug}}` is the one double brace a template may carry; a JSX
    // prop opening with two braces stops generation of the whole project.
    expect(layout.replace(/\{\{projectSlug\}\}/g, '')).not.toContain('{{')
  })
})

describe('the catalogues', () => {
  const keys = (locale: string) =>
    new Set(
      [...read('packages', 'i18n', 'src', 'messages', `${locale}.ts`).matchAll(/^\s*'([a-zA-Z.]+)':/gm)].map(
        (match) => match[1],
      ),
    )

  it('carry every subscription key in all three languages', () => {
    const required = [
      'subscription.trial.endsIn',
      'subscription.trial.endsToday',
      'subscription.trial.open',
      'subscription.trial.addCard',
      'subscription.pastDue.graceDays',
      'subscription.pastDue.open',
      'subscription.pastDue.fixCard',
      'subscription.closed.trialTitle',
      'subscription.closed.title',
      'subscription.closed.descriptionAdmin',
      'subscription.closed.descriptionMember',
      'subscription.closed.action',
    ]
    for (const locale of ['en', 'de', 'es']) {
      const present = keys(locale)
      for (const key of required) expect(present.has(key), `${locale} lacks ${key}`).toBe(true)
    }
  })
})
