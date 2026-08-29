'use client'

import { useActionState } from 'react'
import type { PublicPlan } from './actions'
import { startSignup } from './actions'
import { IDLE } from './state'

/**
 * The one form a stranger fills in.
 *
 * A real form posting to a server action, so it works before React has attached
 * and keeps working if it never does -- which matters more here than anywhere
 * else in the product: this page is the first thing a prospective customer
 * loads, over whatever connection they have, and a signup that needs a
 * hydrated bundle is a signup some people cannot complete.
 *
 * Three fields, because the Control Plane needs three things. Anything else --
 * team size, how they heard about us -- belongs after they have an account, not
 * between them and one.
 */
export function SignupForm({ plans }: { plans: PublicPlan[] }) {
  const [state, action] = useActionState(startSignup, IDLE)

  if (state.status === 'ok') {
    return (
      <div data-testid="signup-sent">
        <h2>Check your email</h2>
        <p>{state.message}</p>
      </div>
    )
  }

  return (
    <form action={action} data-testid="signup-form">
      <label htmlFor="signup-organizationName">Organisation</label>
      <input
        id="signup-organizationName"
        name="organizationName"
        required
        autoComplete="organization"
        aria-invalid={state.field === 'organizationName' ? true : undefined}
        aria-describedby={
          state.field === 'organizationName' ? 'signup-organizationName-error' : undefined
        }
      />
      {state.field === 'organizationName' ? (
        <p id="signup-organizationName-error" role="alert">
          {state.message}
        </p>
      ) : null}

      <label htmlFor="signup-email">Work email</label>
      <input
        id="signup-email"
        name="email"
        type="email"
        required
        autoComplete="email"
        aria-invalid={state.field === 'email' ? true : undefined}
        aria-describedby={state.field === 'email' ? 'signup-email-error' : undefined}
      />
      {state.field === 'email' ? (
        <p id="signup-email-error" role="alert">
          {state.message}
        </p>
      ) : null}

      <label htmlFor="signup-ownerName">Your name (optional)</label>
      <input id="signup-ownerName" name="ownerName" autoComplete="name" />

      {/*
        One plan is not a choice, so it is not presented as one -- a select with
        a single option asks somebody to make a decision that has already been
        made. It still has to be submitted, so it goes as a hidden field.
      */}
      {plans.length === 1 ? (
        <input type="hidden" name="planCode" value={plans[0]!.code} />
      ) : (
        <>
          <label htmlFor="signup-planCode">Plan</label>
          <select id="signup-planCode" name="planCode" required defaultValue={plans[0]?.code}>
            {plans.map((plan) => (
              <option key={plan.code} value={plan.code}>
                {plan.name}
              </option>
            ))}
          </select>
        </>
      )}

      {/* Announced, because the page does not navigate and a screen reader has
          no other way to learn the form did anything. */}
      <div aria-live="polite">
        {state.status === 'error' && !state.field ? (
          <p role="alert" data-testid="signup-error">
            {state.message}
          </p>
        ) : null}
      </div>

      <button type="submit" data-testid="signup-submit">
        Create account
      </button>
    </form>
  )
}
