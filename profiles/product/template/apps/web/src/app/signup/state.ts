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
