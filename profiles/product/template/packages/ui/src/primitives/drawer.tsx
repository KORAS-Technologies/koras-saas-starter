'use client'

import { useCallback, useEffect, useRef } from 'react'
import type { ReactNode, RefObject } from 'react'

/**
 * A panel over the page and to its right, treated as a dialog.
 *
 * Focus goes in when it opens, Tab wraps at the ends, Escape closes it, and
 * focus goes back to the control that opened it.
 *
 * **Extracted from the assistant's drawer on 2026-09-19, when a second feature
 * wanted one.** That file carried a note saying a second copy of the trap was
 * cheaper than a library shipped to every product for two panels — which was
 * true at two and stops being true at three. The notification drawer is the
 * third panel in this design system, so the trap moved here and `AIDrawer`
 * became a wrapper around it.
 *
 * The shell's navigation drawer still has its own copy. Moving that one means
 * touching the shell's layout, which is a change worth making on its own
 * rather than as a side effect of adding a feature — so it is named here
 * rather than quietly left.
 *
 * Rendered in both states and hidden with `hidden`, so a trigger's
 * `aria-controls` resolves before the first open. Full-width below `sm`, a
 * column beside the page above it.
 */
export function Drawer({
  id,
  open,
  title,
  closeLabel,
  onClose,
  returnFocusTo,
  initialFocusSelector,
  testId,
  children,
}: {
  id: string
  open: boolean
  title: string
  closeLabel: string
  onClose: () => void
  /** The trigger, so closing hands the focus back. */
  returnFocusTo?: RefObject<HTMLButtonElement | null>
  /**
   * Where focus lands when the panel opens, if not the first control. The
   * assistant points this at its composer, because somebody opening an
   * assistant came to type.
   */
  initialFocusSelector?: string
  testId?: string
  children: ReactNode
}) {
  const panelRef = useRef<HTMLDivElement>(null)

  const close = useCallback(() => {
    onClose()
    returnFocusTo?.current?.focus()
  }, [onClose, returnFocusTo])

  useEffect(() => {
    if (!open) return
    const panel = panelRef.current

    const focusable = () =>
      [
        ...(panel?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? []),
      ].filter((element) => element.offsetParent !== null)

    const preferred = initialFocusSelector
      ? panel?.querySelector<HTMLElement>(initialFocusSelector)
      : null
    const first = preferred ?? focusable()[0]
    first?.focus()

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        close()
        return
      }
      if (event.key !== 'Tab') return
      const elements = focusable()
      if (elements.length === 0) return
      const head = elements[0] as HTMLElement
      const tail = elements[elements.length - 1] as HTMLElement
      if (event.shiftKey && document.activeElement === head) {
        event.preventDefault()
        tail.focus()
      } else if (!event.shiftKey && document.activeElement === tail) {
        event.preventDefault()
        head.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, close, initialFocusSelector])

  return (
    <div
      id={id}
      hidden={!open}
      className="fixed inset-0 z-50"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-testid={testId}
    >
      <button
        type="button"
        tabIndex={-1}
        aria-hidden="true"
        onClick={close}
        className="absolute inset-0 h-full w-full bg-black/40"
      />
      <div
        ref={panelRef}
        className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col border-l border-line bg-surface shadow-card"
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="font-display text-base font-bold text-ink">{title}</h2>
          <button
            type="button"
            onClick={close}
            className="inline-flex h-11 w-11 items-center justify-center rounded-brand text-ink hover:bg-surface-muted"
          >
            <span className="sr-only">{closeLabel}</span>
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              className="h-5 w-5"
              aria-hidden="true"
              focusable="false"
            >
              <path d="m6 6 12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
      </div>
    </div>
  )
}
