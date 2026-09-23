import { z } from 'zod'

/**
 * `.koras/billing-catalogue.yaml` — what a plan costs and what it includes.
 *
 * The Koras catalogue is the system of record and the provider holds a
 * representation of it; provisioning writes one direction only. This file is
 * the near end of that sentence, and the standard every KORAS product inherits
 * and may override without any provisioning code changing.
 *
 * Three things it deliberately is not:
 *
 *  - **Not a source of displayed prices.** Nothing renders this. The provider's
 *    number remains the only one a customer sees or pays, because the provider
 *    is what takes the money and a page rendering this file could disagree with
 *    its own checkout. What these amounts become is the plan's recorded
 *    *intent*, which the platform's reconciliation compares the provider
 *    against.
 *  - **Not a secret.** It holds amounts, a tax code and limits. The provider
 *    key lives in the factory's Doppler and never here; a catalogue is reviewed
 *    in a diff and a credential must not be.
 *  - **Not a two-way sync.** An amount edited in the provider's dashboard is a
 *    finding, not an update. This file is what somebody stated; the check's job
 *    is to notice when the provider stopped agreeing with it.
 *
 * **A plan is a flat fee that includes a number of users.** $99 includes three;
 * the fourth costs extra. The seat count never multiplies the plan's price, and
 * anything sending it to the provider as a subscription quantity is a bug. See
 * `docs/platform/billing-catalogue-standard.md`, whose Phase 2 is the
 * correction and whose Phase 5 is the extra seat.
 *
 * **Several fields are declared here before anything acts on them**, which is
 * the arrangement this repository has been bitten by before — settings drawn on
 * a page and honoured by nothing. The defence is that the provisioning command
 * says, every run, exactly which declared fields it did not act on. A field
 * whose inertness is printed is not a promise; one whose inertness is inferred
 * is.
 */

/** Where the catalogue lives in a generated project. */
export const BILLING_CATALOGUE_PATH = '.koras/billing-catalogue.yaml'

/**
 * The Managed Payments tax code every KORAS product has used so far.
 *
 * `txcd_10103001` — Software as a Service (SaaS), business use. Pinned rather
 * than prompted because a product without an *eligible* code cannot be sold
 * through Managed Payments at all, so this is not a free choice; it is the one
 * that works, recorded where a future product that is genuinely not SaaS can
 * override it.
 */
export const DEFAULT_TAX_CODE = 'txcd_10103001'

/**
 * The largest amount the catalogue will carry, in minor units.
 *
 * 100,000,000 minor units is $1,000,000.00. Not a provider limit — a typo
 * limit. Amounts are in minor units, and the field names say so, precisely
 * because a fractional currency unit is how a price ends up out by a factor of
 * a hundred: 99 is either $99 or 99 cents depending on a convention the reader
 * has to know, and the version of that mistake which survives review is the one
 * that looks like a plausible number.
 */
export const MAX_MINOR_UNITS = 100_000_000

/** The most users a plan may include. A typo limit again, not a product one. */
export const MAX_INCLUDED_USERS = 100_000

/**
 * A plan code, as the platform spells it.
 *
 * Lowercase, because this is compared against what the Control Plane holds and
 * a catalogue that says `Pro` for a plan stored as `pro` would price nothing
 * and report the plan missing. Validated for shape only: which codes actually
 * exist is the Control Plane's answer, read back at sync time rather than
 * asserted here. Naming its tiers in this repository would be the factory
 * vouching for another repository's schema.
 *
 * **The Professional tier's code is `pro`.** Decided 2026-09-22: a subscription
 * points at a plan row and the platform has renamed a tier once already, so
 * three letters did not justify repeating that across every registered product.
 * The display name is what a customer sees, and it says Professional.
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
const minorUnits = z
  .number()
  .int('must be a whole number of minor units (9900 is $99.00)')
  .positive('must be greater than zero; use `null` for a plan that is not sold at a price')
  .max(MAX_MINOR_UNITS, `must not exceed ${MAX_MINOR_UNITS} minor units`)
  .nullable()
  .optional()

/**
 * A limit the plan includes, by entitlement code.
 *
 * An open map rather than fixed keys, so a product with a ceiling nobody
 * anticipated — workflow runs, API calls, connected accounts — does not need a
 * schema change to express it. That is the requirement stated most plainly in
 * the brief: a different product must not mean different provisioning code.
 *
 * The unit belongs to the entitlement, not to this file. Storage is in
 * gigabytes because the platform's storage entitlement is; a limit added
 * tomorrow carries whatever unit its own entitlement declares.
 */
const limits = z
  .record(
    z.string().regex(/^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$/, 'must be an entitlement code'),
    z.number().int().nonnegative(),
  )
  .optional()

/**
 * Entitlement codes this plan grants beyond the platform's own defaults.
 *
 * The platform already grants a set per tier, seeded at registration. This is
 * how a product adds its own — a module, an integration, a capability that only
 * it has — without that list being hardcoded anywhere in the factory.
 */
const entitlements = z
  .array(z.string().regex(/^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$/, 'must be an entitlement code'))
  .optional()

/**
 * A priced tier.
 *
 * `strict`, so a key nobody recognises is refused rather than dropped. A
 * `monthly_price_cents` misspelt as `monthly_price` would otherwise be silently
 * ignored and the plan provisioned with no price at all — which looks exactly
 * like a plan deliberately not sold monthly.
 */
const pricedPlan = z
  .object({
    /** What a customer sees. The code is the identifier; this is display text. */
    name: z.string().min(1).optional(),
    /**
     * Which version of this plan's commercial terms these are.
     *
     * Bumped when an amount or an included count changes, so a later catalogue
     * row can be effective from a date while the previous one stays readable.
     * Nothing consumes it before the Control Plane catalogue table exists, and
     * the provisioning command says so on every run.
     */
    plan_version: z.number().int().positive().optional(),
    monthly_price_cents: minorUnits,
    annual_price_cents: minorUnits,
    /**
     * Internal users the flat fee includes.
     *
     * Not a quantity multiplier. A plan at 9900 including three costs 9900
     * whether one person uses it or three.
     */
    included_users: z
      .number()
      .int('must be a whole number of users')
      .positive('must be at least one; a plan including nobody cannot be used')
      .max(MAX_INCLUDED_USERS)
      .optional(),
    limits,
    entitlements,
  })
  .strict()

/**
 * A tier that is negotiated rather than bought.
 *
 * Declared so that it appears on a catalogue as the tier to ask about, and
 * produces no price: a price nobody can buy would be a catalogue entry that
 * misleads, and an Enterprise amount invented here would be a number a
 * salesperson has to contradict.
 */
const customPlan = z
  .object({
    name: z.string().min(1).optional(),
    plan_version: z.number().int().positive().optional(),
    custom: z.literal(true),
    limits,
    entitlements,
  })
  .strict()

const planSchema = z.union([customPlan, pricedPlan])

/**
 * ISO 4217, lowercase, as the provider spells it in a price.
 *
 * One currency for the whole catalogue rather than one per plan. A plan priced
 * in two currencies and a catalogue mixing them are different things, and the
 * second is almost always a mistake; the first would be a second catalogue,
 * which is an addition rather than a change to this one.
 */
const currency = z
  .string()
  .regex(/^[a-z]{3}$/, 'must be a three-letter ISO 4217 code in lowercase, such as `usd`')

/**
 * What one internal user beyond a plan's included count costs.
 *
 * The platform standard is 2500 a month and 25000 a year, the same for every
 * tier, which is what makes it a standard rather than a per-plan number. A
 * product may override it; a plan may not, because a seat costing different
 * amounts depending on which tier it is attached to is a pricing model nobody
 * has asked for and every part of the system would have to carry.
 *
 * **Nothing bills this yet.** The extra seat is a second subscription line and
 * that is Phase 5; until it exists the included count is a hard cap. The prices
 * are still created, so the lookup keys are reserved and Phase 5 has nothing to
 * provision, and the command says on every run that nothing charges them.
 */
const additionalUser = z
  .object({
    monthly_price_cents: minorUnits,
    annual_price_cents: minorUnits,
  })
  .strict()
  .optional()

export const billingCatalogueSchema = z
  .object({
    /** The schema's own version, so this file can change shape later. */
    version: z.literal(1),
    /**
     * Which revision of *this product's* commercial terms the file describes.
     *
     * Distinct from `version` above, which is the schema's. Bumped when the
     * catalogue's contents change, so a provisioned estate can be asked which
     * revision it holds.
     */
    catalogue_version: z.number().int().positive().default(1),
    currency,
    tax_code: z.string().min(1).default(DEFAULT_TAX_CODE),
    additional_user: additionalUser,
    plans: z.record(planCode, planSchema),
  })
  .strict()

export type BillingCatalogue = z.infer<typeof billingCatalogueSchema>

/** One plan, after the shape has been checked and the nulls settled. */
export interface CataloguePlan {
  code: string
  /** Display text, when the catalogue states one. The Control Plane's name wins otherwise. */
  name: string | null
  planVersion: number
  monthly: number | null
  yearly: number | null
  includedUsers: number | null
  limits: Record<string, number>
  entitlements: string[]
}

/** A tier declared as negotiated. Carried so a report can say it was seen and skipped. */
export interface CustomPlan {
  code: string
  name: string | null
}

export interface AdditionalUser {
  monthly: number | null
  yearly: number | null
}

export interface ParsedCatalogue {
  catalogueVersion: number
  currency: string
  taxCode: string
  /** Only the plans naming at least one amount. A plan declaring none is not priced. */
  plans: CataloguePlan[]
  /** Tiers declared custom: on the catalogue, deliberately without a price. */
  custom: CustomPlan[]
  /** Plans present in the file with no amount and no custom flag, so nothing to do. */
  unpriced: string[]
  /** The standard extra seat, when the file states one. */
  additionalUser: AdditionalUser | null
}

export type CatalogueProblem = { detail: string }

export type CatalogueResolution =
  | { ok: true; catalogue: ParsedCatalogue }
  | { ok: false; problem: CatalogueProblem }

/** Renders a zod failure as something an operator can act on, path included. */
function describe(error: z.ZodError, source: string): string {
  // A union failure reports every branch, which for a plan means the reader is
  // told both that `custom` must be true and that the price is wrong. Only the
  // priced branch is worth showing unless `custom` was actually attempted, and
  // deduplicating by path is what keeps the message readable.
  const seen = new Set<string>()
  const lines: string[] = []

  for (const issue of error.issues) {
    const path = issue.path.length > 0 ? issue.path.join('.') : '(root)'
    const line = `  ${path}: ${issue.message}`
    if (seen.has(line)) continue
    seen.add(line)
    lines.push(line)
  }

  return `${source} is not a valid billing catalogue:\n${lines.join('\n')}`
}

function isCustom(plan: z.infer<typeof planSchema>): plan is z.infer<typeof customPlan> {
  return 'custom' in plan && plan.custom === true
}

export function parseBillingCatalogue(document: unknown, source: string): CatalogueResolution {
  if (document === null || document === undefined) {
    return {
      ok: false,
      problem: {
        detail:
          `${source} is empty. It ships with the platform's standard pricing already in it, ` +
          'so an empty file means it was replaced rather than edited.',
      },
    }
  }

  const result = billingCatalogueSchema.safeParse(document)
  if (!result.success) {
    return { ok: false, problem: { detail: describe(result.error, source) } }
  }

  const priced: CataloguePlan[] = []
  const custom: CustomPlan[] = []
  const unpriced: string[] = []

  for (const [code, plan] of Object.entries(result.data.plans)) {
    if (isCustom(plan)) {
      custom.push({ code, name: plan.name ?? null })
      continue
    }

    const monthly = plan.monthly_price_cents ?? null
    const yearly = plan.annual_price_cents ?? null

    if (monthly === null && yearly === null) {
      unpriced.push(code)
      continue
    }

    priced.push({
      code,
      name: plan.name ?? null,
      planVersion: plan.plan_version ?? 1,
      monthly,
      yearly,
      includedUsers: plan.included_users ?? null,
      limits: plan.limits ?? {},
      entitlements: plan.entitlements ?? [],
    })
  }

  if (priced.length === 0) {
    // Three ways to get here, and they read differently to an operator. Telling
    // them apart is the difference between "this was gutted", "every tier is
    // negotiated" and "you set them all to null".
    const detail =
      Object.keys(result.data.plans).length === 0
        ? `${source} declares no plans. It ships with the platform's standard pricing already ` +
          'in it, so an empty plan list means it was emptied rather than overridden.'
        : unpriced.length === 0
          ? `${source} declares only negotiated tiers (${custom
              .map((plan) => plan.code)
              .join(', ')}). There is no price to create, and a product sold only by ` +
            'conversation needs no provisioned catalogue.'
          : `${source} names no priced plan: ${unpriced.join(', ')} ${
              unpriced.length === 1 ? 'is' : 'are'
            } null on both intervals, so there is nothing to create at the provider.`

    return { ok: false, problem: { detail } }
  }

  // Sorted so a run's output, and the order calls go out in, does not depend on
  // key order in a hand-edited file. Two runs of the same catalogue should read
  // identically in a terminal and in a log.
  priced.sort((a, b) => a.code.localeCompare(b.code))
  custom.sort((a, b) => a.code.localeCompare(b.code))
  unpriced.sort((a, b) => a.localeCompare(b))

  const extra = result.data.additional_user
  const additionalUser =
    extra === undefined || (extra.monthly_price_cents == null && extra.annual_price_cents == null)
      ? null
      : {
          monthly: extra.monthly_price_cents ?? null,
          yearly: extra.annual_price_cents ?? null,
        }

  return {
    ok: true,
    catalogue: {
      catalogueVersion: result.data.catalogue_version,
      currency: result.data.currency,
      taxCode: result.data.tax_code,
      plans: priced,
      custom,
      unpriced,
      additionalUser,
    },
  }
}

/**
 * Which declared fields nothing has acted on yet.
 *
 * Printed by the provisioning command on every run, and that is the whole
 * point. This repository has twice shipped a declaration that looked live and
 * was inert -- settings rendered on a preferences page and honoured by nothing,
 * found four days apart in two features -- and the rule it produced is that a
 * control which changes nothing is worse than one not offered.
 *
 * A configuration file is not a control, and the phases that consume these
 * fields are named and ordered rather than hypothetical. What makes that
 * acceptable rather than the same mistake again is that the inertness is
 * *stated on every run* instead of being something a reader has to infer from
 * the absence of an effect.
 */
export function declaredButInert(catalogue: ParsedCatalogue): string[] {
  const inert: string[] = []

  if (catalogue.plans.some((plan) => plan.includedUsers !== null)) {
    inert.push(
      'included_users — declared, and not yet enforced anywhere. Until the flat-fee ' +
        'correction ships, the seat count multiplies the plan price and limits nothing',
    )
  }

  if (catalogue.plans.some((plan) => Object.keys(plan.limits).length > 0)) {
    inert.push(
      'limits — declared per plan, and not yet synced. The platform holds one set of ' +
        'limits shared by every product, so a per-product value has nowhere to go yet',
    )
  }

  if (catalogue.plans.some((plan) => plan.entitlements.length > 0)) {
    inert.push('entitlements — declared, and not yet synced to the platform catalogue')
  }

  if (catalogue.plans.some((plan) => plan.planVersion !== 1) || catalogue.catalogueVersion !== 1) {
    inert.push(
      'plan_version and catalogue_version — recorded, and not yet stored. Nothing can ' +
        'answer which revision a customer agreed to until the catalogue table exists',
    )
  }

  if (catalogue.additionalUser !== null) {
    inert.push(
      'additional_user — declared, and no price is created for it yet. When one is, ' +
        'nothing will bill it either: the extra seat is a second subscription line and ' +
        'is a later phase. The included count is a hard cap until then',
    )
  }

  return inert
}
