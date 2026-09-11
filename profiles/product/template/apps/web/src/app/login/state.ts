/**
 * The shapes the sign-in page passes around.
 *
 * Its own module because `actions.ts` carries `'use server'`, and such a file
 * may export only async functions -- see `../signup/state.ts` for the rule.
 */
export interface SignInState {
  /**
   * `factor`: the password was right and the Control Plane is holding the
   * sign-in until a code arrives. `expired`: the auth request is gone, and
   * the only way on is to start again.
   */
  status: 'idle' | 'error' | 'factor' | 'expired'
  message?: string
  /** Set when the fault belongs to one field, so the message can sit under it. */
  field?: string
  /** The held sign-in, once the password has been checked. An id, not a credential. */
  attemptId?: string
}

export const IDLE: SignInState = { status: 'idle' }
