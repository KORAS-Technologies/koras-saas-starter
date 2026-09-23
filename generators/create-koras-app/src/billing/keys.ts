import { createHash } from 'node:crypto'

/**
 * The two derived strings that make catalogue provisioning safe to re-run.
 *
 * They answer different questions and must not be confused:
 *
 *  - A **lookup key** identifies a price *at the provider*, forever. It is how
 *    a second run finds the price the first run created instead of creating
 *    another one. It is stored on the price and is visible in a dashboard.
 *  - An **idempotency key** identifies one *attempt* to make a call. It is how
 *    a retried HTTP request — a timeout where the call actually landed — does
 *    not produce a second object. It is sent in a header and lives 24 hours.
 *
 * Using one for the other is the mistake worth guarding against. A lookup key
 * as an idempotency key would make a legitimate second call a no-op replay of
 * the first; an idempotency key as a lookup key would change on every run and
 * make every run create a new price.
 */

/**
 * **The lookup key implements a contract the Control Plane owns.**
 *
 * The platform wrote the key's shape before anything minted one, so that it
 * would be decided by the catalogue rather than shaped by the first thing to
 * use it. The factory mints keys; the platform reads them; both have to agree,
 * and the platform is the authority.
 *
 * It is reimplemented here rather than imported because that one is Python and
 * this is TypeScript, and there is no seam between them. **That makes it two
 * answers to one question**, which is the arrangement this estate has been
 * bitten by before — so the tests pin the exact expected strings rather than
 * reproducing the rule, since a test that recomputed it would drift in the
 * same direction as the code and agree with itself forever.
 *
 * The shape, for a reader who does not have the other repository open:
 *
 *   product, plan, interval, currency — joined by underscores
 *
 * Underscores separate segments and hyphens are allowed **inside** one, so a
 * product named with hyphens keeps its own name and the four parts stay
 * unambiguous to anything that splits on an underscore. That is why the extra
 * seat below is one hyphenated word rather than two underscored ones.
 *
 * The interval reads as a word a person recognises in a dashboard — the
 * catalogue and the provider both say month, a key says monthly — and the
 * currency is present from the first key, so that a second currency is an
 * addition rather than a re-key of every price that exists.
 */

/** How an interval reads in a key. The provider says `month`; a key says `monthly`. */
const INTERVAL_WORDS: Record<string, string> = { month: 'monthly', year: 'yearly' }

/**
 * One segment's shape: lower-case alphanumeric, hyphens allowed inside.
 *
 * No underscores, because the underscore is the separator. A segment carrying
 * one would make the key ambiguous to anything that splits on it — which is
 * everything that reads a key, including a person.
 */
const SEGMENT = /^[a-z0-9][a-z0-9-]*$/

/**
 * The add-on's segment, for a price that is not a plan.
 *
 * Hyphenated rather than underscored for the reason above: two underscored
 * words would be two segments where one is meant, and a key with five parts
 * where four are expected is one nothing can parse.
 */
export const EXTRA_USER_SEGMENT = 'extra-user'

export class LookupKeyError extends Error {
  constructor(segment: string, value: string) {
    super(
      `a lookup key's ${segment} segment must be lower-case alphanumeric, ` +
        `hyphens allowed inside: got "${value}"`,
    )
    this.name = 'LookupKeyError'
  }
}

function segment(name: string, value: string): string {
  const cleaned = value.trim().toLowerCase()
  if (!SEGMENT.test(cleaned)) throw new LookupKeyError(name, value)
  return cleaned
}

/**
 * A price's permanent name: product, plan, interval, currency.
 *
 * Deterministic and readable on purpose. It is read by a person in a provider
 * dashboard trying to work out which plan a price belongs to, and it is the
 * only thing tying an opaque provider id back to the catalogue that asked for
 * it. Computable from what the catalogue already knows, so it is the same key
 * next year and in the next environment.
 */
export function priceLookupKey(input: {
  productCode: string
  planCode: string
  interval: 'month' | 'year'
  currency: string
}): string {
  return [
    segment('product', input.productCode),
    segment('plan', input.planCode),
    segment('interval', INTERVAL_WORDS[input.interval] ?? input.interval),
    segment('currency', input.currency),
  ].join('_')
}

/**
 * An add-on's permanent name, in the same shape with the plan segment replaced.
 *
 * The same four parts rather than a different scheme, because a price is a
 * price: anything reading a key should not have to know whether what it names
 * is a tier or a seat. The extra internal user is the only add-on today.
 */
export function addonLookupKey(input: {
  productCode: string
  addonCode: string
  interval: 'month' | 'year'
  currency: string
}): string {
  return [
    segment('product', input.productCode),
    segment('add-on', input.addonCode),
    segment('interval', INTERVAL_WORDS[input.interval] ?? input.interval),
    segment('currency', input.currency),
  ].join('_')
}

/**
 * The provider product a plan's prices hang from.
 *
 * One provider product per *plan*, not per KORAS product. A provider product
 * is what a customer sees named on an invoice and what a tax code attaches to,
 * and "Acme" on an invoice says less than "Acme Professional". It also keeps
 * the monthly and yearly prices of one plan together, which is what a checkout
 * switches between.
 */
export function productLookupKey(input: { productCode: string; planCode: string }): string {
  return [segment('product', input.productCode), segment('plan', input.planCode)].join('_')
}

/**
 * A stable name for one operation on one subject, for the idempotency header.
 *
 * Inbound idempotency was already sound — the event id is stored before the
 * event is acted on — so this closes the one-directional gap. Without it a
 * retried create can produce a second object for one plan, which is a money
 * defect rather than a data defect: two prices for one plan is two amounts a
 * checkout could pick between.
 *
 * The amount is part of the subject for a price, and that is deliberate rather
 * than incidental. The same plan at a corrected amount is a *different*
 * operation and must not replay the first attempt's answer — a provider price
 * is immutable in amount, so correcting one means creating another, and an
 * idempotency key that ignored the amount would silently hand back the old
 * price and report success.
 *
 * Hashed rather than sent in the clear because the provider caps the header's
 * length and an amount is not something to put in a header that appears in
 * request logs on both sides.
 */
export function idempotencyKey(operation: string, ...subject: Array<string | number>): string {
  const material = [operation, ...subject.map(String)].join('\u0000')
  return `koras.${operation}.${createHash('sha256').update(material).digest('hex').slice(0, 32)}`
}
