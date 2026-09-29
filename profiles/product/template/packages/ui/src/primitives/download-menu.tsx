'use client'

import { useEffect, useId, useRef, useState } from 'react'
import { ButtonLink } from './button'

/**
 * One button that discloses a short list of downloads.
 *
 * The shell's profile menu and the reporting export menu, combined: a
 * disclosure -- a button with `aria-expanded` and `aria-controls` over a
 * panel rendered in both states, closed by Escape, by an outside click and
 * by focus leaving it -- whose items are plain anchors, because a download
 * is a body and `ButtonLink` renders a real anchor for any `/api/` href so
 * the router never prefetches one. A prefetched template download would be
 * recorded in the audit table as if somebody had asked for it.
 *
 * **Not a menu role**, for the reason the profile menu gives: a real menu
 * takes arrow-key handling and roving focus, and a panel of two or three links
 * does not need them. The menu-shaped ARIA roles are deliberately absent. Tab reaches the button, Enter or Space opens the panel
 * and moves focus to the first item, Tab walks the items, Escape closes and
 * returns focus to the button.
 *
 * Rendered with one item as readily as with three, so the control behaves the
 * same way for every target rather than collapsing into a bare link when a
 * target accepts one format.
 */
export function DownloadMenu({
  label,
  items,
  disabled = false,
  testId,
}: {
  /** The button's text. */
  label: string
  items: Array<{ key: string; href: string; label: string }>
  disabled?: boolean
  testId?: string
}) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const toggleRef = useRef<HTMLButtonElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setOpen(false)
      toggleRef.current?.focus()
    }
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onFocusOut = (event: FocusEvent) => {
      const next = event.relatedTarget as Node | null
      if (next !== null && !containerRef.current?.contains(next)) setOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('mousedown', onPointerDown)
    const container = containerRef.current
    container?.addEventListener('focusout', onFocusOut)
    // The first item takes focus once the panel is open, so a keyboard user
    // who pressed Enter is on a download rather than on a button that now
    // says "expanded" and nothing else.
    const first = container?.querySelector<HTMLAnchorElement>(`#${CSS.escape(panelId)} a`)
    first?.focus()
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('mousedown', onPointerDown)
      container?.removeEventListener('focusout', onFocusOut)
    }
  }, [open, panelId])

  return (
    <div ref={containerRef} className="relative inline-block" data-testid={testId}>
      <button
        ref={toggleRef}
        type="button"
        disabled={disabled || items.length === 0}
        onClick={() => setOpen((wasOpen) => !wasOpen)}
        aria-expanded={open}
        aria-controls={panelId}
        aria-haspopup="true"
        className="inline-flex min-h-11 items-center justify-center gap-2 rounded-brand border border-line bg-surface px-4 text-sm font-medium text-ink hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {label}
        <span aria-hidden="true">▾</span>
      </button>

      {/* Rendered in both states so `aria-controls` points at something real
          before the control is ever used. */}
      <div
        id={panelId}
        hidden={!open}
        // Choosing an item closes the panel and returns focus to the button.
        // The anchor's own navigation -- the download -- proceeds; only the
        // disclosure changes. A panel left open after a choice reads as a
        // choice that did not take, and the next press on the button would
        // close it rather than open it.
        onClick={() => {
          setOpen(false)
          toggleRef.current?.focus()
        }}
        className="absolute left-0 z-40 mt-2 flex w-full min-w-56 flex-col gap-1 rounded-brand border border-line bg-surface p-2 shadow-card sm:w-auto"
      >
        {items.map((item) => (
          <ButtonLink
            key={item.key}
            href={item.href}
            variant="ghost"
            className="justify-start"
            testId={testId === undefined ? undefined : `${testId}-${item.key}`}
          >
            {item.label}
          </ButtonLink>
        ))}
      </div>
    </div>
  )
}
