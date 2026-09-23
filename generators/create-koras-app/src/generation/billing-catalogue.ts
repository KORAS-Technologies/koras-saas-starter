import type { GenerationContext } from './context.js'
import { BILLING_CATALOGUE_PATH, DEFAULT_TAX_CODE } from '../billing/catalogue.js'

/**
 * `.koras/billing-catalogue.yaml`, as the generator first writes it.
 *
 * Generator-authored rather than template-authored, for the same reason
 * `.koras/project.yaml` is: every product gets the same shape, so duplicating
 * it into a template would create two things to keep in sync, and its one
 * variable value — the product code — comes from the generation context.
 *
 * **It ships with the platform's standard pricing already in it**, which is a
 * reversal of how it was first written. The first version shipped empty, on the
 * grounds that a generated product does not know what it costs and a file of
 * plausible amounts would be provisioned by whoever ran the command without
 * reading it. That reasoning was right while no standard existed. One was
 * specified on 2026-09-22, and a product that wants the standard should get it
 * by doing nothing, while overriding it should be editing a number.
 *
 * The safety the empty file was buying is bought elsewhere now: the command
 * refuses a live provider key outside production, refuses a plan the Control
 * Plane does not hold, and prints every amount before it creates anything.
 */

export { BILLING_CATALOGUE_PATH }

/**
 * The platform standard, 2026-09-22.
 *
 * Four tiers, two of them self-serve. Amounts in minor units. The user counts
 * are what the flat fee *includes*, never a multiplier: $99 buys the plan and
 * three people, not one person three times.
 *
 * Storage is the platform's current per-tier allowance, restated here so a
 * product can override it in the one place a product overrides anything. It is
 * not yet read — the platform holds one set of limits shared by every product —
 * and the command says so on every run rather than leaving it to be discovered.
 */
const STANDARD_PLANS: Array<{
  code: string
  name: string
  monthly: number
  annual: number
  users: number
  storageGb: number
}> = [
  { code: 'starter', name: 'Starter', monthly: 9_900, annual: 99_000, users: 3, storageGb: 5 },
  // The Professional tier's code is `pro`. A subscription points at a plan row
  // and the platform has renamed a tier once already; three letters did not
  // justify repeating that across every registered product. The name is what a
  // customer sees, and it says Professional.
  { code: 'pro', name: 'Professional', monthly: 19_900, annual: 199_000, users: 10, storageGb: 50 },
  {
    code: 'business',
    name: 'Business',
    monthly: 49_900,
    annual: 499_000,
    users: 25,
    storageGb: 250,
  },
]

/** The standard extra internal user: $25 a month, $250 a year, every tier. */
const STANDARD_ADDITIONAL_USER = { monthly: 2_500, annual: 25_000 }

function planBlock(plan: (typeof STANDARD_PLANS)[number]): string {
  return `  ${plan.code}:
    name: ${plan.name}
    plan_version: 1
    monthly_price_cents: ${plan.monthly}
    annual_price_cents: ${plan.annual}
    included_users: ${plan.users}
    limits:
      storage.files: ${plan.storageGb}
`
}

export function renderBillingCatalogue(ctx: GenerationContext): string {
  return `# The commercial catalogue for ${ctx.projectSlug}.
#
# The platform standard is already in this file. A product that wants it does
# nothing; a product that differs edits a number. Nothing here requires the
# provisioning code to change, which is the point of the file existing.
#
# WHAT THIS IS NOT
#
# Not what a customer is shown or charged. The payment provider holds that,
# because the provider is what takes the money and a page rendering this file
# could disagree with its own checkout. What these amounts become is the plan's
# recorded INTENT, which the platform's reconciliation compares the provider
# against. A plan with no intent is unchecked, not clean.
#
# Not a secret. NO CREDENTIAL BELONGS IN THIS FILE. The provider key lives in
# the factory's own Doppler and is read by the operator running the command.
#
# HOW A PLAN IS PRICED
#
# A plan is a FLAT FEE that INCLUDES a number of internal users. ${STANDARD_PLANS[0].monthly / 100} includes
# ${STANDARD_PLANS[0].users}; it costs the same whether one person uses it or ${STANDARD_PLANS[0].users}. The seat count never
# multiplies the price. A user beyond the included count costs the
# additional_user amount below.
#
# AMOUNTS ARE IN MINOR UNITS, which is why every amount key says so. ${STANDARD_PLANS[0].monthly} is
# ${STANDARD_PLANS[0].monthly / 100}.00, not ${STANDARD_PLANS[0].monthly}.00. A fractional currency unit is how a price ends up
# out by a factor of a hundred, and that mistake survives review because the
# number looks plausible either way.
#
# PROVISION IT with, from the starter:
#
#   pnpm create-koras-app ${ctx.projectSlug} --profile ${ctx.profile} \\
#     --provision-billing --output-dir <where this project is>
#
# Run it AFTER registration and AFTER doppler-bootstrap. Registration is what
# creates the plans this writes onto; bootstrap is what supplies the two
# credentials it needs. Running it twice is free -- the second run finds every
# price already there and changes nothing. Add --dry-run to see the amounts
# before anything is created.
#
# SOME FIELDS BELOW ARE NOT ACTED ON YET. The command lists exactly which, on
# every run. They are here because the schema is meant to be complete: a later
# phase consuming a field should not mean a product re-editing this file.

version: 1
catalogue_version: 1

# ISO 4217, lowercase. One currency for the whole catalogue.
currency: usd

# The Managed Payments tax code. \`${DEFAULT_TAX_CODE}\` is Software as a Service,
# business use. A product without an ELIGIBLE code cannot be sold through
# Managed Payments at all, so change this only if this product genuinely is
# not SaaS.
tax_code: ${DEFAULT_TAX_CODE}

# One internal user beyond a plan's included count. The same for every tier --
# a seat that costs different amounts depending on which plan it hangs off is a
# model nobody asked for and every part of the system would have to carry.
#
# NOTHING BILLS THIS YET, and nothing creates a price for it yet either.
# Charging for the extra user is a second subscription line and is a later
# phase. Until then the included count is a hard cap: the ${STANDARD_PLANS[0].users + 1}th user on
# ${STANDARD_PLANS[0].name} is refused and pointed at ${STANDARD_PLANS[1].name}.
additional_user:
  monthly_price_cents: ${STANDARD_ADDITIONAL_USER.monthly}
  annual_price_cents: ${STANDARD_ADDITIONAL_USER.annual}

# Every plan named here must ALREADY EXIST in the Control Plane, which
# registration creates. A code that does not match one is refused rather than
# created -- a mistyped code would otherwise become a real, priced tier that
# grants nothing.
#
# \`limits\` is an open map keyed by entitlement code, so a ceiling this product
# has and no other -- workflow runs, API calls, connected accounts -- needs no
# schema change to express. Storage is in gigabytes, because the platform's
# storage entitlement is.
plans:
${STANDARD_PLANS.map(planBlock).join('\n')}
  # Negotiated rather than bought, so it carries no price: an amount invented
  # here would be a number a salesperson has to contradict. It is on the
  # catalogue as the tier to ask about.
  enterprise:
    name: Enterprise
    plan_version: 1
    custom: true
`
}
