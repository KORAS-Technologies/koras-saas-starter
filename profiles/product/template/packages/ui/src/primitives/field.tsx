import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { cn } from '../lib/cn'

/**
 * A labelled field, with its error attached to it.
 *
 * The association is the reason this exists. `aria-describedby` pointing at the
 * error, `aria-invalid` on the control and `role="alert"` on the message are
 * three things that have to agree, and doing them by hand on each field is how
 * a form ends up announcing "invalid" without ever saying what is wrong. Here
 * they are derived from one `error` prop and cannot disagree.
 */

const CONTROL =
  'w-full min-h-11 rounded-brand border bg-surface px-3.5 py-2.5 text-base text-ink ' +
  'placeholder:text-ink-muted/70 transition-colors'

function controlClasses(invalid: boolean, className?: string) {
  return cn(CONTROL, invalid ? 'border-red-600' : 'border-line hover:border-ink-muted/50', className)
}

function describedBy(id: string, error?: string, hint?: string): string | undefined {
  const ids = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean)
  return ids.length > 0 ? ids.join(' ') : undefined
}

/**
 * Where a field's hint sits relative to its control.
 *
 * `above` (the default) is the long-standing shape: label, hint, control. It
 * suits a hint that has to be read before answering, such as a format rule.
 * `below` is label, control, hint, and exists so two fields side by side in a
 * grid row keep their controls level when only one of them carries a hint: a
 * hint above the control pushes that control down by the height of the hint.
 * Either way the control's `aria-describedby` names the hint.
 */
export type HintPlacement = 'above' | 'below'

function Frame({
  id,
  label,
  hint,
  hintPlacement = 'above',
  error,
  children,
}: {
  id: string
  label: string
  hint?: string
  hintPlacement?: HintPlacement
  error?: string
  children: ReactNode
}) {
  const hintBelow = hint && hintPlacement === 'below'
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-semibold text-ink">
        {label}
      </label>
      {hint && !hintBelow && (
        <p id={`${id}-hint`} className="mt-1 text-sm text-ink-muted">
          {hint}
        </p>
      )}
      <div className="mt-2">{children}</div>
      {hintBelow && (
        <p id={`${id}-hint`} className="mt-2 text-sm text-ink-muted">
          {hint}
        </p>
      )}
      {error && (
        // Announced when it appears, and only then. A live region wrapping the
        // whole form would re-read every field on each keystroke.
        <p id={`${id}-error`} role="alert" className="mt-2 text-sm font-medium text-red-700">
          {error}
        </p>
      )}
    </div>
  )
}

export function TextField({
  id,
  label,
  hint,
  error,
  className,
  ...rest
}: {
  id: string
  label: string
  hint?: string
  error?: string
  className?: string
} & Omit<InputHTMLAttributes<HTMLInputElement>, 'id' | 'className'>) {
  return (
    <Frame id={id} label={label} hint={hint} error={error}>
      <input
        id={id}
        className={controlClasses(Boolean(error), className)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, error, hint)}
        {...rest}
      />
    </Frame>
  )
}

export function SelectField({
  id,
  label,
  hint,
  hintPlacement,
  error,
  className,
  children,
  ...rest
}: {
  id: string
  label: string
  hint?: string
  hintPlacement?: HintPlacement
  error?: string
  className?: string
  children: ReactNode
} & Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id' | 'className' | 'children'>) {
  return (
    <Frame id={id} label={label} hint={hint} hintPlacement={hintPlacement} error={error}>
      <select
        id={id}
        className={controlClasses(Boolean(error), className)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, error, hint)}
        {...rest}
      >
        {children}
      </select>
    </Frame>
  )
}
