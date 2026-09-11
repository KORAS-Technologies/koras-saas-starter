import { describe, it, expect } from 'vitest'
import { execFileSync } from 'node:child_process'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

/**
 * An identifier named in a document has to exist in the code.
 *
 * The third mechanical class in R-042, after paths and lists. A document
 * described `environments/dev.tfvars` files configured through a
 * `vercel_target`; neither has existed at any point. Another described a
 * `terraform.tfvars.json` written to a temporary directory and deleted, which
 * is not how any of it works. Both read as descriptions of the system and were
 * descriptions of a plan replaced before it was built.
 *
 * Measured when written: 683 identifier-shaped mentions across the documents,
 * of which 12 resolved to nothing and 8 of those were legitimate. A check that
 * finds 4 real problems in 683 mentions is worth having; one that flagged 100
 * would be switched off, which is why the filters below are narrow rather than
 * clever.
 *
 * What counts as an identifier: SCREAMING_SNAKE_CASE, and lower_snake_case with
 * at least one underscore. A lowercase word without one is prose --
 * `microservice` is not a symbol -- and matching it would flag English.
 */

const ROOT = join(__dirname, '..', '..')

/**
 * Named in a document, absent from the code, and correctly so.
 *
 * Each is asserted absent below. An exemption is a claim too, and one that
 * quietly stops being true is the same defect this file exists to catch.
 */
const ABSENT_ON_PURPOSE: Record<string, string> = {
  ZITADEL_DEV_SERVICE_TOKEN: 'built at runtime from the environment name',
  ZITADEL_TEST_SERVICE_TOKEN: 'built at runtime from the environment name',
  ZITADEL_PROD_SERVICE_TOKEN: 'built at runtime from the environment name',
  STATUS_DLL_INIT_FAILED: 'a Windows error code, quoted in a failure table',
  delete_repo: 'a GitHub *classic* token scope, named in R-036 to say it is the wrong one',
  null_resource: 'a Terraform concept named in a dated account of what was tried',
  attach_branch_domains: 'a removed resource, named in the entry recording its removal',
  storage_buckets: 'named in SYNC_BACKLOG as something the storage module does not create',
  vercel_target: 'named in ENVIRONMENT_STRATEGY to say it has never existed',
  // A shell variable in NEW_PRODUCT_WALKTHROUGH's curl examples, not a setting
  // the platform has. The credential it holds is a ZITADEL id token copied out
  // of the console's cookie, which no code here names -- so it must stay absent,
  // and a name like this appearing in the code would mean somebody had started
  // storing a staff token.
  STAFF_TOKEN: "a shell variable in a worked example; the platform has no such setting",
  // A name from koras-control-plane, cited by FOLLOW_UPS F7 and F11 as the
  // record of what the first deployment of a generated product found. It must
  // stay absent here: `send_signup_verification` is a Control Plane worker
  // task, and a product repository holding it would mean a boundary had moved.
  //
  // `install_rls` was the third and is no longer exempt. It was described here
  // as a Control Plane engine hook, which it was: the boundary moved on
  // purpose. TS-14 promoted the mechanism -- a `begin` listener that refuses a
  // transaction declaring nothing -- because a product needs it more than the
  // Control Plane does, being the profile with customer tenant tables. The
  // vocabulary did not move with it; `koras_database` carries the guard and the
  // profiles carry their own settings.
  //
  // This test is what noticed. An exemption that stops matching is a line
  // nobody deletes, and the next reader takes it as a description of the
  // system.
  send_signup_verification: 'a Control Plane worker task; named in F7/F11, absent here by design',
  // `self_serve` was exempted beside it as "a column on the Control Plane
  // plans table; no product repository has one". It left the list on
  // 2026-09-08 because the public catalogue now *publishes* the flag and the
  // product reads it -- `canSignUp` in packages/branding decides which
  // pricing card to draw from it -- without owning it: the column, and the
  // decision of what to set it to, are still the platform's.
  // `past_due` was exempted here as "a Control Plane subscription status; a
  // product never decides one". It left the list on 2026-09-06 because the
  // product template now *names* it -- `SubscriptionNotice` renders the
  // sentence for a failed charge -- without deciding it: the platform still
  // resolves the state to no entitlements whether or not the product reads it.
  // This test is what noticed, which is the point of asserting exemptions.
  // The Control Plane's registry tables. REGISTRATION_LIFECYCLE names them
  // because the safety of a single-environment re-registration rests on which
  // of them prune and which do not -- read out of that repository rather than
  // assumed. A product repository must never have them, so asserting their
  // absence here is worth something on its own.
  product_environments: 'a Control Plane registry table; no product repository has one',
  product_services: 'a Control Plane registry table; no product repository has one',
  infrastructure_references: 'a Control Plane registry table; no product repository has one',
  // The commercial catalogue's join table, named in FOLLOW_UPS because the size
  // of the authoring gap is measured in rows of it. Same rule as the three
  // above: it is the Control Plane's, and a product that had one would be
  // deciding its own entitlements.
  plan_entitlements: 'a Control Plane catalogue table; no product repository has one',
  // The billing work, BILLING_DESIGN.md and FOLLOW_UPS F21. Every one of these
  // is the Control Plane's: the two settings are the provider's server-side
  // credentials, which a product must never hold -- since the switch to Stripe
  // on 2026-09-09 the product holds no provider value at all, because the
  // checkout is a hosted URL -- and the rest are columns, tables and states of
  // the subscription record, which is the platform's by the same rule as
  // `past_due` above. A product repository naming any of them would mean the
  // money had moved.
  //
  // `PADDLE_API_KEY`, `PADDLE_WEBHOOK_SECRET` and `custom_data` were exempted
  // here for the same reason until 2026-09-12; they left when the documents
  // stopped naming them, since an exemption nothing cites is a line nobody
  // deletes.
  STRIPE_SECRET_KEY: "the provider's server-side key; the Control Plane holds it, no product does",
  STRIPE_WEBHOOK_SECRET: "the provider's webhook secret; the Control Plane holds it, no product does",
  BILLING_TRIAL_DAYS: 'a Control Plane setting; the trial length is stated on the checkout session',
  managed_payments: "a Stripe Checkout parameter the Control Plane's adapter sends; no product does",
  incomplete_expired: 'a Stripe subscription status the Control Plane maps; a product never decides one',
  billing_customers: 'a Control Plane table; no product repository has one',
  billing_events: 'a Control Plane table; no product repository has one',
  billing_synced_at: 'a column on the Control Plane subscriptions table',
  billing_customer_id: 'a column the design proposed and the build replaced with billing_customers',
  cancelled_at: 'a column on the Control Plane subscriptions table',
  occurred_at: 'a column on the Control Plane billing_events table',
  // ZITADEL instance roles, named in PRODUCT_SIGN_IN.md because finalising an
  // auth request needs the second and the platform's service user held only
  // the first -- found live on 2026-09-11. They are granted in the ZITADEL
  // Console, so no file here carries them; one appearing in the code would
  // mean the membership had started being managed from a repository.
  IAM_OWNER: 'a ZITADEL instance role, granted in the Console rather than by any file here',
  IAM_LOGIN_CLIENT: 'a ZITADEL instance role, granted in the Console rather than by any file here',
}

function tracked(): string[] {
  return execFileSync('git', ['ls-files'], { cwd: ROOT, encoding: 'utf8' })
    .split('\n')
    .filter(Boolean)
}

/**
 * Everything that is not prose: the code, configuration and templates.
 *
 * This file alone is excluded, and only because its exemption map spells out
 * the identifiers it asserts are absent -- scanning itself found
 * `ZITADEL_DEV_SERVICE_TOKEN` in the code and called the exemption stale.
 *
 * Excluding the whole of `tests/docs/` was the first attempt and was wrong:
 * `ABSENT_ON_PURPOSE` and `MOVED` are real symbols in the sibling test, named
 * in R-042, and hiding them made two true references look invented. The
 * exclusion has to be exactly as wide as the self-reference.
 */
function codeText(): string {
  let all = ''
  for (const file of tracked()) {
    if (file.endsWith('.md')) continue
    if (file === 'tests/docs/identifiers.test.ts') continue
    try {
      all += readFileSync(join(ROOT, file), 'utf8')
    } catch {
      // Binary, or gone since `git ls-files` ran. Neither carries identifiers.
    }
  }
  return all
}

function documents(): string[] {
  const docs = readdirSync(join(ROOT, 'docs'))
    .filter((name) => name.endsWith('.md'))
    .map((name) => `docs/${name}`)
  return [...docs, 'CLAUDE.md']
}

const SCREAMING = /^[A-Z][A-Z0-9_]{4,}$/
const SNAKE = /^[a-z][a-z0-9]*(_[a-z0-9]+)+$/
/** A commit SHA is not an identifier, and several are quoted in dated entries. */
const HEX = /^[0-9a-f]{7,40}$/

function identifiers(doc: string): string[] {
  const text = readFileSync(join(ROOT, doc), 'utf8')
  const found = new Set<string>()
  for (const match of text.matchAll(/`([^`\n]+)`/g)) {
    const token = (match[1] as string).trim()
    if (HEX.test(token)) continue
    if (!SCREAMING.test(token) && !SNAKE.test(token)) continue
    found.add(token)
  }
  return [...found].sort()
}

describe('identifiers named in the documentation', () => {
  const code = codeText()

  it('finds identifiers to check', () => {
    // A filter matching nothing would make every case below pass silently --
    // the failure mode of a test that reads text rather than calling code.
    expect(documents().flatMap(identifiers).length).toBeGreaterThan(100)
  })

  it.each(documents())('all exist, in %s', (doc) => {
    const missing = identifiers(doc).filter(
      (name) => !(name in ABSENT_ON_PURPOSE) && !code.includes(name),
    )

    expect(
      missing,
      `${doc} names these and no file outside docs/ contains them. ` +
        'A document describing a plan that was replaced before it was built ' +
        'reads exactly like one describing the system.',
    ).toEqual([])
  })

  it('exempts only identifiers the code really does not contain', () => {
    for (const [name, reason] of Object.entries(ABSENT_ON_PURPOSE)) {
      expect(code.includes(name), `${name} exists now, so "${reason}" is stale`).toBe(false)
    }
  })
})
