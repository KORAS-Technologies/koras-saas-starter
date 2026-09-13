import type { RefObject } from 'react'
import { Icon } from '../primitives/icon'
import { cn } from '../lib/cn'

/**
 * The button that opens the assistant.
 *
 * The same shape as the shell's own header controls: 44px, a border, an icon,
 * and an accessible name that says what it opens. `aria-expanded` and
 * `aria-controls` point at the drawer, which is rendered in both states so
 * the reference is real before the control is ever used.
 */
export function AITrigger({
  open,
  controls,
  label,
  onClick,
  buttonRef,
  className,
}: {
  open: boolean
  controls: string
  /** Already translated: "Open the assistant". */
  label: string
  onClick: () => void
  buttonRef?: RefObject<HTMLButtonElement | null>
  className?: string
}) {
  return (
    <button
      ref={buttonRef}
      type="button"
      onClick={onClick}
      aria-expanded={open}
      aria-controls={controls}
      data-testid="assistant-trigger"
      className={cn(
        'inline-flex min-h-11 items-center gap-2 rounded-brand border border-line px-3 text-sm font-medium text-ink hover:bg-surface-muted',
        open && 'bg-brand/10 text-brand',
        className,
      )}
    >
      <Icon name="sparkle" className="h-5 w-5 shrink-0" />
      <span className="sr-only sm:not-sr-only">{label}</span>
    </button>
  )
}
