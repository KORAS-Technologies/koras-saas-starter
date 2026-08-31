import type { ReactNode } from 'react'
import { cn } from '../lib/cn'

/**
 * The card an authentication screen puts its one job inside.
 *
 * `title` renders the page's <h1>. Every auth screen has exactly one heading
 * and it is the thing being done -- "Sign in", "Create your account", "By
 * invitation only" -- so the heading level lives here rather than being chosen
 * again on each page, where one of them would eventually be an <h2>.
 *
 * Borderless on a narrow screen: a card outline drawn 16px from the viewport
 * edge is a box around the whole screen, which is not a card, it is a frame.
 */
export function AuthCard({
  title,
  description,
  footer,
  className,
  children,
}: {
  title: string
  description?: ReactNode
  footer?: ReactNode
  className?: string
  children?: ReactNode
}) {
  return (
    <div
      className={cn(
        'rounded-brand bg-surface sm:border sm:border-line sm:p-8 sm:shadow-card',
        className,
      )}
    >
      <h1 className="font-display text-2xl font-bold tracking-tight text-ink">{title}</h1>
      {description && <div className="mt-3 leading-7 text-ink-muted">{description}</div>}
      {children && <div className="mt-8">{children}</div>}
      {footer && <div className="mt-8 border-t border-line pt-6 text-sm text-ink-muted">{footer}</div>}
    </div>
  )
}
