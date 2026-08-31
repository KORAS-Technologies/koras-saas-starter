import type { ButtonHTMLAttributes, ReactNode } from 'react'
import Link from 'next/link'
import { cn } from '../lib/cn'

/**
 * One button treatment, in five variants, for the whole product.
 *
 * `inverse` and `outline` exist because the hero, the final call to action and
 * the auth panel are dark: a primary button on ink has to invert to stay
 * legible, and giving it a variant here is what stops each dark section
 * inventing its own.
 *
 * Every variant is at least 44px tall. That is the pointer target size WCAG 2.2
 * asks for, and it is easier to hold as a property of the button than to
 * remember per use.
 */
export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'inverse' | 'outline'
export type ButtonSize = 'md' | 'lg'

const BASE =
  'inline-flex items-center justify-center gap-2 rounded-brand font-semibold ' +
  'transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-60'

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-brand text-white hover:bg-brand-ink',
  secondary: 'border border-line bg-surface text-ink hover:bg-surface-muted',
  ghost: 'text-ink hover:bg-surface-muted',
  inverse: 'bg-white text-brand-ink hover:bg-white/85',
  outline: 'border border-white/25 bg-white/5 text-white hover:bg-white/12',
}

const SIZES: Record<ButtonSize, string> = {
  md: 'min-h-11 px-4 py-2.5 text-sm',
  lg: 'min-h-12 px-6 py-3 text-base',
}

function classes(variant: ButtonVariant, size: ButtonSize, className?: string) {
  return cn(BASE, VARIANTS[variant], SIZES[size], className)
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  className,
  children,
  disabled,
  ...rest
}: {
  variant?: ButtonVariant
  size?: ButtonSize
  /** Disables the control and announces the wait, rather than only spinning. */
  loading?: boolean
  children: ReactNode
} & Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className' | 'children'> & {
    className?: string
  }) {
  return (
    <button
      className={classes(variant, size, className)}
      // A submitting form must not accept a second submission, and the reason
      // has to reach a screen reader as well as the pointer.
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading && (
        <span
          aria-hidden="true"
          className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
        />
      )}
      {children}
    </button>
  )
}

/**
 * A page this application's router can navigate to.
 *
 * Two kinds of href are excluded, for two different reasons.
 *
 * `mailto:` and `https://` are not paths at all: `next/link` intercepts the
 * click and hands the href to the router, which cannot navigate to either, so
 * the link silently does nothing. The request-access card is built out of
 * mailto links, so this is not theoretical.
 *
 * `/api/...` is a route handler rather than a page, and the problem there is
 * prefetching. `next/link` fetches what it points at before anybody clicks --
 * and `/api/auth/start` begins an OAuth authorization: it mints a state token
 * and a PKCE verifier and sets them as cookies. Prefetching it starts a
 * sign-in the visitor did not ask for, on hover, and leaves the cookies from
 * that attempt behind for the real click to race with. Observed as a 500 in
 * the browser console on every load of the sign-in page, from a request nobody
 * made.
 */
function isRoutablePage(href: string): boolean {
  if (!href.startsWith('/') && !href.startsWith('#')) return false
  return !href.startsWith('/api/')
}

export function ButtonLink({
  href,
  variant = 'primary',
  size = 'md',
  className,
  testId,
  children,
}: {
  href: string
  variant?: ButtonVariant
  size?: ButtonSize
  className?: string
  /**
   * Rendered as `data-testid` on the anchor itself.
   *
   * A named prop rather than a spread of arbitrary attributes: the sign-in link
   * carries a test id that the deployment smoke checks resolve to an element
   * and read `href` from, so it has to land on the anchor and not on a span
   * inside it.
   */
  testId?: string
  children: ReactNode
}) {
  const classNames = classes(variant, size, className)

  if (!isRoutablePage(href)) {
    return (
      <a href={href} className={classNames} data-testid={testId}>
        {children}
      </a>
    )
  }

  return (
    <Link href={href} className={classNames} data-testid={testId}>
      {children}
    </Link>
  )
}
