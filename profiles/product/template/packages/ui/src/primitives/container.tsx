import type { ReactNode } from 'react'
import { cn } from '../lib/cn'

/**
 * The one content width in the product.
 *
 * Every section measures itself against this, which is what makes the vertical
 * edge of the page read as a single line from the header to the footer. A
 * section that sets its own max-width is the first crack in that.
 */
export function Container({
  className,
  children,
}: {
  className?: string
  children: ReactNode
}) {
  return <div className={cn('mx-auto w-full max-w-6xl px-5 sm:px-8', className)}>{children}</div>
}
