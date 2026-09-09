/**
 * The shapes the activation page passes around.
 *
 * Its own module because `actions.ts` carries `'use server'`, and such a file
 * may export only async functions -- see `../signup/state.ts` for the rule.
 */
export interface ActivateState {
  status: 'idle' | 'ok' | 'error' | 'invalid'
  message?: string
  /** Set when the fault belongs to one field, so the message can sit under it. */
  field?: string
}

export const IDLE: ActivateState = { status: 'idle' }

/** Whom the link is for, as the Control Plane reports it. */
export interface ActivationDetails {
  email: string
  organizationName: string
  productCode: string
}
