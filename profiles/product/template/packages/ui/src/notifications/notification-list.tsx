'use client'

import { cn } from '../lib/cn'
import { withCount } from './types'
import type { NotificationItem, NotificationLabels, NotificationTone } from './types'

/**
 * A feed, newest first.
 *
 * Shared by the drawer and the notification centre, because two renderings of
 * one list is two places for "unread" to stop meaning the same thing.
 *
 * **An unread notification is marked by three things, not one.** A left rule,
 * a heavier title, and a dot with a text alternative. Colour alone would leave
 * the distinction invisible to a reader who cannot see it and to one who
 * cannot see at all.
 *
 * Marking read and dismissing are server actions passed in from the
 * application. This component holds no state: after either, the page
 * revalidates and the list arrives correct, which is one source of truth
 * rather than an optimistic copy that can disagree with the server.
 */
export function NotificationList({
  notifications,
  labels,
  locale,
  onMarkRead,
  onDismiss,
  className,
}: {
  notifications: readonly NotificationItem[]
  labels: NotificationLabels
  locale: string
  onMarkRead?: (id: string) => void
  onDismiss?: (id: string) => void
  className?: string
}) {
  if (notifications.length === 0) {
    return (
      <div className={cn('px-4 py-10 text-center', className)} data-testid="notifications-empty">
        <p className="text-sm font-semibold text-ink">{labels.empty}</p>
        <p className="mt-1 text-sm text-ink-muted">{labels.emptyHint}</p>
      </div>
    )
  }

  return (
    <ul className={cn('divide-y divide-line', className)} data-testid="notification-list">
      {notifications.map((item) => (
        <li
          key={item.id}
          data-testid="notification"
          data-read={item.read ? 'true' : 'false'}
          data-kind={item.kind}
          className={cn(
            'flex gap-3 border-l-2 px-4 py-3',
            item.read ? 'border-l-transparent' : RULES[item.tone],
          )}
        >
          <div className="min-w-0 flex-1">
            <p className={cn('text-sm text-ink', item.read ? '' : 'font-semibold')}>
              {item.url ? (
                <a className="hover:underline" href={item.url}>
                  {item.title}
                </a>
              ) : (
                item.title
              )}
              {item.read ? null : (
                // The text alternative for the rule and the weight. A screen
                // reader gets the word; a sighted reader gets the mark.
                <span className="sr-only"> — {withCount(labels.unread, 1)}</span>
              )}
            </p>
            {item.body ? <p className="mt-0.5 text-sm text-ink-muted">{item.body}</p> : null}
            <p className="mt-1 text-xs text-ink-muted">
              <time dateTime={item.createdAt}>{when(item.createdAt, locale)}</time>
            </p>
          </div>
          <div className="flex shrink-0 items-start gap-1">
            {!item.read && onMarkRead ? (
              <button
                type="button"
                data-testid="mark-read"
                onClick={() => {
                  onMarkRead(item.id)
                }}
                className="inline-flex h-11 w-11 items-center justify-center rounded-brand text-ink-muted hover:bg-surface-muted"
              >
                <span className="sr-only">{labels.markRead}</span>
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
                  <path d="m5 12.5 4.5 4.5L19 7.5" />
                </svg>
              </button>
            ) : null}
            {onDismiss ? (
              <button
                type="button"
                data-testid="dismiss"
                onClick={() => {
                  onDismiss(item.id)
                }}
                className="inline-flex h-11 w-11 items-center justify-center rounded-brand text-ink-muted hover:bg-surface-muted"
              >
                <span className="sr-only">{labels.dismiss}</span>
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
        </li>
      ))}
    </ul>
  )
}

const RULES: Record<NotificationTone, string> = {
  info: 'border-l-brand',
  success: 'border-l-emerald-500',
  warning: 'border-l-amber-500',
  error: 'border-l-red-500',
}

/**
 * The reader's own formatting, from their own locale.
 *
 * `Intl` rather than a date library: it is in every runtime this ships to, it
 * knows every locale the product might add, and it adds nothing to the bundle.
 * An unparseable value renders as itself rather than as "Invalid Date", which
 * is the failure that reaches a customer.
 */
function when(iso: string, locale: string): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return iso
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(at)
}
