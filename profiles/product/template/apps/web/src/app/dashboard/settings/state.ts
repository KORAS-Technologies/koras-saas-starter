/**
 * The shape the organisation-language form passes around.
 *
 * Its own module because `actions.ts` carries `'use server'`, and such a file
 * may export only async functions -- see `../../signup/state.ts` for the rule.
 */
export interface TenantLocaleState {
  status: 'idle' | 'saved' | 'error'
  message?: string
}

export const IDLE: TenantLocaleState = { status: 'idle' }
