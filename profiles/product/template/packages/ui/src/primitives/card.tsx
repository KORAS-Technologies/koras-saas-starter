import type { ReactNode } from 'react'
import { cn } from '../lib/cn'

/**
 * A card: a hairline border, a flat surface, and one soft shadow.
 *
 * Restraint is deliberate. A grid of six cards is already a strong shape; give
 * each one a gradient, a heavy shadow and a large radius and the grid stops
 * reading as content and starts reading as decoration.
 */
export function Card({
  as: Tag = 'div',
  className,
  children,
}: {
  as?: 'div' | 'article' | 'li'
  className?: string
  children: ReactNode
}) {
  return (
    <Tag
      className={cn(
        'rounded-brand border border-line bg-surface p-6 shadow-card sm:p-7',
        className,
      )}
    >
      {children}
    </Tag>
  )
}
