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
import {
  addonLookupKey,
  EXTRA_USER_SEGMENT,
  priceLookupKey,
  productLookupKey,
} from './keys.js'
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

/** What happened to the add-on's two prices. Neither is billed by anything yet. */
export interface AddonOutcome {
  month?: IntervalOutcome
  year?: IntervalOutcome
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
      /** The extra internal user, when the catalogue states one. Billed by nothing. */
      extraUser?: AddonOutcome
      /** How many plans had their terms recorded as a catalogue version. */
      catalogueRecorded: number
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
 * The labels every provider object this command creates carries.
 *
 * A thread back from an object in a payment dashboard to the catalogue entry
 * that asked for it, and to the environment and the registry entry it belongs
 * to. Somebody looking at an unfamiliar price should be able to tell whose it
 * is without asking anybody.
 *
 * **Never an authorization source, and that is the rule rather than a caution.**
 * Metadata is writable by anyone with dashboard access, so a decision made
 * from it is a decision anyone with dashboard access can make. What authorises
 * is the key the call is made with and the environment guard it passed; this
 * only explains.
 *
 * `product_registration_id` is absent when the platform could not be asked for
 * it. One label fewer is better than refusing to price a product because a
 * listing was slow.
 */
function standardMetadata(input: {
  productCode: string
  environment: Environment
  catalogueVersion: number
  registrationId: string | null
  planCode?: string
  planVersion?: number
  interval?: 'month' | 'year'
}): Record<string, string> {
  const metadata: Record<string, string> = {
    platform: 'koras',
    application: input.productCode,
    environment: input.environment,
    catalog_version: String(input.catalogueVersion),
  }
  if (input.registrationId !== null) metadata.product_registration_id = input.registrationId
  if (input.planCode !== undefined) metadata.plan_code = input.planCode
  if (input.planVersion !== undefined) metadata.plan_version = String(input.planVersion)
  if (input.interval !== undefined) metadata.billing_interval = input.interval
  return metadata
}

/**
 * The provider product id for one plan.
 *
 * Deterministic, so a re-run addresses the same object instead of searching for
 * it. Narrowed to the characters the provider accepts in an id, at the one
 * place the id is built, so a product code carrying a dash cannot produce an id
 * that is refused on creation and then looks absent on every later run.
 */
/**
 * The product's name as it reads on an invoice, from its code.
 *
 * **A fallback, not the answer.** The platform holds the product's real name
 * and the caller passes it; this is what a provider product is called when the
 * listing did not carry one, which is a Control Plane older than the field.
 * Title case over the separators: `koras-e2e-shop` reads as `Koras E2E Shop`.
 *
 * Deriving it as the primary source would be a second answer to what a product
 * is called, and the one a customer sees on an invoice is the wrong place for
 * a guess.
 */
export function productDisplayName(productCode: string): string {
  return productCode
    .split(/[-_]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

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
    productId: string
    productName: string
    lookupKey: string
    interval: 'month' | 'year'
    amount: number
    currency: string
    taxCode: string
    metadata: Record<string, string>
  },
): Promise<IntervalOutcome> {
  const lookupKey = input.lookupKey

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
    id: input.productId,
    name: input.productName,
    taxCode: input.taxCode,
    metadata: input.metadata,
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
    metadata: { ...input.metadata, billing_interval: input.interval },
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
    /**
     * What the catalogue says the flat fee includes. Absent leaves the plan's
     * own value alone: a catalogue that states nothing is not a catalogue
     * stating zero, and the platform's seeded default is a decision this
     * command has no reason to overrule.
     */
    includedUsers?: number | null
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
    included_users:
      input.includedUsers === undefined || input.includedUsers === null
        ? existing.included_users
        : input.includedUsers,
  }
}

/**
 * Whether the recorded terms already say exactly this.
 *
 * Compared field by field against what would be sent rather than by a digest,
 * so that a field added to the record and forgotten here shows up as a run
 * that always writes -- which is noisy and visible -- instead of one that
 * never does, which is silent.
 */
export function sameTerms(
  recorded: Record<string, unknown> | null,
  terms: {
    planVersion: number
    catalogueVersion: number
    amountMonth: number | null
    amountYear: number | null
    currency: string
    includedUsers: number | null
    priceIdMonth: string | null
    priceIdYear: string | null
    extraUserAmountMonth: number | null
    extraUserAmountYear: number | null
    extraUserPriceIdMonth: string | null
    extraUserPriceIdYear: string | null
    limits: Record<string, number>
  },
): boolean {
  if (recorded === null) return false

  const asNumber = (value: unknown): number | null =>
    value === null || value === undefined ? null : Number(value)
  const asString = (value: unknown): string | null =>
    value === null || value === undefined ? null : String(value)

  return (
    asNumber(recorded.plan_version) === terms.planVersion &&
    asNumber(recorded.catalogue_version) === terms.catalogueVersion &&
    asNumber(recorded.amount_month) === terms.amountMonth &&
    asNumber(recorded.amount_year) === terms.amountYear &&
    asString(recorded.currency) === terms.currency &&
    asNumber(recorded.included_users) === terms.includedUsers &&
    asString(recorded.price_id_month) === terms.priceIdMonth &&
    asString(recorded.price_id_year) === terms.priceIdYear &&
    asNumber(recorded.extra_user_amount_month) === terms.extraUserAmountMonth &&
    asNumber(recorded.extra_user_amount_year) === terms.extraUserAmountYear &&
    asString(recorded.extra_user_price_id_month) === terms.extraUserPriceIdMonth &&
    asString(recorded.extra_user_price_id_year) === terms.extraUserPriceIdYear &&
    JSON.stringify(recorded.limits ?? {}) === JSON.stringify(terms.limits)
  )
}

/** Whether writing this row back would change anything at all. */
export function sameRow(a: PlanRecord, b: PlanRecord): boolean {
  return (
    a.price_id_month === b.price_id_month &&
    a.price_id_year === b.price_id_year &&
    a.expected_amount_month === b.expected_amount_month &&
    a.expected_amount_year === b.expected_amount_year &&
    a.expected_currency === b.expected_currency &&
    a.included_users === b.included_users
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

  if (catalogue.additionalUser !== null) {
    lines.push('  Additional internal user — created, and billed by nothing yet')
    for (const interval of ['month', 'year'] as const) {
      const amount = interval === 'month'
        ? catalogue.additionalUser.monthly
        : catalogue.additionalUser.yearly
      if (amount === null) continue
      const key = addonLookupKey({
        productCode,
        addonCode: EXTRA_USER_SEGMENT,
        interval,
        currency: catalogue.currency,
      })
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

    // Asked once and reused. It is the same answer for every plan, and a
    // listing per price would be a call per price for a label.
    const registrationId = await plansClient.productId(options.productCode)

    const outcomes: PlanOutcome[] = []
    // Held so the catalogue can be recorded after the extra seat's prices
    // exist: a version naming an extra-user price that was never created
    // would be a record of terms nobody can be charged on.
    const priced = new Map<
      string,
      { plan: CataloguePlan; results: { month?: IntervalOutcome; year?: IntervalOutcome } }
    >()
    let wroteAnything = false

    for (const plan of catalogue.catalogue.plans) {
      const existing = byCode.get(plan.code)
      if (existing === undefined) continue

      // The catalogue's name when it states one, the Control Plane's
      // otherwise. The provider product is what a customer sees on an
      // invoice, and "Acme Professional" says more than "Acme Pro" -- which
      // is the one place the plan-code decision is visible to a customer.
      const displayName = plan.name ?? existing.name
      const productName = existing.product_name ?? productDisplayName(options.productCode)
      const metadata = standardMetadata({
        productCode: options.productCode,
        environment: config.environment,
        catalogueVersion: catalogue.catalogue.catalogueVersion,
        registrationId,
        planCode: plan.code,
        planVersion: plan.planVersion,
      })

      const results: { month?: IntervalOutcome; year?: IntervalOutcome } = {}

      for (const { interval, amount } of intervalsOf(plan)) {
        const outcome = await ensureInterval(provider, {
          productId: providerProductId(options.productCode, plan.code),
          productName: `${productName} ${displayName}`,
          lookupKey: priceLookupKey({
            productCode: options.productCode,
            planCode: plan.code,
            interval,
            currency: catalogue.catalogue.currency,
          }),
          interval,
          amount,
          currency: catalogue.catalogue.currency,
          taxCode: catalogue.catalogue.taxCode,
          metadata,
        })
        results[interval] = outcome
        if (outcome.kind !== 'reused') wroteAnything = true
      }

      const merged = mergePlan(existing, {
        currency: catalogue.catalogue.currency,
        includedUsers: plan.includedUsers,
        ...results,
      })
      const unchanged = sameRow(existing, merged)

      if (!unchanged) {
        await plansClient.upsertPlan(options.productCode, merged)
        wroteAnything = true
      }

      outcomes.push({ code: plan.code, ...results, unchanged })
      priced.set(plan.code, { plan, results })
    }

    // ── the extra internal user ───────────────────────────────────────────
    //
    // Created here and billed by nothing. The extra seat is a second
    // subscription line and that is a later phase; what this buys now is that
    // the lookup keys are reserved and the later phase has nothing to
    // provision. An unused price sits in an account costing nothing and
    // misleading no customer -- unlike an unused control on a page, which is
    // the distinction that makes this acceptable rather than the failure this
    // repository keeps recording. The report says so on every run.
    let extraUser: AddonOutcome | undefined
    if (catalogue.catalogue.additionalUser !== null) {
      const extra = catalogue.catalogue.additionalUser
      // Any plan's row carries the product's name; they all name the same
      // product. Falls back to the derived name only when nothing did.
      const extraUserProductName =
        known.find((row) => row.product_name !== null)?.product_name ??
        productDisplayName(options.productCode)
      const metadata = standardMetadata({
        productCode: options.productCode,
        environment: config.environment,
        catalogueVersion: catalogue.catalogue.catalogueVersion,
        registrationId,
      })
      const results: { month?: IntervalOutcome; year?: IntervalOutcome } = {}

      for (const interval of ['month', 'year'] as const) {
        const amount = interval === 'month' ? extra.monthly : extra.yearly
        if (amount === null) continue
        const outcome = await ensureInterval(provider, {
          productId: providerProductId(options.productCode, EXTRA_USER_SEGMENT),
          productName: `${extraUserProductName} Additional Internal User`,
          lookupKey: addonLookupKey({
            productCode: options.productCode,
            addonCode: EXTRA_USER_SEGMENT,
            interval,
            currency: catalogue.catalogue.currency,
          }),
          interval,
          amount,
          currency: catalogue.catalogue.currency,
          taxCode: catalogue.catalogue.taxCode,
          metadata: { ...metadata, addon: EXTRA_USER_SEGMENT },
        })
        results[interval] = outcome
        if (outcome.kind !== 'reused') wroteAnything = true
      }

      // Nothing is written to the Control Plane for it. There is no column to
      // hold an add-on price, and inventing one here would be the factory
      // deciding another repository's schema.
      if (results.month !== undefined || results.year !== undefined) {
        extraUser = { ...results }
      }
    }

    // ── the record of what was sold ──────────────────────────────────────
    //
    // Last, and that ordering is the point. Every price this version names --
    // the plan's and the extra seat's -- exists by now, so a recorded version
    // never names one that failed to be created.
    let catalogueRecorded = 0
    for (const [code, entry] of priced) {
      const terms = {
        productCode: options.productCode,
        planCode: code,
        planVersion: entry.plan.planVersion,
        catalogueVersion: catalogue.catalogue.catalogueVersion,
        amountMonth: entry.plan.monthly,
        amountYear: entry.plan.yearly,
        currency: catalogue.catalogue.currency,
        includedUsers: entry.plan.includedUsers,
        priceIdMonth: entry.results.month?.priceId ?? null,
        priceIdYear: entry.results.year?.priceId ?? null,
        extraUserAmountMonth: catalogue.catalogue.additionalUser?.monthly ?? null,
        extraUserAmountYear: catalogue.catalogue.additionalUser?.yearly ?? null,
        extraUserPriceIdMonth: extraUser?.month?.priceId ?? null,
        extraUserPriceIdYear: extraUser?.year?.priceId ?? null,
        limits: entry.plan.limits,
      }

      // Read, compare, skip -- the same shape as the plan row above. A run
      // that changes nothing must write nothing, literally rather than
      // harmlessly: the moment "writes nothing" becomes "writes something
      // idempotent", nobody can tell a quiet run from a busy one.
      const current = await plansClient.currentCatalogue(options.productCode, code)
      if (sameTerms(current, terms)) continue

      await plansClient.recordCatalogue(terms)
      catalogueRecorded += 1
      wroteAnything = true
    }

    return {
      kind: 'provisioned',
      environment: config.environment,
      correlationId,
      catalogueRecorded,
      plans: outcomes,
      extraUser,
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
