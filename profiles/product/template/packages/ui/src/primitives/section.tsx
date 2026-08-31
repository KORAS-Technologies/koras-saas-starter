import type { ReactNode } from 'react'
import { cn } from '../lib/cn'
import { Container } from './container'

/**
 * A page section, with the heading treatment that goes with it.
 *
 * The eyebrow is not decoration: it names the section for somebody scanning,
 * and it is the accessible label the heading below then answers. Rendering it
 * outside the heading keeps the document outline to real headings only.
 *
 * `id` is required whenever the section is a navigation target, which is how
 * the header links resolve to something that exists.
 */
export function Section({
  id,
  eyebrow,
  title,
  description,
  tone = 'default',
  className,
  headingClassName,
  children,
}: {
  id?: string
  eyebrow?: string
  title?: string
  description?: string
  /** `muted` is the quiet band used to separate two light sections. */
  tone?: 'default' | 'muted'
  className?: string
  headingClassName?: string
  children: ReactNode
}) {
  return (
    <section
      id={id}
      aria-labelledby={id && title ? `${id}-heading` : undefined}
      className={cn(
        'py-20 sm:py-24',
        tone === 'muted' && 'border-y border-line bg-surface-muted',
        className,
      )}
    >
      <Container>
        {(eyebrow || title || description) && (
          <div className={cn('mb-12 max-w-2xl', headingClassName)}>
            {eyebrow && (
              <p className="mb-3 flex items-center gap-2.5 text-sm font-semibold tracking-wide text-brand uppercase">
                <span aria-hidden="true" className="h-px w-6 bg-brand-accent" />
                {eyebrow}
              </p>
            )}
            {title && (
              <h2
                id={id ? `${id}-heading` : undefined}
                className="font-display text-3xl font-bold tracking-tight text-balance sm:text-4xl"
              >
                {title}
              </h2>
            )}
            {description && (
              <p className="mt-4 text-lg leading-8 text-ink-muted text-pretty">{description}</p>
            )}
          </div>
        )}
        {children}
      </Container>
    </section>
  )
}
