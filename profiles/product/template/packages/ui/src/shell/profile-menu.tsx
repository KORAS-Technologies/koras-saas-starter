'use client'

import { useEffect, useId, useRef, useState } from 'react'
import { usePathname } from 'next/navigation'
import type { ShellIdentity } from './product-shell'

/**
 * Who you are signed in as, and the three things you can do about it.
 *
 * A disclosure rather than a menu widget, for the reason `PublicHeader` gives:
 * the panel is a list of links and one form, the platform already knows how to
 * operate those, and a hand-rolled `role="menu"` would take arrow-key handling,
 * roving tabindex and typeahead away from the browser and give back a worse
 * copy.
 *
 * **What is deliberately not in here:** billing, subscriptions, plans, domains,
 * single sign-on, the product catalogue, provisioning, infrastructure, and
 * organization membership. Every one of those belongs to the Customer Portal or
 * to the Control Plane, and a product that grows its own copy has two places to
 * change a price and two answers to who is a member.
 *
 * The one concession is `accountUrl`: a single outbound link, rendered only
 * when the caller may actually manage the account, that leaves for the portal.
 * A link out is not a reimplementation.
 */
export function ProductProfileMenu({
  identity,
  accountUrl,
}: {
  identity: ShellIdentity
  accountUrl?: string
}) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const toggleRef = useRef<HTMLButtonElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const pathname = usePathname()

  useEffect(() => setOpen(false), [pathname])

  useEffect(() => {
    if (!open) return

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setOpen(false)
      toggleRef.current?.focus()
    }
    // Closing on an outside click as well as on Escape, because a panel that
    // stays open while the reader clicks the page behind it looks stuck.
    // Focus is not moved here: the reader has already put it somewhere.
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }

    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('mousedown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('mousedown', onPointerDown)
    }
  }, [open])

  const display = identity.name ?? identity.email ?? 'Signed in'

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={toggleRef}
        type="button"
        onClick={() => setOpen((wasOpen) => !wasOpen)}
        aria-expanded={open}
        aria-controls={panelId}
        className="inline-flex min-h-11 items-center gap-2 rounded-brand border border-line px-2 text-sm font-medium text-ink hover:bg-surface-muted"
      >
        <Avatar label={display} />
        <span className="hidden max-w-40 truncate sm:inline">{display}</span>
        <span className="sr-only">Account menu</span>
      </button>

      {/* Rendered in both states so `aria-controls` points at something real
          before the control is ever used. */}
      <div
        id={panelId}
        hidden={!open}
        className="absolute right-0 z-50 mt-2 w-64 rounded-brand border border-line bg-surface p-2 shadow-card"
      >
        <div className="border-b border-line px-3 pb-3 pt-2">
          <p className="truncate text-sm font-semibold text-ink">{display}</p>
          {identity.email !== undefined && identity.email !== display && (
            <p className="truncate text-xs text-ink-muted">{identity.email}</p>
          )}
          {identity.roleLabel !== undefined && (
            <p className="mt-1 text-xs text-ink-muted">
              {identity.roleLabel}
              {identity.organizationName !== undefined && ' · ' + identity.organizationName}
            </p>
          )}
        </div>

        {accountUrl !== undefined && (
          <a
            // A plain anchor, and it leaves this application. `next/link`
            // would try to route to it, and prefetch it on hover.
            href={accountUrl}
            className="flex min-h-11 items-center justify-between rounded-brand px-3 text-sm text-ink hover:bg-surface-muted"
          >
            Manage subscription
            <span aria-hidden="true">↗</span>
            <span className="sr-only">(opens the Koras account portal)</span>
          </a>
        )}

        {/*
          A form, because the sign-out route is POST-only -- deliberately, so
          that any page able to make this browser load a URL cannot sign
          somebody out. A link here would render a control that always returns
          405.
        */}
        <form action="/api/auth/signout" method="post">
          <button
            type="submit"
            className="flex min-h-11 w-full items-center rounded-brand px-3 text-left text-sm font-semibold text-ink hover:bg-surface-muted"
          >
            Sign out
          </button>
        </form>
      </div>
    </div>
  )
}

/**
 * Initials on a brand-coloured tile.
 *
 * Drawn rather than fetched: an avatar image would be a request to somewhere,
 * and the only somewhere available is a third-party gravatar service that would
 * publish every customer's email hash from every page of the product.
 */
function Avatar({ label }: { label: string }) {
  const initials = label
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')

  return (
    <span
      aria-hidden="true"
      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand text-xs font-bold text-white"
    >
      {initials === '' ? '·' : initials}
    </span>
  )
}
