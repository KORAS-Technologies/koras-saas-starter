import type { ReactNode } from 'react'
import { cn } from '../lib/cn'

/**
 * A message bar for a condition that persists.
 *
 * The division this design system draws, and the reason there are two
 * primitives rather than one:
 *
 * - a **toast** is feedback for something the person just did. It goes away,
 *   because the thing it describes is over.
 * - a **banner** is a condition that is still true. It stays, because
 *   dismissing it does not change it.
 *
 * Getting that backwards is the commonest notification mistake: a toast saying
 * "your subscription has lapsed" disappears while the subscription is still
 * lapsed, and a banner saying "saved" sits there until the page reloads.
 *
 * `onDismiss` is for a banner a person may reasonably stop being shown — an
 * announcement, a tip. A banner about something they must act on takes none,
 * so there is nothing to dismiss and no state to remember.
 *
 * Before this existed, roughly thirty surfaces hand-rolled a `role="alert"`
 * region each, and each did it differently. This does not migrate them; it
 * gives the next one somewhere to go.
 */
export function Banner({
  tone = 'info',
  title,
  children,
  action,
  onDismiss,
  dismissLabel,
  className,
}: {
  tone?: 'info' | 'success' | 'warning' | 'error'
  title?: string
  children: ReactNode
  action?: ReactNode
  onDismiss?: () => void
  dismissLabel?: string
  className?: string
}) {
  return (
    <div
      // `alert` is assertive and interrupts a screen reader mid-sentence. That
      // is right for something that went wrong and rude for an announcement,
      // so only the error tone claims it.
      role={tone === 'error' ? 'alert' : 'status'}
      className={cn(
        'flex flex-wrap items-start gap-3 rounded-brand border p-4 text-sm sm:flex-nowrap',
        TONES[tone],
        className,
      )}
    >
      <span aria-hidden="true" className="mt-0.5 shrink-0">
        {GLYPHS[tone]}
      </span>
      <div className="min-w-0 flex-1">
        {title ? <p className="font-semibold text-ink">{title}</p> : null}
        <div className={cn('text-ink-muted', title ? 'mt-0.5' : undefined)}>{children}</div>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          // 44px, so it is a target on a phone rather than a pixel.
          className="-my-2 -mr-2 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-brand text-ink-muted hover:bg-surface-muted"
        >
          <span className="sr-only">{dismissLabel ?? 'Dismiss'}</span>
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            className="h-4 w-4"
            aria-hidden="true"
            focusable="false"
          >
            <path d="m6 6 12 12M18 6 6 18" />
          </svg>
        </button>
      ) : null}
    </div>
  )
}

/**
 * Tone carries a border and a tint, never colour alone — a person who cannot
 * distinguish the tints still gets the glyph and the words. WCAG 1.4.1.
 */
const TONES: Record<string, string> = {
  info: 'border-line bg-surface-muted',
  success: 'border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950',
  warning: 'border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950',
  error: 'border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950',
}

const GLYPHS: Record<string, string> = {
  info: 'ℹ',
  success: '✓',
  warning: '!',
  error: '×',
}
