/**
 * The shapes the forgotten-password page passes around.
 *
 * Its own module because `actions.ts` carries `'use server'`, and such a file
 * may export only async functions -- see `../../signup/state.ts` for the rule.
 */
export interface ForgotState {
  status: 'idle' | 'sent' | 'error'
  message?: string
  /** Set when the fault belongs to one field, so the message can sit under it. */
  field?: string
  /** Echoed back on success so the page can say where the link went. */
  email?: string
}

export const IDLE: ForgotState = { status: 'idle' }
