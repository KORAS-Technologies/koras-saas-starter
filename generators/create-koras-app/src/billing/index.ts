import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import yaml from 'js-yaml'

import { resolveBearer } from '../registration/token.js'
import {
  BILLING_CATALOGUE_PATH,
  declaredButInert,
  parseBillingCatalogue,
  type CataloguePlan,
  type ParsedCatalogue,
} from './catalogue.js'
import { resolveBillingConfig, type BillingConfig, type Environment } from './config.js'
import { priceLookupKey, productLookupKey } from './keys.js'
import { ProviderClient, ProviderError, type FetchLike } from './stripe.js'
import { ControlPlaneError, PlansClient, type PlanRecord } from './plans.js'

/**
 * Catalogue provisioning, as one call the CLI can make and print.
 *
 * The step runs **after** registration and **after** `doppler-bootstrap`, and
 * the order is a dependency rather than a convention: registration is what
 * creates the plans this writes onto, and bootstrap is what puts the two
 * credentials it needs into Doppler. Run earlier, it has nothing to price.
 *
 * It is a one-time operation in the sense that a second run finds everything
 * already there and changes nothing — not in the sense that running it twice
 * is unsafe. Those are different properties, and only the second one is worth
 * having: an operator who cannot tell whether the first run finished will run
 * it again, so the only safe design is one where doing so is free.
 *
 * What it will never do: delete a price, archive one, change an amount at the
 * provider, create a plan that does not already exist, or touch a field of a
 * plan it does not own.
 */

export type BillingSkipReason = 'profile' | 'no-catalogue' | 'not-configured'

export type IntervalOutcome =
  /** The price already existed with this amount. Nothing was created. */
  | { kind: 'reused'; priceId: string; amount: number }
  /** No price carried this lookup key. One was created. */
  | { kind: 'created'; priceId: string; amount: number }
  /**
   * A price existed at a different amount. A provider price is immutable in
   * amount, so a new one was created and the lookup key moved to it. The old
   * price is still there, active and referenced by nothing.
   */
  | {
      kind: 'superseded'
      priceId: string
      amount: number
      previousPriceId: string
      previousAmount: number | null
    }

export interface PlanOutcome {
  code: string
  month?: IntervalOutcome
  year?: IntervalOutcome
  /** True when the Control Plane row already said exactly this. */
  unchanged: boolean
}

export type BillingReport =
  | { kind: 'skipped'; reason: BillingSkipReason; detail: string }
  | {
      kind: 'provisioned'
      environment: Environment
      correlationId: string
      plans: PlanOutcome[]
      /** Plans in the catalogue file declaring no amount at all. */
      unpriced: string[]
      /** Tiers declared negotiated: on the catalogue, deliberately unpriced. */
      custom: string[]
      /** Declared fields nothing acts on yet, printed so inertness is stated. */
      inert: string[]
      /** True when nothing at all was created or written. */
      noop: boolean
    }
  | { kind: 'failed'; detail: string; retryable: boolean; correlationId?: string }
  /** Nothing was sent. What *would* have been done, for `--dry-run`. */
  | { kind: 'planned'; environment: Environment; lines: string[] }

export interface RunBillingOptions {
  /** The project on disk, which holds the catalogue file. */
  projectRoot: string
  /** The product's code, as it is registered with the Control Plane. */
  productCode: string
  /** Whether this profile registers as a product at all. */
  registersAsProduct: boolean
  dryRun: boolean
  urlOverride?: string
  env?: NodeJS.ProcessEnv
  fetchImpl?: FetchLike
  correlationId?: string
  /** Injected for tests; the real clients are built from the resolved config. */
  clients?: {
    provider: ProviderClient
    plans: PlansClient
  }
}

/** Reads and validates the catalogue file, or says why it cannot be used. */
export function loadCatalogue(
  projectRoot: string,
): { ok: true; catalogue: ParsedCatalogue } | { ok: false; missing: boolean; detail: string } {
  const path = join(projectRoot, BILLING_CATALOGUE_PATH)

  if (!existsSync(path)) {
    return {
      ok: false,
      missing: true,
      detail:
        `${BILLING_CATALOGUE_PATH} is not in this project. It is written by the generator for ` +
        'products; a project generated before catalogue provisioning existed will not have one ' +
        `yet. Create it, or re-generate with --refresh ${BILLING_CATALOGUE_PATH}.`,
    }
  }

  let document: unknown
  try {
    document = yaml.load(readFileSync(path, 'utf8'))
  } catch (err) {
    return {
      ok: false,
      missing: false,
      detail: `${BILLING_CATALOGUE_PATH} is not valid YAML: ${String(err)}`,
    }
  }

  const parsed = parseBillingCatalogue(document, BILLING_CATALOGUE_PATH)
  if (!parsed.ok) return { ok: false, missing: false, detail: parsed.problem.detail }

  return { ok: true, catalogue: parsed.catalogue }
}

/** The intervals a plan names an amount for, in a fixed order. */
function intervalsOf(plan: CataloguePlan): Array<{ interval: 'month' | 'year'; amount: number }> {
  const out: Array<{ interval: 'month' | 'year'; amount: number }> = []
  if (plan.monthly !== null) out.push({ interval: 'month', amount: plan.monthly })
  if (plan.yearly !== null) out.push({ interval: 'year', amount: plan.yearly })
  return out
}

/**
 * The provider product id for one plan.
 *
 * Deterministic, so a re-run addresses the same object instead of searching for
 * it. Narrowed to the characters the provider accepts in an id, at the one
 * place the id is built, so a product code carrying a dash cannot produce an id
 * that is refused on creation and then looks absent on every later run.
 */
export function providerProductId(productCode: string, planCode: string): string {
  const key = productLookupKey({ productCode, planCode })
  return `koras_${key.replace(/[^a-z0-9]+/g, '_')}`
}

/**
 * Ensures one interval's price exists at the stated amount.
 *
 * The three outcomes are the three the contract allows, and the third is the
 * one worth reading carefully: a provider price cannot have its amount edited,
 * so "the catalogue says 2900 and the provider says 1900" is resolved by
 * creating a second price and moving the lookup key, never by mutating the
 * first. The superseded price is left active and unreferenced rather than
 * archived, because archiving is a state change on an object holding a
 * commercial record and nothing here needs it gone.
 */
async function ensureInterval(
  provider: ProviderClient,
  input: {
    productCode: string
    planCode: string
    planName: string
    interval: 'month' | 'year'
    amount: number
    currency: string
    taxCode: string
  },
): Promise<IntervalOutcome> {
  const lookupKey = priceLookupKey({
    productCode: input.productCode,
    planCode: input.planCode,
    interval: input.interval,
    currency: input.currency,
  })

  const existing = await provider.findPriceByLookupKey(lookupKey)

  if (
    existing !== null &&
    existing.unitAmount === input.amount &&
    existing.currency === input.currency &&
    existing.interval === input.interval
  ) {
    return { kind: 'reused', priceId: existing.id, amount: input.amount }
  }

  // The product is ensured only once something is actually going to be created
  // under it. A run that changes nothing should make no writes at all, and a
  // product created for a price that turned out to already exist would be one.
  const { product } = await provider.ensureProduct({
    id: providerProductId(input.productCode, input.planCode),
    name: input.planName,
    taxCode: input.taxCode,
    metadata: {
      koras_product: input.productCode,
      koras_plan: input.planCode,
    },
  })

  const created = await provider.createPrice({
    productId: product.id,
    lookupKey,
    unitAmount: input.amount,
    currency: input.currency,
    interval: input.interval,
    // Only when something already holds the key. Sending it unconditionally
    // would be refused on the first create, since there is nothing to transfer.
    transferLookupKey: existing !== null,
    metadata: {
      koras_product: input.productCode,
      koras_plan: input.planCode,
      koras_interval: input.interval,
    },
  })

  if (existing !== null) {
    return {
      kind: 'superseded',
      priceId: created.id,
      amount: input.amount,
      previousPriceId: existing.id,
      previousAmount: existing.unitAmount,
    }
  }

  return { kind: 'created', priceId: created.id, amount: input.amount }
}

/** The plan row to write: the one that was read, with only this step's fields changed. */
export function mergePlan(
  existing: PlanRecord,
  input: {
    currency: string
    month?: IntervalOutcome
    year?: IntervalOutcome
  },
): PlanRecord {
  return {
    // Everything this step does not own is carried through exactly as read.
    // `PUT /plans` overwrites the whole row, so an omission here is a silent
    // reset of somebody else's decision.
    ...existing,
    price_id_month: input.month !== undefined ? input.month.priceId : existing.price_id_month,
    price_id_year: input.year !== undefined ? input.year.priceId : existing.price_id_year,
    expected_amount_month:
      input.month !== undefined ? input.month.amount : existing.expected_amount_month,
    expected_amount_year:
      input.year !== undefined ? input.year.amount : existing.expected_amount_year,
    expected_currency: input.currency,
  }
}

/** Whether writing this row back would change anything at all. */
export function sameRow(a: PlanRecord, b: PlanRecord): boolean {
  return (
    a.price_id_month === b.price_id_month &&
    a.price_id_year === b.price_id_year &&
    a.expected_amount_month === b.expected_amount_month &&
    a.expected_amount_year === b.expected_amount_year &&
    a.expected_currency === b.expected_currency
  )
}

/** What a dry run prints: every call that would go out, and nothing sent. */
function planLines(
  productCode: string,
  catalogue: ParsedCatalogue,
  environment: Environment,
): string[] {
  const lines: string[] = [
    `Target: ${environment}, currency ${catalogue.currency}, tax code ${catalogue.taxCode}, ` +
      `catalogue version ${catalogue.catalogueVersion}`,
  ]

  for (const plan of catalogue.plans) {
    const included =
      plan.includedUsers === null ? '' : `, includes ${plan.includedUsers} internal users`
    lines.push(`  ${plan.name ?? plan.code}${included}`)
    for (const { interval, amount } of intervalsOf(plan)) {
      const key = priceLookupKey({
        productCode,
        planCode: plan.code,
        interval,
        currency: catalogue.currency,
      })
      // The amount is printed in major units beside the minor ones. Reading
      // 99000 and 990.00 together is what catches a factor-of-a-hundred error
      // before it becomes a price somebody is charged; reading either alone is
      // what lets one through.
      lines.push(`    ${key} -> ${amount} (${(amount / 100).toFixed(2)} ${catalogue.currency})`)
    }
  }

  for (const plan of catalogue.custom) {
    lines.push(`  ${plan.name ?? plan.code}: negotiated; no price is created`)
  }

  for (const code of catalogue.unpriced) {
    lines.push(`  ${code}: no amount declared; no price, no intent, plan left alone`)
  }

  const inert = declaredButInert(catalogue)
  if (inert.length > 0) {
    lines.push('', 'Declared in the catalogue and acted on by nothing yet:')
    for (const entry of inert) lines.push(`  - ${entry}`)
  }

  lines.push(
    '',
    'Nothing was sent. A dry run reads nothing from the provider either, so it cannot say ' +
      'which of these already exist.',
  )

  return lines
}

export async function runBillingProvision(options: RunBillingOptions): Promise<BillingReport> {
  if (!options.registersAsProduct) {
    return {
      kind: 'skipped',
      reason: 'profile',
      detail:
        'This profile does not register as a product, so it has no plans and no commercial ' +
        'catalogue. The Control Plane is the authority over other products’ catalogues; ' +
        'it is not a product with one of its own.',
    }
  }

  const catalogue = loadCatalogue(options.projectRoot)
  if (!catalogue.ok) {
    return catalogue.missing
      ? { kind: 'skipped', reason: 'no-catalogue', detail: catalogue.detail }
      : { kind: 'failed', detail: catalogue.detail, retryable: false }
  }

  const resolution = resolveBillingConfig({ urlOverride: options.urlOverride, env: options.env })
  if (!resolution.ok) {
    if (resolution.problem.kind === 'no-base-url') {
      return {
        kind: 'skipped',
        reason: 'not-configured',
        detail:
          'No Control Plane is configured, so there is nothing to sync a catalogue to. This is ' +
          'the documented bootstrap order rather than an error.',
      }
    }
    return { kind: 'failed', detail: resolution.problem.detail, retryable: false }
  }

  const config: BillingConfig = resolution.config

  // Placed after the configuration is resolved, not before. A dry run that
  // skipped the environment guard would report a plan it would refuse to
  // carry out, which is the one thing a rehearsal must not do.
  if (options.dryRun) {
    return {
      kind: 'planned',
      environment: config.environment,
      lines: planLines(options.productCode, catalogue.catalogue, config.environment),
    }
  }

  const bearer = await resolveBearer(
    {
      baseUrl: config.baseUrl,
      credential: config.credential,
      endpoint: '/api/platform/v1/plans',
    },
    // The mint deliberately takes no environment: it signs an assertion from
    // the key already in hand and reads nothing else. Passing one would suggest
    // it could be steered by configuration, which is the last thing a token
    // exchange should be.
    { fetchImpl: options.fetchImpl },
  )

  if (!bearer.ok) {
    return { kind: 'failed', detail: bearer.detail, retryable: bearer.retryable }
  }

  const provider =
    options.clients?.provider ??
    new ProviderClient({
      apiKey: config.providerKey,
      fetchImpl: options.fetchImpl,
      env: options.env,
    })

  const plansClient =
    options.clients?.plans ??
    new PlansClient({
      baseUrl: config.baseUrl,
      token: bearer.config.token,
      fetchImpl: options.fetchImpl,
      correlationId: options.correlationId,
      env: options.env,
    })

  const correlationId = plansClient.correlation

  try {
    const known = await plansClient.listPlans(options.productCode)
    const byCode = new Map(known.map((plan) => [plan.code, plan]))

    // Every unknown code is reported at once rather than one per run. An
    // operator fixing a catalogue wants the whole list, and finding the second
    // typo only after correcting the first is three runs against a real
    // payment account.
    const unknown = catalogue.catalogue.plans
      .map((plan) => plan.code)
      .filter((code) => !byCode.has(code))

    if (unknown.length > 0) {
      return {
        kind: 'failed',
        retryable: false,
        correlationId,
        detail:
          `${BILLING_CATALOGUE_PATH} names ${unknown.length === 1 ? 'a plan' : 'plans'} the ` +
          `Control Plane does not hold for ${options.productCode}: ${unknown.join(', ')}. ` +
          `Known: ${known.map((plan) => plan.code).join(', ') || '(none)'}. ` +
          'Refused rather than created: this endpoint would happily create a plan, and a ' +
          'mistyped code would become a real priced tier granting nothing.',
      }
    }

    const outcomes: PlanOutcome[] = []
    let wroteAnything = false

    for (const plan of catalogue.catalogue.plans) {
      const existing = byCode.get(plan.code)
      if (existing === undefined) continue

      const results: { month?: IntervalOutcome; year?: IntervalOutcome } = {}

      for (const { interval, amount } of intervalsOf(plan)) {
        const outcome = await ensureInterval(provider, {
          productCode: options.productCode,
          planCode: plan.code,
          // The catalogue's name when it states one, the Control Plane's
          // otherwise. The provider product is what a customer sees on an
          // invoice, and "Acme Professional" says more than "Acme Pro" --
          // which is the one place the plan-code decision surfaces.
          planName: plan.name ?? existing.name,
          interval,
          amount,
          currency: catalogue.catalogue.currency,
          taxCode: catalogue.catalogue.taxCode,
        })
        results[interval] = outcome
        if (outcome.kind !== 'reused') wroteAnything = true
      }

      const merged = mergePlan(existing, { currency: catalogue.catalogue.currency, ...results })
      const unchanged = sameRow(existing, merged)

      if (!unchanged) {
        await plansClient.upsertPlan(options.productCode, merged)
        wroteAnything = true
      }

      outcomes.push({ code: plan.code, ...results, unchanged })
    }

    return {
      kind: 'provisioned',
      environment: config.environment,
      correlationId,
      plans: outcomes,
      unpriced: catalogue.catalogue.unpriced,
      custom: catalogue.catalogue.custom.map((plan) => plan.code),
      inert: declaredButInert(catalogue.catalogue),
      noop: !wroteAnything,
    }
  } catch (err) {
    if (err instanceof ProviderError || err instanceof ControlPlaneError) {
      return { kind: 'failed', detail: err.message, retryable: err.retryable, correlationId }
    }
    throw err
  }
}

export { BILLING_CATALOGUE_PATH } from './catalogue.js'
export { PROVIDER_KEY_VAR, BILLING_KEY_VAR, ENVIRONMENT_OVERRIDE_VAR } from './config.js'
export { priceLookupKey, productLookupKey, idempotencyKey } from './keys.js'
