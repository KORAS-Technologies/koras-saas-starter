'use client'

import { useEffect, useState } from 'react'
import { useFormStatus } from 'react-dom'
import type { ReactNode } from 'react'
import { Button, type ButtonSize, type ButtonVariant } from './button'

/**
 * A submit control that knows its form is busy, and knows whether it is live.
 *
 * `Button` already refuses a second click and announces the wait once it is
 * told it is loading. Nothing told it: `loading` had to be threaded down from
 * whatever held the request, and a form that forgot accepted the second
 * submission. `useFormStatus` reads it from the form itself, which is the one
 * place that cannot be out of date.
 *
 * The second half is subtler and is the reason this exists as a component
 * rather than a note in a review.
 *
 * A page segment hydrates independently of the shell around it, so the chrome
 * can be interactive while this form is still inert markup. A click in that
 * window posts natively: the server action runs, the page re-renders, and
 * `useActionState` starts from nothing -- so the work happened and the form
 * says nothing about it. It reads as a slow action, or as a click that did not
 * register, and it is intermittent by nature.
 *
 * `data-enhanced` states it rather than leaving it to be inferred. A test that
 * waits for the shell's own hydration signal is testing the wrong thing and
 * will race; this is the only signal that *this form* is ready.
 *
 * Promoted from the Control Plane, which found the pre-hydration case in its
 * own console. Only this part came: the rest of that module is a second set of
 * field and button treatments, and this package already has those.
 */
export function SubmitButton({
  children,
  busy,
  variant = 'primary',
  size = 'md',
  testId = 'submit',
  className,
}: {
  children: ReactNode
  /** What to say while waiting. Not a spinner alone -- it is read aloud. */
  busy: string
  variant?: ButtonVariant
  size?: ButtonSize
  testId?: string
  className?: string
}) {
  const { pending } = useFormStatus()

  const [enhanced, setEnhanced] = useState(false)
  useEffect(() => setEnhanced(true), [])

  return (
    <Button
      type="submit"
      variant={variant}
      size={size}
      loading={pending}
      className={className}
      data-enhanced={enhanced ? 'true' : 'false'}
      data-testid={testId}
    >
      {pending ? busy : children}
    </Button>
  )
}
