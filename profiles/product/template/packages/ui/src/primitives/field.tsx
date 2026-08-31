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

function Frame({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string
  label: string
  hint?: string
  error?: string
  children: ReactNode
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-semibold text-ink">
        {label}
      </label>
      {hint && (
        <p id={`${id}-hint`} className="mt-1 text-sm text-ink-muted">
          {hint}
        </p>
      )}
      <div className="mt-2">{children}</div>
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
  error,
  className,
  children,
  ...rest
}: {
  id: string
  label: string
  hint?: string
  error?: string
  className?: string
  children: ReactNode
} & Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id' | 'className' | 'children'>) {
  return (
    <Frame id={id} label={label} hint={hint} error={error}>
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
