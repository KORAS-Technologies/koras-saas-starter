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
 * `<product>.<plan>.<interval>.<currency>` — a price's permanent name.
 *
 * Deterministic and readable on purpose. It is read by a person in a provider
 * dashboard trying to work out which plan a price belongs to, and it is the
 * only thing tying an opaque `price_…` back to the catalogue that asked for it.
 *
 * **The currency segment is present from the first key**, before this estate
 * sells in more than one currency. That is the whole reason it is here: adding
 * it later would mean every existing price carries a key of a different shape,
 * and a second currency would be a re-key of the catalogue rather than an
 * addition to it. One segment now costs nothing.
 *
 * Lowercased because the provider treats lookup keys as case-sensitive and the
 * catalogue is lowercase by validation; normalising at the one place the key is
 * built means a stray capital cannot produce a second price for the same plan.
 */
export function priceLookupKey(input: {
  productCode: string
  planCode: string
  interval: 'month' | 'year'
  currency: string
}): string {
  return [input.productCode, input.planCode, input.interval, input.currency]
    .map((segment) => segment.trim().toLowerCase())
    .join('.')
}

/**
 * The provider product a plan's prices hang from.
 *
 * One provider product per *plan*, not per KORAS product. A provider product
 * is what a customer sees named on an invoice and what a tax code attaches to,
 * and "Acme" on an invoice says less than "Acme Pro". It also keeps the
 * monthly and yearly prices of one plan together, which is what a checkout
 * switches between.
 */
export function productLookupKey(input: { productCode: string; planCode: string }): string {
  return [input.productCode, input.planCode]
    .map((segment) => segment.trim().toLowerCase())
    .join('.')
}

/**
 * A stable name for one operation on one subject, for the idempotency header.
 *
 * BILL-GAP-002. Inbound idempotency was already sound — the event id is stored
 * before the event is acted on — so this closes the one-directional gap.
 * Without it a retried create can produce a second object for one plan, which
 * is a money defect rather than a data defect: two prices for one plan is two
 * amounts a checkout could pick between.
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
