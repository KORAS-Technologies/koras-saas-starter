import { z } from 'zod'

/**
 * `.koras/billing-catalogue.yaml` — what a plan is *meant* to cost.
 *
 * The Koras catalogue is the system of record and the provider holds a
 * representation of it; provisioning writes one direction only. This file is
 * the near end of that sentence. It is generator-written with no amounts, so a
 * product that never sells anything carries a catalogue declaring nothing, and
 * the provisioning step refuses it rather than inventing a price.
 *
 * Three things it deliberately is not:
 *
 *  - **Not a source of displayed prices.** Nothing renders this. The provider's
 *    number remains the only one a customer sees or pays, because the provider
 *    is what takes the money and a page rendering this file could disagree with
 *    its own checkout. What these amounts become is
 *    `expected_amount_month`/`_year` on the plan — the *intent* the Control
 *    Plane's `billing.catalogue` check reconciles the provider against.
 *  - **Not a secret.** It holds amounts and a tax code. The provider key lives
 *    in the factory's Doppler and never here; a catalogue is reviewed in a diff
 *    and a credential must not be.
 *  - **Not a two-way sync.** An amount edited in the provider's dashboard is a
 *    finding, not an update. This file is what somebody stated; the check's job
 *    is to notice when the provider stopped agreeing with it.
 */

/** Where the catalogue lives in a generated project. */
export const BILLING_CATALOGUE_PATH = '.koras/billing-catalogue.yaml'

/**
 * The Managed Payments tax code every KORAS product has used so far.
 *
 * `txcd_10103001` — Software as a Service (SaaS), business use. Pinned rather
 * than prompted because a product without an *eligible* code cannot be sold
 * through Managed Payments at all, so this is not a free choice; it is the one
 * that works, recorded where a future product that needs a different one can
 * override it. The eligibility rule is written down in the Control Plane's
 * go-live runbook, step 2.
 */
export const DEFAULT_TAX_CODE = 'txcd_10103001'

/**
 * The largest amount the catalogue will carry, in minor units.
 *
 * 100,000,000 minor units is $1,000,000.00. Not a provider limit — a typo
 * limit. Amounts are in minor units precisely because a fractional currency
 * unit is how a price ends up out by a factor of a hundred, and the mistake
 * that survives review is the one that looks like a plausible number. A plan
 * that genuinely costs more than this is not being sold self-serve.
 */
export const MAX_MINOR_UNITS = 100_000_000

/**
 * A plan code, as the platform spells it.
 *
 * Lowercase, because this is compared against what the Control Plane holds and
 * a catalogue that says `Pro` for a plan stored as `pro` would price nothing
 * and report the plan missing. Validated for shape only: which codes actually
 * exist is the Control Plane's answer, read back at sync time rather than
 * asserted here. Naming its tiers in this repository would be the factory
 * vouching for another repository's schema.
 */
const planCode = z
  .string()
  .regex(/^[a-z][a-z0-9_-]{1,38}$/, 'must be a lowercase code such as `starter` or `pro`')

/**
 * An amount in the currency's minor unit, or `null` for "not sold at a price".
 *
 * `null` is a statement, not an omission — it is how the catalogue says a plan
 * has no monthly price, or is quoted rather than bought. An absent key means
 * the same thing and reads worse, so both are accepted and both produce no
 * price and no intent.
 *
 * Zero is refused. A free plan takes no card, so it needs no price at the
 * provider, and a zero amount is the shape an unset variable takes when it is
 * interpolated into one.
 */
const amount = z
  .number()
  .int('must be a whole number of minor units (900 is $9.00, not 9)')
  .positive('must be greater than zero; use `null` for a plan that is not sold at a price')
  .max(MAX_MINOR_UNITS, `must not exceed ${MAX_MINOR_UNITS} minor units`)
  .nullable()
  .optional()

const planSchema = z
  .object({
    monthly: amount,
    yearly: amount,
  })
  .strict()

/**
 * ISO 4217, lowercase, as the provider spells it in a price.
 *
 * One currency for the whole catalogue rather than one per plan. A plan priced
 * in two currencies and a catalogue mixing them are different things, and the
 * second is almost always a mistake; the first is a later phase, which is why
 * the currency is a segment of the lookup key from the first key rather than
 * added when it is finally needed.
 */
const currency = z
  .string()
  .regex(/^[a-z]{3}$/, 'must be a three-letter ISO 4217 code in lowercase, such as `usd`')

export const billingCatalogueSchema = z
  .object({
    version: z.literal(1),
    currency,
    tax_code: z.string().min(1).default(DEFAULT_TAX_CODE),
    plans: z.record(planCode, planSchema),
  })
  .strict()

export type BillingCatalogue = z.infer<typeof billingCatalogueSchema>

/** One plan's prices, after the shape has been checked and the nulls settled. */
export interface CataloguePlan {
  code: string
  monthly: number | null
  yearly: number | null
}

export interface ParsedCatalogue {
  currency: string
  taxCode: string
  /** Only the plans naming at least one amount. A plan declaring none is not priced. */
  plans: CataloguePlan[]
  /** Plans present in the file with no amount at all, reported so silence is visible. */
  unpriced: string[]
}

export type CatalogueProblem = { detail: string }

export type CatalogueResolution =
  | { ok: true; catalogue: ParsedCatalogue }
  | { ok: false; problem: CatalogueProblem }

/** Renders a zod failure as something an operator can act on, path included. */
function describe(error: z.ZodError, source: string): string {
  const lines = error.issues.map((issue) => {
    const path = issue.path.length > 0 ? issue.path.join('.') : '(root)'
    return `  ${path}: ${issue.message}`
  })
  return `${source} is not a valid billing catalogue:\n${lines.join('\n')}`
}

/**
 * Validates an already-parsed YAML document.
 *
 * Separate from reading the file so a test can supply a document, and so the
 * caller owns the YAML dependency and the file system. Returns a refusal
 * rather than throwing, because every other step in this CLI that talks to an
 * operator does.
 */
export function parseBillingCatalogue(document: unknown, source: string): CatalogueResolution {
  if (document === null || document === undefined) {
    return {
      ok: false,
      problem: {
        detail:
          `${source} is empty. It is written with no amounts on purpose — fill in what each ` +
          'plan costs, in minor units, before provisioning the catalogue.',
      },
    }
  }

  const result = billingCatalogueSchema.safeParse(document)
  if (!result.success) {
    return { ok: false, problem: { detail: describe(result.error, source) } }
  }

  const priced: CataloguePlan[] = []
  const unpriced: string[] = []

  for (const [code, prices] of Object.entries(result.data.plans)) {
    const monthly = prices.monthly ?? null
    const yearly = prices.yearly ?? null
    if (monthly === null && yearly === null) {
      unpriced.push(code)
      continue
    }
    priced.push({ code, monthly, yearly })
  }

  if (priced.length === 0) {
    // The two ways to get here read differently to an operator, and telling
    // them apart is the difference between "you have not filled this in yet"
    // and "you filled it in and every plan says it is not sold".
    const detail =
      unpriced.length === 0
        ? `${source} declares no plans. It is written that way on purpose — a generated ` +
          'product does not know what it costs. Add the plans this product sells, with their ' +
          'amounts in minor units.'
        : `${source} names no priced plan: ${unpriced.join(', ')} ${
            unpriced.length === 1 ? 'is' : 'are'
          } null on both intervals, so there is nothing to create at the provider.`

    return { ok: false, problem: { detail } }
  }

  // Sorted so a run's output, and the order calls go out in, does not depend on
  // key order in a hand-edited file. Two runs of the same catalogue should read
  // identically in a terminal and in a log.
  priced.sort((a, b) => a.code.localeCompare(b.code))
  unpriced.sort((a, b) => a.localeCompare(b))

  return {
    ok: true,
    catalogue: {
      currency: result.data.currency,
      taxCode: result.data.tax_code,
      plans: priced,
      unpriced,
    },
  }
}
