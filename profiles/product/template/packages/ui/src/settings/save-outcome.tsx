'use client'

import { useEffect, useRef } from 'react'

/**
 * What happened to a save, announced and given focus.
 *
 * **SET-24.** Both settings pages answer a save by redirecting with a flag,
 * which is deliberate: a redirect works without JavaScript, survives a reload,
 * and says the same thing to everybody. But a redirect reloads the document,
 * and that has two costs a `role="status"` paragraph does not pay off.
 *
 * *Focus is lost.* It resets from the control somebody was using to `BODY`, so
 * anybody working by keyboard tabs back to their place after every save.
 * Measured on 2026-09-22 against a deployed product: focus went from the
 * `ui.density` select to `BODY` on each save, at 1440 and at 375.
 *
 * *And the message may never be announced.* A live region announces the
 * changes made to it **after it exists**. Arriving by redirect, this text is
 * already there when the document loads, so there is no change to announce —
 * the one signal that the save worked can be silent for exactly the people the
 * region was added for.
 *
 * Moving focus here fixes both at once, and fixes the announcement in a way
 * that does not depend on live-region semantics at all: a screen reader reads
 * what it lands on. The reader keeps their place *at the confirmation*, which
 * is where somebody who just saved wants to be.
 *
 * **`tabIndex={-1}` and no focus ring by design.** The element is reachable
 * programmatically and not in the tab order — it is a message, not a control,
 * and adding it to the sequence would make everybody tab past a sentence on
 * every visit. Browsers do not match `:focus-visible` on a programmatic focus
 * of a `tabIndex={-1}` element, so nothing is drawn, which is correct: a ring
 * appears when somebody navigates to a thing, and nobody navigated here.
 *
 * **Strings only across the boundary.** Every prop here is a string, because
 * this is a client component and a function cannot cross that line — the
 * defect PLAT-DEF-008 recorded, and the reason `SettingsFormLabels.resetTo` is
 * a template filled on this side rather than a closure.
 *
 * Without JavaScript the paragraph still renders with its message, still
 * carries `role="status"`, and only the focus move is lost. That is the right
 * thing to degrade.
 */
export function SaveOutcome({
  message,
  outcome,
  testId,
  className,
}: {
  /** The sentence to show, already translated by the page. */
  message: string
  /** `ok`, `error`, `forbidden` — whatever the page's flag carried. Published as `data-outcome`. */
  outcome: string
  testId: string
  className?: string
}) {
  const ref = useRef<HTMLParagraphElement>(null)

  useEffect(() => {
    // Mount only. The component is rendered solely when a save just happened,
    // so there is no second render to guard against and no dependency that
    // could move focus a second time while somebody is reading.
    ref.current?.focus()
  }, [])

  return (
    <p
      ref={ref}
      tabIndex={-1}
      role="status"
      data-testid={testId}
      data-outcome={outcome}
      className={className}
    >
      {message}
    </p>
  )
}
