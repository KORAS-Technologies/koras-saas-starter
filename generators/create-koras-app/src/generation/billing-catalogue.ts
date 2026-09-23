import type { GenerationContext } from './context.js'
import { BILLING_CATALOGUE_PATH, DEFAULT_TAX_CODE } from '../billing/catalogue.js'

/**
 * `.koras/billing-catalogue.yaml`, as the generator first writes it.
 *
 * Generator-authored rather than template-authored, for the same reason
 * `.koras/project.yaml` is: every product gets the same shape, so duplicating
 * it into a template would create two things to keep in sync, and its one
 * variable value — the product code in the header — comes from the generation
 * context rather than from template data.
 *
 * **It is written with every amount null**, and that is the design rather than
 * a placeholder nobody got round to filling in. A generated product does not
 * know what it costs; somebody decides that, and the decision belongs in a
 * diff. A file shipped with plausible amounts would be provisioned by the first
 * operator who ran the step without reading it, and the prices would be real.
 *
 * `--provision-billing` refuses a catalogue in this state, saying so.
 */

export { BILLING_CATALOGUE_PATH }

export function renderBillingCatalogue(ctx: GenerationContext): string {
  return `# The commercial catalogue for ${ctx.projectSlug}.
#
# What each plan is MEANT to cost. Nothing here is displayed to a customer and
# nothing here charges anybody: the payment provider holds the amount that is
# shown and taken, because the provider is what takes the money and a page
# rendering this file could disagree with its own checkout.
#
# What these amounts become is the plan's recorded *intent* in the Control
# Plane, which the platform's \`billing.catalogue\` reconciliation check compares
# the provider against. A plan with no intent is unchecked, not clean -- an
# expectation nobody stated is not a fact about a price. That is the whole
# reason to fill this in even for a plan whose price already exists.
#
# Provision it with, from the starter:
#
#   pnpm create-koras-app ${ctx.projectSlug} --profile ${ctx.profile} \\
#     --provision-billing --output-dir <where this project is>
#
# Run it AFTER registration and AFTER doppler-bootstrap. Registration is what
# creates the plans this writes onto; bootstrap is what supplies the two
# credentials it needs. Running it twice is free -- the second run finds every
# price already there and changes nothing.
#
# NO CREDENTIAL BELONGS IN THIS FILE. The provider key lives in the factory's
# own Doppler and is read by the operator running the command. A catalogue is
# reviewed in a diff; a secret must not be.

version: 1

# ISO 4217, lowercase. One currency for the whole catalogue: a catalogue mixing
# them is almost always a mistake, and a second currency is an addition to the
# price lookup keys rather than a change to them.
currency: usd

# The Managed Payments tax code. \`${DEFAULT_TAX_CODE}\` is Software as a Service,
# business use, and is what every KORAS product has used so far. A product
# without an ELIGIBLE code cannot be sold through Managed Payments at all, so
# change this only if this product genuinely is not SaaS.
tax_code: ${DEFAULT_TAX_CODE}

# Amounts are in MINOR UNITS. 900 is $9.00, not $900.00. Minor units because a
# fractional currency unit is how a price ends up out by a factor of a hundred,
# and the version of that mistake which survives review is the one that looks
# like a plausible number.
#
# \`null\` is a statement: this plan is not sold at this interval. Use it for a
# free tier, and for a tier that is quoted rather than bought. A plan with null
# on both intervals gets no price and no intent, and its Control Plane row is
# left entirely alone.
#
# Every plan named here must ALREADY EXIST in the Control Plane, which
# registration creates. A code that does not match one is refused rather than
# created -- a mistyped code would otherwise become a real, priced tier that
# grants nothing.
plans: {}

# Fill in the plans this product sells, for example:
#
# plans:
#   starter:
#     monthly: 900
#     yearly: 9000
#   pro:
#     monthly: 2900
#     yearly: 29000
#   business:
#     monthly: null    # quoted, not bought
#     yearly: null
`
}
