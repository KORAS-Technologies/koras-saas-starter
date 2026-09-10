/**
 * The shape a signup action reports back.
 *
 * Its own module because `actions.ts` carries `'use server'`, and such a file
 * may export *only* async functions -- everything exported from one becomes a
 * callable server endpoint, so a plain object cannot be. `IDLE` here and not
 * there is that rule, not a preference.
 *
 * Next catches it at build time rather than at runtime, which is the good
 * outcome; it does so while collecting page data, which reads as a page problem
 * rather than an export problem.
 */
export interface SignupState {
  status: 'idle' | 'ok' | 'error'
  message?: string
  /** Set when the fault belongs to one field, so the message can sit under it. */
  field?: string
}

export const IDLE: SignupState = { status: 'idle' }

/**
 * How far the provisioning run started by a verification has got.
 *
 * Here rather than in `actions.ts` for the same reason `SignupState` is: that
 * file carries `'use server'`, and everything exported from one becomes a
 * callable server endpoint, so it may export only async functions.
 *
 * Three booleans-worth of information and no error text. What broke in
 * provisioning is an operational fact the Control Plane deliberately does not
 * hand to an unauthenticated page, and a visitor could do nothing with it.
 */
export interface SignupStatus {
  /** The run's state, for display. `pending` covers everything not yet known. */
  state: string
  /** The account exists. This is the only field the page acts on. */
  ready: boolean
  /** The run finished and did not succeed, so waiting longer will not help. */
  failed: boolean
}

/**
 * What opens the payment provider's checkout, once an address is proved.
 *
 * Everything here is either something the visitor typed or something public
 * by nature. The price id is what the pricing page is built from; the seat
 * count and interval are what they chose; the address is the one they just
 * confirmed. The two ids travel into the checkout so the provider's webhook
 * can find its way back, and neither is a credential -- knowing one lets you
 * poll a status that answers one of three words.
 *
 * `url` is the provider's hosted checkout page, minted by the Control Plane
 * for this signup. It expires on its own within a day and opens nothing but
 * a form asking for a card.
 */
export interface CheckoutDetails {
  registrationId: string
  organizationId: string
  productCode: string
  planCode: string
  priceId: string
  seats: number
  billingInterval: 'month' | 'year'
  email: string
  url: string
}
