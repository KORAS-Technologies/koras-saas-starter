'use client'

import { useRef, useState, useTransition } from 'react'
import { Drawer } from '../primitives/drawer'
import { Icon } from '../primitives/icon'
import { NotificationList } from './notification-list'
import { withCount } from './types'
import type { NotificationItem, NotificationLabels } from './types'

/**
 * The bell in the header, its unread count, and the drawer behind it.
 *
 * **The count is rendered by the server and does not poll.** It is resolved in
 * the dashboard layout, once per navigation, alongside the settings and the
 * locale that were already read there. A five-second poll from every open tab
 * is a request per tab per five seconds for a number that changes a few times
 * a day, and the worker already polls its queue at that rate for a reason
 * recorded as R-018. So the count is right when a page loads and after any
 * action here, and stale in between — which is stated rather than implied,
 * and is the thing to revisit first if anybody asks for live updates.
 *
 * Marking read and dismissing are server actions passed down from the
 * application; this holds no list state of its own. After either, the page
 * revalidates and the drawer re-renders from the server's answer.
 */
export function NotificationBell({
  notifications,
  unread,
  labels,
  locale,
  allHref,
  onMarkRead,
  onMarkAllRead,
  onDismiss,
}: {
  notifications: readonly NotificationItem[]
  unread: number
  labels: NotificationLabels
  locale: string
  /** The notification centre, for everything the drawer does not show. */
  allHref: string
  onMarkRead: (id: string) => Promise<void>
  onMarkAllRead: () => Promise<void>
  onDismiss: (id: string) => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [pending, start] = useTransition()
  const trigger = useRef<HTMLButtonElement>(null)

  const run = (action: () => Promise<void>) => {
    start(() => {
      void action()
    })
  }

  return (
    <>
      <button
        ref={trigger}
        type="button"
        data-testid="notification-bell"
        aria-controls="notification-drawer"
        aria-expanded={open}
        onClick={() => {
          setOpen((was) => !was)
        }}
        className="relative inline-flex h-11 w-11 items-center justify-center rounded-brand text-ink hover:bg-surface-muted"
      >
        {/*
         * The count is on the button's accessible name rather than only in the
         * badge, so a screen reader hears "Notifications, 3 unread" instead of
         * "Notifications" beside an unannounced number.
         */}
        <span className="sr-only">
          {labels.title}
          {unread > 0 ? `, ${withCount(labels.unread, unread)}` : ''}
        </span>
        <Icon name="bell" className="h-5 w-5" />
        {unread > 0 ? (
          <span
            aria-hidden="true"
            data-testid="notification-badge"
            className="absolute right-1.5 top-1.5 inline-flex min-w-4 items-center justify-center rounded-full bg-brand px-1 text-[10px] font-semibold leading-4 text-white"
          >
            {/* Past ninety-nine the number stops being information and starts
                being a wide badge. */}
            {unread > 99 ? '99+' : unread}
          </span>
        ) : null}
      </button>

      <Drawer
        id="notification-drawer"
        open={open}
        title={labels.title}
        closeLabel={labels.close}
        onClose={() => {
          setOpen(false)
        }}
        returnFocusTo={trigger}
        testId="notification-drawer"
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-2">
          <p className="text-xs text-ink-muted">{withCount(labels.unread, unread)}</p>
          <button
            type="button"
            data-testid="mark-all-read"
            disabled={unread === 0 || pending}
            onClick={() => {
              run(onMarkAllRead)
            }}
            className="rounded-brand px-2 py-1 text-xs font-semibold text-brand hover:bg-surface-muted disabled:opacity-50"
          >
            {labels.markAllRead}
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <NotificationList
            notifications={notifications}
            labels={labels}
            locale={locale}
            onMarkRead={(id) => {
              run(() => onMarkRead(id))
            }}
            onDismiss={(id) => {
              run(() => onDismiss(id))
            }}
          />
        </div>

        <div className="border-t border-line px-4 py-3">
          <a
            href={allHref}
            data-testid="notification-view-all"
            className="text-sm font-semibold text-brand hover:underline"
          >
            {labels.viewAll}
          </a>
        </div>
      </Drawer>
    </>
  )
}
